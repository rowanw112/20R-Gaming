import asyncio
import logging
import discord
from discord import app_commands
from discord.ext import commands

from core.database import (
    load_hub_dashboard_config,
    load_thread_mappings,
    save_hub_dashboard_config,
    save_thread_mappings,
)

logger = logging.getLogger(__name__)


class ThreadSync(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._sync_lock = asyncio.Lock()

    async def get_or_fetch_thread(
        self, guild: discord.Guild, thread_id: int
    ) -> discord.Thread | None:
        """Safely fetches a thread from cache, guild active threads, or Discord API."""
        thread = guild.get_thread(thread_id)
        if isinstance(thread, discord.Thread):
            return thread

        for t in guild.threads:
            if t.id == thread_id:
                return t

        try:
            ch = await guild.fetch_channel(thread_id)
            if isinstance(ch, discord.Thread):
                return ch
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass

        return None

    async def update_dashboard(self, guild: discord.Guild):
        """Builds and edits the live-updating embed grouped by normalized Game Hubs and Standalone links."""
        dash_config = load_hub_dashboard_config()
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

        embed = discord.Embed(
            title="📌 Role ➔ Thread Auto-Sync Dashboard",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow(),
        )

        embed.add_field(
            name="📖 Purpose & How It Works",
            value=(
                "Thread Mapping automatically manages member access to private threads based on Discord roles.\n"
                "• **Role Added:** Member receives role ➔ added to thread.\n"
                "• **Role Removed:** Role removed ➔ removed from thread."
            ),
            inline=False,
        )

        embed.add_field(
            name="🛠️ Staff Instructions",
            value=(
                "• `/link_thread role:@Role` — Link access inside a thread.\n"
                "• `/unlink_thread role:@Role` — Remove thread connection.\n"
                "• `/force_thread_sync` — Run full audit and sync members."
            ),
            inline=False,
        )

        if not mappings:
            embed.add_field(
                name="🔗 Active Links",
                value="*No roles are currently linked to threads.*",
                inline=False,
            )
        else:
            grouped_games: dict[str, dict[str, any]] = {}
            standalone_links: list[tuple[discord.Role, discord.Thread]] = []

            # Keywords table for grouping games together
            GAME_MAP = {
                "bf6": "BF6",
                "rl": "Rocket League",
                "rocket": "Rocket League",
                "rust": "Rust",
                "squad": "Squad",
                "wardogs": "Wardogs",
                "helldivers": "Helldivers",
            }

            for entry in mappings:
                if not isinstance(entry, dict):
                    continue

                r_id = entry.get("role_id")
                t_id = entry.get("thread_id")

                role = guild.get_role(int(r_id)) if r_id else None
                thread = (
                    await self.get_or_fetch_thread(guild, int(t_id)) if t_id else None
                )

                if not role or not thread:
                    continue

                raw_role_name = role.name.lower()

                # Search for game keyword match
                matched_game = None
                for key, display_name in GAME_MAP.items():
                    if key in raw_role_name:
                        matched_game = display_name
                        break

                if matched_game:
                    if matched_game not in grouped_games:
                        grouped_games[matched_game] = {
                            "roles": set(),
                            "threads": set(),
                            "has_division_role": False,
                        }

                    grouped_games[matched_game]["roles"].add(role)
                    grouped_games[matched_game]["threads"].add(thread)

                    # Mark if any linked role for this game explicitly uses "Division"
                    if "division" in raw_role_name:
                        grouped_games[matched_game]["has_division_role"] = True
                else:
                    standalone_links.append((role, thread))

            # 1. Render Grouped Game Hubs
            for game_name, data in sorted(grouped_games.items()):
                roles_list = sorted(list(data["roles"]), key=lambda r: r.name)
                threads_list = sorted(list(data["threads"]), key=lambda t: t.name)

                role_mentions = " • ".join([r.mention for r in roles_list])
                thread_mentions = ", ".join([f"🔒 {t.mention}" for t in threads_list])

                field_value = (
                    f"**Linked Roles:** {role_mentions}\n"
                    f"**Hub Threads:** {thread_mentions}"
                )

                # Only include "Division" in header if a division role is linked
                header_title = (
                    f"🎮 {game_name} Division"
                    if data["has_division_role"]
                    else f"🎮 {game_name}"
                )

                embed.add_field(
                    name=header_title,
                    value=field_value,
                    inline=False,
                )

            # 2. Render Non-Game / Standalone Thread Links
            if standalone_links:
                custom_lines = [
                    f"• {role.mention} ➔ 🔒 {thread.mention}"
                    for role, thread in standalone_links
                ]
                embed.add_field(
                    name="🔗 Custom / Standalone Role Links",
                    value="\n".join(custom_lines),
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

            dash_config["channel_id"] = channel.id
            dash_config["message_id"] = msg.id
            save_hub_dashboard_config(dash_config)

        except (discord.Forbidden, discord.HTTPException) as e:
            logger.error(f"❌ Dashboard update error in #{channel.name}: {e}")

    async def run_full_thread_audit(self, guild: discord.Guild):
        """Audits mapped threads without purging valid uncached threads."""
        mappings = load_thread_mappings()
        if not mappings:
            logger.info("✅ No thread mappings found. Skipping audit.")
            return

        sanitized_mappings = []
        for entry in mappings:
            if not isinstance(entry, dict):
                continue

            t_id = entry.get("thread_id")
            r_id = entry.get("role_id")

            role_exists = guild.get_role(int(r_id)) if r_id else None
            thread_exists = (
                await self.get_or_fetch_thread(guild, int(t_id)) if t_id else None
            )

            if role_exists and thread_exists:
                sanitized_mappings.append(entry)

        if len(sanitized_mappings) < len(mappings):
            logger.info(
                f"🧹 [Database Sanitation] Purged {len(mappings) - len(sanitized_mappings)} orphaned mapping entry(ies)."
            )
            save_thread_mappings(sanitized_mappings)
            mappings = sanitized_mappings

        if not mappings:
            return

        thread_to_roles: dict[int, set[int]] = {}
        for entry in mappings:
            if not isinstance(entry, dict):
                continue
            t_id = entry.get("thread_id")
            r_id = entry.get("role_id")
            if t_id and r_id:
                thread_to_roles.setdefault(int(t_id), set()).add(int(r_id))

        for thread_id, allowed_role_ids in thread_to_roles.items():
            thread = await self.get_or_fetch_thread(guild, thread_id)
            if not thread:
                continue

            try:
                await thread.add_user(discord.Object(id=self.bot.user.id))
            except discord.HTTPException:
                pass

            role_member_ids = {
                m.id
                for m in guild.members
                if not m.bot and any(r.id in allowed_role_ids for r in m.roles)
            }

            exempt_user_ids = {
                m.id
                for m in guild.members
                if not m.bot
                and (
                    m.guild_permissions.administrator
                    or m.guild_permissions.manage_threads
                    or thread.permissions_for(m).manage_threads
                )
            }

            target_member_ids = role_member_ids.union(exempt_user_ids)

            try:
                existing_thread_members = await thread.fetch_members()
                existing_user_ids = {tm.id for tm in existing_thread_members}
            except (discord.Forbidden, discord.HTTPException) as e:
                logger.error(f"Could not fetch members for thread {thread.name}: {e}")
                continue

            # 1. Add missing role members
            missing_user_ids = role_member_ids - existing_user_ids
            for user_id in missing_user_ids:
                try:
                    await thread.add_user(discord.Object(id=user_id))
                    await asyncio.sleep(0.25)
                except discord.HTTPException as e:
                    if e.status == 429:
                        retry_after = float(e.response.headers.get("Retry-After", 5))
                        await asyncio.sleep(retry_after)

            # 2. Remove extra members
            extra_user_ids = existing_user_ids - target_member_ids - {self.bot.user.id}
            for user_id in extra_user_ids:
                try:
                    await thread.remove_user(discord.Object(id=user_id))
                    await asyncio.sleep(0.25)
                except discord.HTTPException as e:
                    if e.status == 429:
                        retry_after = float(e.response.headers.get("Retry-After", 5))
                        await asyncio.sleep(retry_after)

    # -------------------------------------------------------------------------
    # LISTENERS & COMMANDS
    # -------------------------------------------------------------------------
    @commands.Cog.listener()
    async def on_ready(self):
        if self._sync_lock.locked():
            return

        async with self._sync_lock:
            logger.info("🔄 Running post-downtime Thread Sync audit...")
            for guild in self.bot.guilds:
                await self.run_full_thread_audit(guild)
                await self.update_dashboard(guild)
            logger.info(
                "✅ Post-downtime Thread Sync audit & dashboard update complete!"
            )

    @app_commands.command(
        name="force_thread_sync",
        description="Manually audit and sync missing users across all mapped threads.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def force_thread_sync(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await self.run_full_thread_audit(interaction.guild)
        await self.update_dashboard(interaction.guild)
        await interaction.followup.send(
            "✅ **Thread Sync Audit Complete!** Checked all mapped threads and reconciled member access.",
            ephemeral=True,
        )

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
                "❌ You must specify a thread in the `thread` option or run this inside the target thread!",
                ephemeral=True,
            )
            return

        mappings = load_thread_mappings()

        exists = any(
            isinstance(item, dict)
            and item.get("role_id") == role.id
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
                "❌ You must specify a thread in the `thread` option or run this inside the target thread!",
                ephemeral=True,
            )
            return

        mappings = load_thread_mappings()

        new_mappings = [
            item
            for item in mappings
            if not (
                isinstance(item, dict)
                and item.get("role_id") == role.id
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
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel | None = None,
    ):
        await interaction.response.defer(ephemeral=True)

        target_channel = channel or interaction.channel
        if not isinstance(target_channel, discord.TextChannel):
            await interaction.followup.send(
                "❌ Must be run in a text channel or specify a text channel!",
                ephemeral=True,
            )
            return

        dash_config = load_hub_dashboard_config()
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

        dash_config["channel_id"] = target_channel.id
        dash_config["message_id"] = None
        save_hub_dashboard_config(dash_config)

        await self.update_dashboard(interaction.guild)

        await interaction.followup.send(
            f"✅ Live dashboard set to {target_channel.mention}!", ephemeral=True
        )

    @app_commands.command(
        name="remove_sync_channel",
        description="Remove the live dashboard embed and stop dashboard updates.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def remove_sync_channel(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        dash_config = load_hub_dashboard_config()
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

        dash_config["channel_id"] = None
        dash_config["message_id"] = None
        save_hub_dashboard_config(dash_config)

        await interaction.followup.send(
            "✅ Sync dashboard channel removed and embed cleared!",
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(ThreadSync(bot))