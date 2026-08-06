import discord
from discord import app_commands
from discord.ext import commands

from core.database import (
    load_dashboard_config,
    load_thread_mappings,
    save_dashboard_config,
    save_thread_mappings,
)


class ThreadSync(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def update_dashboard(self, guild: discord.Guild):
        """Builds and edits the live-updating embed in the designated dashboard channel."""
        dash_config = load_dashboard_config()
        channel_id = dash_config.get("channel_id")
        message_id = dash_config.get("message_id")

        if not channel_id:
            return

        channel = guild.get_channel(channel_id)
        if not channel:
            try:
                channel = await guild.fetch_channel(channel_id)
            except (discord.NotFound, discord.HTTPException):
                return

        if not isinstance(channel, discord.TextChannel):
            return

        mappings = load_thread_mappings()

        # Build Embed Base
        embed = discord.Embed(
            title="📌 Role ➔ Thread Auto-Sync Dashboard",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow(),
        )

        embed.add_field(
            name="📖 Purpose & How It Works",
            value=(
                "Thread Mapping automatically manages member access to private threads based on Discord roles.\n"
                "• **Role Added:** When a member receives a linked role, the bot immediately adds them to the corresponding thread.\n"
                "• **Role Removed:** When the role is removed, the bot automatically removes them from the thread."
            ),
            inline=False,
        )

        embed.add_field(
            name="🛠️ Staff Instructions",
            value=(
                "• Run `/link_thread role:@Role` inside a thread (or specify the thread) to link access.\n"
                "• Run `/unlink_thread role:@Role` inside a thread to remove the auto-sync connection."
            ),
            inline=False,
        )

        valid_mappings = []
        grouped_by_role: dict[int, list[dict]] = {}

        if mappings:
            for entry in mappings:
                role_id = entry.get("role_id")
                thread_id = entry.get("thread_id")

                role = guild.get_role(int(role_id)) if role_id else None

                thread = guild.get_thread(int(thread_id)) if thread_id else None
                if not thread and thread_id:
                    try:
                        thread = await guild.fetch_channel(int(thread_id))
                    except (discord.NotFound, discord.HTTPException):
                        thread = None

                if not thread or not role:
                    continue

                valid_mappings.append(entry)
                grouped_by_role.setdefault(int(role_id), []).append(
                    {"thread": thread, "creator_id": entry.get("created_by")}
                )

            if len(valid_mappings) < len(mappings):
                save_thread_mappings(valid_mappings)

        if not grouped_by_role:
            embed.add_field(
                name="🔗 Active Links",
                value="*No roles are currently linked to threads.*",
                inline=False,
            )
        else:
            embed.add_field(
                name="🔗 Active Links (Grouped by Role)",
                value="───────────────",
                inline=False,
            )

            for role_id, items in grouped_by_role.items():
                role = guild.get_role(role_id)
                role_name = f"@{role.name}" if role else "Unknown Role"
                role_mention = role.mention if role else f"`ID: {role_id}`"

                thread_lines = []
                for item in items:
                    thr = item["thread"]
                    cid = item["creator_id"]
                    creator_str = f"<@{cid}>" if cid else "System"
                    archived_tag = (
                        " *(Archived)*" if getattr(thr, "archived", False) else ""
                    )
                    thread_lines.append(
                        f"• {thr.mention}{archived_tag} *(Added by {creator_str})*"
                    )

                embed.add_field(
                    name=f"🛡️ {role_name}",
                    value=f"**Role:** {role_mention}\n" + "\n".join(thread_lines),
                    inline=False,
                )

        embed.set_footer(text="Auto-updates live on link / unlink")

        try:
            if message_id:
                try:
                    msg = await channel.fetch_message(message_id)
                    await msg.edit(embed=embed)
                    return
                except discord.NotFound:
                    pass

            msg = await channel.send(embed=embed)

            try:
                await msg.pin(reason="Live Thread-Sync Dashboard")
            except (discord.Forbidden, discord.HTTPException):
                pass

            save_dashboard_config(channel_id=channel.id, message_id=msg.id)

        except (discord.Forbidden, discord.HTTPException) as e:
            print(f"❌ Dashboard update error in #{channel.name}: {e}")

    # -------------------------------------------------------------------------
    # SELF-HEALING EVENT LISTENERS
    # -------------------------------------------------------------------------
    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role):
        mappings = load_thread_mappings()
        if not mappings:
            return

        new_mappings = [item for item in mappings if item.get("role_id") != role.id]
        if len(new_mappings) < len(mappings):
            save_thread_mappings(new_mappings)
            await self.update_dashboard(role.guild)

    @commands.Cog.listener()
    async def on_thread_delete(self, thread: discord.Thread):
        mappings = load_thread_mappings()
        if not mappings:
            return

        new_mappings = [
            item for item in mappings if item.get("thread_id") != thread.id
        ]
        if len(new_mappings) < len(mappings):
            save_thread_mappings(new_mappings)
            await self.update_dashboard(thread.guild)

    @commands.Cog.listener()
    async def on_raw_thread_delete(self, payload: discord.RawThreadDeleteEvent):
        mappings = load_thread_mappings()
        if not mappings:
            return

        new_mappings = [
            item for item in mappings if item.get("thread_id") != payload.thread_id
        ]
        if len(new_mappings) < len(mappings):
            save_thread_mappings(new_mappings)
            guild = self.bot.get_guild(payload.guild_id)
            if guild:
                await self.update_dashboard(guild)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        """Triggers when a member's roles change."""
        before_roles = set(before.roles)
        after_roles = set(after.roles)

        added_roles = after_roles - before_roles
        removed_roles = before_roles - after_roles

        if not added_roles and not removed_roles:
            return

        mappings = load_thread_mappings()
        if not mappings:
            return

        # Role Addition
        for role in added_roles:
            matched_entries = [
                item for item in mappings if item.get("role_id") == role.id
            ]
            for entry in matched_entries:
                thread_id = entry.get("thread_id")
                try:
                    thread = after.guild.get_thread(
                        thread_id
                    ) or await after.guild.fetch_channel(thread_id)
                    if isinstance(thread, discord.Thread):
                        try:
                            await thread.add_user(
                                discord.Object(id=self.bot.user.id)
                            )
                        except discord.HTTPException:
                            pass

                        await thread.add_user(discord.Object(id=after.id))
                        print(
                            f"✅ Added {after.display_name} to thread '{thread.name}' via role @{role.name}"
                        )
                except (discord.NotFound, discord.Forbidden, discord.HTTPException) as e:
                    print(f"⚠️ Error adding {after.display_name} to thread: {e}")

        # Role Removal
        for role in removed_roles:
            matched_entries = [
                item for item in mappings if item.get("role_id") == role.id
            ]
            for entry in matched_entries:
                thread_id = entry.get("thread_id")
                try:
                    thread = before.guild.get_thread(
                        thread_id
                    ) or await before.guild.fetch_channel(thread_id)
                    if isinstance(thread, discord.Thread):
                        await thread.remove_user(discord.Object(id=before.id))
                        print(
                            f"✅ Removed {before.display_name} from thread '{thread.name}' after role removal @{role.name}"
                        )
                except (discord.NotFound, discord.Forbidden, discord.HTTPException) as e:
                    print(f"⚠️ Error removing {before.display_name} from thread: {e}")

    # -------------------------------------------------------------------------
    # SLASH COMMANDS
    # -------------------------------------------------------------------------
    @app_commands.command(
        name="link_thread",
        description="Link a Discord Role to a Private Thread.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def link_thread(
        self,
        interaction: discord.Interaction,
        role: discord.Role,
        thread: discord.Thread | None = None,
    ):
        target_thread = thread or interaction.channel

        if not isinstance(target_thread, discord.Thread):
            await interaction.response.send_message(
                "❌ You must either specify a thread in the `thread` option or run this command inside the target thread!",
                ephemeral=True,
            )
            return

        mappings = load_thread_mappings()

        exists = any(
            item.get("role_id") == role.id
            and item.get("thread_id") == target_thread.id
            for item in mappings
        )
        if exists:
            await interaction.response.send_message(
                f"⚠️ **@{role.name}** is already linked to **{target_thread.name}**!",
                ephemeral=True,
            )
            return

        mappings.append(
            {
                "role_id": role.id,
                "thread_id": target_thread.id,
                "created_by": interaction.user.id,
            }
        )
        save_thread_mappings(mappings)

        try:
            await target_thread.add_user(discord.Object(id=self.bot.user.id))
        except discord.HTTPException:
            pass

        await interaction.response.send_message(
            f"✅ Linked **@{role.name}** to thread **{target_thread.name}**!",
            ephemeral=True,
        )

        await self.update_dashboard(interaction.guild)

    @app_commands.command(
        name="unlink_thread",
        description="Unlink a role from a specific thread.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def unlink_thread(
        self,
        interaction: discord.Interaction,
        role: discord.Role,
        thread: discord.Thread | None = None,
    ):
        target_thread = thread or interaction.channel

        if not isinstance(target_thread, discord.Thread):
            await interaction.response.send_message(
                "❌ You must either run this command **inside the thread** or select a valid thread in the `thread` option!",
                ephemeral=True,
            )
            return

        mappings = load_thread_mappings()

        new_mappings = [
            item
            for item in mappings
            if not (
                item.get("role_id") == role.id
                and item.get("thread_id") == target_thread.id
            )
        ]

        if len(new_mappings) < len(mappings):
            save_thread_mappings(new_mappings)
            await interaction.response.send_message(
                f"✅ Successfully unlinked **@{role.name}** from thread **{target_thread.name}**!",
                ephemeral=True,
            )
            await self.update_dashboard(interaction.guild)
        else:
            await interaction.response.send_message(
                f"⚠️ No active link found between **@{role.name}** and thread **{target_thread.name}**.",
                ephemeral=True,
            )

    @app_commands.command(
        name="set_sync_channel",
        description="Set the channel where the live role-thread dashboard lives.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def set_sync_channel(
        self, interaction: discord.Interaction, channel: discord.TextChannel
    ):
        await interaction.response.defer(ephemeral=True)

        dash_config = load_dashboard_config()
        old_channel_id = dash_config.get("channel_id")
        old_message_id = dash_config.get("message_id")

        if old_channel_id and old_message_id:
            try:
                old_channel = interaction.guild.get_channel(
                    old_channel_id
                ) or await interaction.guild.fetch_channel(old_channel_id)
                if isinstance(old_channel, discord.TextChannel):
                    old_msg = await old_channel.fetch_message(old_message_id)
                    await old_msg.delete()
            except (discord.NotFound, discord.HTTPException, discord.Forbidden):
                pass

        save_dashboard_config(channel_id=channel.id, message_id=None)
        await self.update_dashboard(interaction.guild)

        await interaction.followup.send(
            f"✅ Live dashboard set to {channel.mention}!", ephemeral=True
        )

    @app_commands.command(
        name="remove_sync_channel",
        description="Remove the live dashboard embed and stop dashboard updates.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def remove_sync_channel(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        dash_config = load_dashboard_config()
        channel_id = dash_config.get("channel_id")
        message_id = dash_config.get("message_id")

        if not channel_id:
            await interaction.followup.send(
                "⚠️ No dashboard channel is currently set.", ephemeral=True
            )
            return

        if message_id:
            try:
                channel = interaction.guild.get_channel(
                    channel_id
                ) or await interaction.guild.fetch_channel(channel_id)
                if isinstance(channel, discord.TextChannel):
                    msg = await channel.fetch_message(message_id)
                    await msg.delete()
            except (discord.NotFound, discord.HTTPException, discord.Forbidden):
                pass

        save_dashboard_config(channel_id=None, message_id=None)

        await interaction.followup.send(
            "✅ Sync dashboard channel removed and embed cleared!",
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(ThreadSync(bot))