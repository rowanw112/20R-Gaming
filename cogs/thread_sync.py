import logging
import discord
from discord.ext import commands

from core.database import (
    load_thread_mappings,
    load_thread_sync_dashboard_config,
    save_thread_sync_dashboard_config,
)

logger = logging.getLogger(__name__)


class ThreadSync(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        """Runs a full thread audit and refreshes the Thread Sync Dashboard on startup."""
        logger.info("[ThreadSync] 🔄 Running startup thread audit & dashboard refresh...")
        for guild in self.bot.guilds:
            try:
                await self.run_full_thread_audit(guild)
                await self.update_dashboard(guild)
            except Exception as e:
                logger.error(f"[ThreadSync] Error during startup sync for '{guild.name}': {e}")
        logger.info("[ThreadSync] ✅ Startup thread audit complete!")

    async def run_full_thread_audit(self, guild: discord.Guild):
        """Audits all mapped private threads and adds members holding the required role."""
        mappings = load_thread_mappings() or []
        if not mappings:
            return

        for mapping in mappings:
            role_id = mapping.get("role_id")
            thread_id = mapping.get("thread_id")

            if not role_id or not thread_id:
                continue

            role = guild.get_role(role_id)
            thread = guild.get_thread(thread_id)

            if not thread:
                try:
                    thread = await guild.fetch_channel(thread_id)
                except (discord.NotFound, discord.HTTPException):
                    continue

            if not role or not isinstance(thread, discord.Thread):
                continue

            # Add all role holders to the private thread
            for member in role.members:
                if not member.bot:
                    try:
                        await thread.add_user(member)
                    except discord.HTTPException as e:
                        logger.error(f"[ThreadSync] Failed to add {member.display_name} to #{thread.name}: {e}")

    async def update_dashboard(self, guild: discord.Guild):
        """Updates or posts the live Thread Sync Dashboard embed, grouping threads that share role sets."""
        dash_cfg = load_thread_sync_dashboard_config()
        channel_id = dash_cfg.get("channel_id")
        message_id = dash_cfg.get("message_id")

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

        mappings = load_thread_mappings() or []

        embed = discord.Embed(
            title="🧵 Private Thread Sync Dashboard",
            description="Live mapping of private hub threads and their synchronized roles.",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow(),
        )

        # 1. Map threads to their list of role IDs
        thread_to_roles: dict[int, list[int]] = {}
        for m in mappings:
            t_id = m.get("thread_id")
            r_id = m.get("role_id")
            if t_id and r_id:
                if t_id not in thread_to_roles:
                    thread_to_roles[t_id] = []
                if r_id not in thread_to_roles[t_id]:
                    thread_to_roles[t_id].append(r_id)

        # 2. Group threads that share the exact same set of roles
        # Key: tuple of sorted role_ids, Value: list of thread_ids
        role_set_to_threads: dict[tuple[int, ...], list[int]] = {}
        for t_id, r_ids in thread_to_roles.items():
            role_key = tuple(sorted(r_ids))
            if role_key not in role_set_to_threads:
                role_set_to_threads[role_key] = []
            if t_id not in role_set_to_threads[role_key]:
                role_set_to_threads[role_key].append(t_id)

        # 3. Format lines
        mapping_lines = []
        for role_tuple, t_ids in role_set_to_threads.items():
            # Format thread mentions
            thread_mentions = []
            for t_id in t_ids:
                t = guild.get_thread(t_id)
                if not t:
                    try:
                        t = guild.get_channel(t_id)
                    except (discord.NotFound, discord.HTTPException):
                        pass
                thread_mentions.append(f"🔒 {t.mention}" if t else f"`Thread ID: {t_id}`")

            # Format role mentions
            role_mentions = []
            for r_id in role_tuple:
                r = guild.get_role(r_id)
                role_mentions.append(r.mention if r else f"`Role ID: {r_id}`")

            threads_str = ", ".join(thread_mentions)
            roles_str = ", ".join(role_mentions)
            mapping_lines.append(f"• {threads_str} ➔ {roles_str}")

        # 4. Chunk fields safely (<1024 chars limit)
        if not mapping_lines:
            embed.add_field(
                name="📍 Mapped Sync Routes",
                value="*No active thread mappings found.*",
                inline=False,
            )
        else:
            chunks = []
            current_chunk = []
            current_length = 0

            for line in mapping_lines:
                line_len = len(line) + 1  # include newline
                if current_length + line_len > 1000:
                    chunks.append("\n".join(current_chunk))
                    current_chunk = [line]
                    current_length = line_len
                else:
                    current_chunk.append(line)
                    current_length += line_len

            if current_chunk:
                chunks.append("\n".join(current_chunk))

            for idx, chunk in enumerate(chunks):
                field_title = "📍 Mapped Sync Routes" if idx == 0 else f"📍 Mapped Sync Routes (Part {idx + 1})"
                embed.add_field(name=field_title, value=chunk, inline=False)

        embed.set_footer(text="Auto-updates live on division creation or teardown.")

        if message_id:
            try:
                msg = await channel.fetch_message(message_id)
                await msg.edit(embed=embed)
                return
            except (discord.NotFound, discord.HTTPException):
                pass

        try:
            posted_msg = await channel.send(embed=embed)
            try:
                await posted_msg.pin(reason="Live Thread Sync Dashboard")
            except (discord.Forbidden, discord.HTTPException):
                pass

            dash_cfg["channel_id"] = channel.id
            dash_cfg["message_id"] = posted_msg.id
            save_thread_sync_dashboard_config(dash_cfg)

        except (discord.Forbidden, discord.HTTPException) as e:
            logger.error(f"❌ Error posting Thread Sync Dashboard in #{channel.name}: {e}")

    # -------------------------------------------------------------------------
    # REAL-TIME ROLE TOGGLE LISTENER
    # -------------------------------------------------------------------------
    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        """Listens for member role additions/removals and syncs thread memberships."""
        if after.bot:
            return

        before_roles = set(before.roles)
        after_roles = set(after.roles)

        added_roles = after_roles - before_roles
        removed_roles = before_roles - after_roles

        if not added_roles and not removed_roles:
            return

        mappings = load_thread_mappings() or []
        if not mappings:
            return

        # 1. Process Role Additions
        for role in added_roles:
            for mapping in mappings:
                if mapping.get("role_id") == role.id:
                    thread_id = mapping.get("thread_id")
                    if not thread_id:
                        continue

                    thread = after.guild.get_thread(thread_id)
                    if not thread:
                        try:
                            thread = await after.guild.fetch_channel(thread_id)
                        except (discord.NotFound, discord.HTTPException):
                            continue

                    if isinstance(thread, discord.Thread):
                        try:
                            await thread.add_user(after)
                            logger.info(f"[ThreadSync] Added {after.display_name} to thread '{thread.name}' via role '{role.name}'.")
                        except (discord.Forbidden, discord.HTTPException) as e:
                            logger.error(f"[ThreadSync] Failed to add {after.display_name} to thread '{thread.name}': {e}")

        # 2. Process Role Removals
        for role in removed_roles:
            for mapping in mappings:
                if mapping.get("role_id") == role.id:
                    thread_id = mapping.get("thread_id")
                    if not thread_id:
                        continue

                    other_mapped_roles = {
                        m.get("role_id")
                        for m in mappings
                        if m.get("thread_id") == thread_id and m.get("role_id") != role.id
                    }
                    user_role_ids = {r.id for r in after.roles}

                    if user_role_ids.intersection(other_mapped_roles):
                        continue

                    thread = after.guild.get_thread(thread_id)
                    if not thread:
                        try:
                            thread = await after.guild.fetch_channel(thread_id)
                        except (discord.NotFound, discord.HTTPException):
                            continue

                    if isinstance(thread, discord.Thread):
                        try:
                            await thread.remove_user(after)
                            logger.info(f"[ThreadSync] Removed {after.display_name} from thread '{thread.name}' (role lost).")
                        except (discord.Forbidden, discord.HTTPException) as e:
                            logger.error(f"[ThreadSync] Failed to remove {after.display_name} from thread '{thread.name}': {e}")

    # -------------------------------------------------------------------------
    # REAL-TIME MENTION EVICTION LISTENER
    # -------------------------------------------------------------------------
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Evicts users added to private threads via pings if they lack required roles."""
        if message.author.bot or not message.guild or not isinstance(message.channel, discord.Thread):
            return

        thread = message.channel

        if thread.type != discord.ChannelType.private_thread:
            return

        if not message.mentions:
            return

        mappings = load_thread_mappings()
        if not mappings:
            return

        allowed_role_ids = {
            m.get("role_id")
            for m in mappings
            if isinstance(m, dict) and m.get("thread_id") == thread.id and m.get("role_id")
        }

        if not allowed_role_ids:
            return

        for mentioned_user in message.mentions:
            if mentioned_user.bot:
                continue

            user_role_ids = {r.id for r in mentioned_user.roles}

            if not user_role_ids.intersection(allowed_role_ids):
                try:
                    await thread.remove_user(mentioned_user)
                    logger.info(
                        f"[ThreadSync] Evicted pinged user {mentioned_user.display_name} "
                        f"from private thread '{thread.name}' (lacks required role)."
                    )

                    warning_msg = await thread.send(
                        f"⚠️ {mentioned_user.mention} does not have the required role for this thread "
                        f"and was automatically removed."
                    )
                    await warning_msg.delete(delay=8)

                except (discord.Forbidden, discord.HTTPException) as e:
                    logger.error(
                        f"[ThreadSync] Failed to evict pinged user {mentioned_user.display_name} "
                        f"from thread '{thread.name}': {e}"
                    )


async def setup(bot: commands.Bot):
    await bot.add_cog(ThreadSync(bot))