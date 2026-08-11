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
        """Updates or posts the live Thread Sync Dashboard embed."""
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

        mapping_lines = []
        for m in mappings:
            r = guild.get_role(m.get("role_id"))
            t = guild.get_thread(m.get("thread_id"))
            r_str = r.mention if r else f"`Role ID: {m.get('role_id')}`"
            t_str = t.mention if t else f"`Thread ID: {m.get('thread_id')}`"
            mapping_lines.append(f"• **Role:** {r_str} ➔ **Thread:** 🔒 {t_str}")

        embed.add_field(
            name="📍 Mapped Sync Routes",
            value="\n".join(mapping_lines) if mapping_lines else "*No active thread mappings found.*",
            inline=False,
        )
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
    # REAL-TIME MENTION EVICTION LISTENER
    # -------------------------------------------------------------------------
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Evicts users added to private threads via pings if they lack required roles."""
        if message.author.bot or not message.guild or not isinstance(message.channel, discord.Thread):
            return

        thread = message.channel

        # Only audit private threads
        if thread.type != discord.ChannelType.private_thread:
            return

        # Skip if no user mentions are present
        if not message.mentions:
            return

        mappings = load_thread_mappings()
        if not mappings:
            return

        # Find all allowed role IDs mapped to this specific thread
        allowed_role_ids = {
            m.get("role_id")
            for m in mappings
            if isinstance(m, dict) and m.get("thread_id") == thread.id and m.get("role_id")
        }

        if not allowed_role_ids:
            return

        # Audit mentioned users
        for mentioned_user in message.mentions:
            if mentioned_user.bot:
                continue

            user_role_ids = {r.id for r in mentioned_user.roles}

            # If user does not hold any of the allowed roles for this thread, evict them
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