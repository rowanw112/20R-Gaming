import asyncio
import logging
import discord
from discord import app_commands
from discord.ext import commands

from core.database import (
    load_thread_mappings,
    save_thread_mappings,
)

logger = logging.getLogger(__name__)


class ThreadCreator(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="create_threads",
        description="Bulk creates threads and optionally links a role with auto-sync access.",
    )
    @app_commands.checks.has_permissions(manage_roles=True)
    @app_commands.describe(
        thread_names="List of thread names (separated by newlines or commas)",
        role="Optional role to link to these threads for auto-sync access",
        private="Set to True for Private threads, False for Public threads (Default: True)",
        channel="Target channel to create threads in (Defaults to current channel)",
    )
    async def create_threads(
        self,
        interaction: discord.Interaction,
        thread_names: str,
        role: discord.Role | None = None,
        private: bool = True,
        channel: discord.TextChannel = None,
    ):
        await interaction.response.defer(ephemeral=True)

        target_channel = channel or interaction.channel
        if not isinstance(target_channel, discord.TextChannel):
            await interaction.followup.send(
                "❌ Threads can only be created inside standard Text Channels.",
                ephemeral=True,
            )
            return

        raw_list = thread_names.replace(",", "\n").split("\n")
        parsed_names = [name.strip() for name in raw_list if name.strip()]

        if not parsed_names:
            await interaction.followup.send(
                "❌ No valid thread names provided.", ephemeral=True
            )
            return

        thread_type_str = "Private" if private else "Public"
        created_threads = []
        failed_threads = []

        mappings = load_thread_mappings() or []

        for name in parsed_names:
            try:
                thread_type = (
                    discord.ChannelType.private_thread
                    if private
                    else discord.ChannelType.public_thread
                )
                thread = await target_channel.create_thread(
                    name=name,
                    type=thread_type,
                    reason=f"Bulk creation requested by {interaction.user}",
                )

                try:
                    await thread.add_user(discord.Object(id=self.bot.user.id))
                except discord.HTTPException:
                    pass

                try:
                    await thread.add_user(interaction.user)
                except discord.HTTPException:
                    pass

                if role:
                    exists = any(
                        item.get("role_id") == role.id
                        and item.get("thread_id") == thread.id
                        for item in mappings
                    )
                    if not exists:
                        mappings.append(
                            {
                                "role_id": role.id,
                                "thread_id": thread.id,
                                "created_by": interaction.user.id,
                            }
                        )

                    for member in role.members:
                        if not member.bot:
                            try:
                                await thread.add_user(discord.Object(id=member.id))
                                await asyncio.sleep(0.2)
                            except discord.HTTPException:
                                pass

                created_threads.append(thread)
                await asyncio.sleep(0.5)

            except discord.HTTPException as e:
                failed_threads.append(f"`{name}` ({e.text})")

        if role and created_threads:
            save_thread_mappings(mappings)
            thread_sync_cog = self.bot.get_cog("ThreadSync")
            if thread_sync_cog:
                await thread_sync_cog.update_dashboard(interaction.guild)

        summary = [
            f"✅ **Successfully created {len(created_threads)} {thread_type_str} thread(s) in {target_channel.mention}:**"
        ]
        if role:
            summary.append(f"🔗 **Linked Role:** {role.mention}\n")

        for t in created_threads:
            summary.append(f"• {t.mention}")

        if failed_threads:
            summary.append(f"\n❌ **Failed ({len(failed_threads)}):**")
            for f_err in failed_threads:
                summary.append(f"• {f_err}")

        await interaction.followup.send("\n".join(summary), ephemeral=True)

    @app_commands.command(
        name="link_thread",
        description="Link a role to a private thread for auto-sync access.",
    )
    @app_commands.checks.has_permissions(manage_roles=True)
    async def link_thread(
        self,
        interaction: discord.Interaction,
        role: discord.Role,
        thread: discord.Thread,
    ):
        await interaction.response.defer(ephemeral=True)

        mappings = load_thread_mappings() or []
        exists = any(
            m.get("role_id") == role.id and m.get("thread_id") == thread.id
            for m in mappings
        )

        if exists:
            await interaction.followup.send(
                f"⚠️ {role.mention} is already linked to {thread.mention}.",
                ephemeral=True,
            )
            return

        mappings.append(
            {
                "role_id": role.id,
                "thread_id": thread.id,
                "created_by": interaction.user.id,
            }
        )
        save_thread_mappings(mappings)

        thread_sync_cog = self.bot.get_cog("ThreadSync")
        if thread_sync_cog:
            await thread_sync_cog.run_full_thread_audit(interaction.guild)
            await thread_sync_cog.update_dashboard(interaction.guild)

        await interaction.followup.send(
            f"✅ Linked {role.mention} ➔ {thread.mention}! Role holders have been synchronized.",
            ephemeral=True,
        )

    @app_commands.command(
        name="unlink_thread",
        description="Unlink a role from a private thread.",
    )
    @app_commands.checks.has_permissions(manage_roles=True)
    async def unlink_thread(
        self,
        interaction: discord.Interaction,
        role: discord.Role,
        thread: discord.Thread,
    ):
        await interaction.response.defer(ephemeral=True)

        mappings = load_thread_mappings() or []
        new_mappings = [
            m
            for m in mappings
            if not (m.get("role_id") == role.id and m.get("thread_id") == thread.id)
        ]

        if len(new_mappings) == len(mappings):
            await interaction.followup.send(
                f"⚠️ No active mapping found between {role.mention} and {thread.mention}.",
                ephemeral=True,
            )
            return

        save_thread_mappings(new_mappings)

        thread_sync_cog = self.bot.get_cog("ThreadSync")
        if thread_sync_cog:
            await thread_sync_cog.update_dashboard(interaction.guild)

        await interaction.followup.send(
            f"✅ Unlinked {role.mention} from {thread.mention}.",
            ephemeral=True,
        )

    @create_threads.error
    @link_thread.error
    @unlink_thread.error
    async def command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ):
        if isinstance(error, app_commands.MissingPermissions):
            msg = "❌ You need the `Manage Roles` permission to run this command."
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(ThreadCreator(bot))