import asyncio
import logging
import re
import discord
from discord.ext import commands, tasks

from core.database import load_thread_mappings

logger = logging.getLogger(__name__)

# Pattern to match threads starting with numbers (e.g. "1234-ticket-name" or "0012 - support")
RE_TICKET_PREFIX = re.compile(r"^\d+")


class ThreadKeeper(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.sweep_archived_threads.start()

    def cog_unload(self):
        self.sweep_archived_threads.cancel()

    def is_exempt_from_unarchive(self, thread: discord.Thread) -> bool:
        """Returns True if the thread should NOT be unarchived."""
        # Respect locked threads
        if thread.locked:
            return True

        # Exclude threads if the title explicitly contains 'archive'
        if "archive" in thread.name.lower():
            return True

        return False

    async def notify_unarchive_if_needed(
        self, thread: discord.Thread, is_linked_to_role: bool
    ):
        """Sends an informational message to unarchived threads, UNLESS it's linked to a role
        or starts with a ticket ID number.
        """
        starts_with_number = bool(RE_TICKET_PREFIX.match(thread.name.strip()))

        # Suppress message if linked to a role OR if it starts with numbers (ticket format)
        if is_linked_to_role or starts_with_number:
            return

        try:
            await thread.send(
                "📌 **Thread Auto-Unarchived**\n"
                "This thread was automatically unarchived to keep it active. "
                "If you want this thread to remain archived, please rename it to include **`archive`** in the thread title."
            )
        except (discord.Forbidden, discord.HTTPException) as e:
            logger.warning(
                f"Could not send unarchive notice in {thread.name}: {e}"
            )

    async def _unarchive_guild_threads(self, guild: discord.Guild, context_reason: str):
        """Sweeps and unarchives valid inactive threads across text channels in the guild."""
        mappings = load_thread_mappings()
        mapped_role_thread_ids = {
            item.get("thread_id") for item in mappings if item.get("thread_id")
        }

        for channel in guild.text_channels:
            # Check if bot has permissions to read/manage threads in this channel
            permissions = channel.permissions_for(guild.me)
            if not permissions.read_message_history or not permissions.manage_threads:
                continue

            try:
                # 1. Private Archived Threads
                async for thread in channel.archived_threads(private=True, limit=None):
                    if self.is_exempt_from_unarchive(thread):
                        continue

                    await thread.edit(
                        archived=False, reason=f"ThreadKeeper: {context_reason}"
                    )
                    logger.info(
                        f"🔓 [{context_reason}] Unarchived private thread '{thread.name}' in #{channel.name}"
                    )

                    is_linked = thread.id in mapped_role_thread_ids
                    await self.notify_unarchive_if_needed(thread, is_linked)

                    # Rate Limit Safety
                    await asyncio.sleep(1.0)

                # 2. Public Archived Threads
                async for thread in channel.archived_threads(private=False, limit=None):
                    if self.is_exempt_from_unarchive(thread):
                        continue

                    await thread.edit(
                        archived=False, reason=f"ThreadKeeper: {context_reason}"
                    )
                    logger.info(
                        f"🔓 [{context_reason}] Unarchived public thread '{thread.name}' in #{channel.name}"
                    )

                    is_linked = thread.id in mapped_role_thread_ids
                    await self.notify_unarchive_if_needed(thread, is_linked)

                    # Rate Limit Safety
                    await asyncio.sleep(1.0)

            except (discord.Forbidden, discord.HTTPException) as e:
                logger.error(f"Error checking archived threads in #{channel.name}: {e}")

    # -------------------------------------------------------------------------
    # 1. BOT STARTUP AUDIT
    # -------------------------------------------------------------------------
    @commands.Cog.listener()
    async def on_ready(self):
        """Fires when the bot logs in and checks for inactive threads."""
        logger.info(
            "🔍 Bot online — auditing inactive/archived threads across all guilds..."
        )
        for guild in self.bot.guilds:
            await self._unarchive_guild_threads(
                guild, context_reason="Startup Audit"
            )

    # -------------------------------------------------------------------------
    # 2. REAL-TIME EVENT LISTENER
    # -------------------------------------------------------------------------
    @commands.Cog.listener()
    async def on_thread_update(self, before: discord.Thread, after: discord.Thread):
        """Triggers immediately when a thread is archived in real-time."""
        if not before.archived and after.archived:
            if self.is_exempt_from_unarchive(after):
                return

            try:
                await after.edit(
                    archived=False,
                    reason="ThreadKeeper: Real-time auto-unarchive",
                )
                logger.info(
                    f"🔓 Instantly unarchived thread: {after.name} ({after.id})"
                )

                mappings = load_thread_mappings()
                mapped_role_thread_ids = {
                    item.get("thread_id") for item in mappings if item.get("thread_id")
                }
                is_linked = after.id in mapped_role_thread_ids

                await self.notify_unarchive_if_needed(after, is_linked)

            except discord.Forbidden:
                logger.warning(
                    f"⚠️ Lacking permissions to unarchive thread {after.name}"
                )
            except discord.HTTPException as e:
                logger.error(f"Failed to unarchive thread {after.name}: {e}")

    # -------------------------------------------------------------------------
    # 3. PERIODIC CATCH-UP TASK LOOP (Runs Hourly)
    # -------------------------------------------------------------------------
    @tasks.loop(hours=1)
    async def sweep_archived_threads(self):
        """Runs hourly as a fail-safe sweep for missed events."""
        await self.bot.wait_until_ready()
        for guild in self.bot.guilds:
            await self._unarchive_guild_threads(
                guild, context_reason="Hourly Sweep"
            )

    @sweep_archived_threads.before_loop
    async def before_sweep(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(ThreadKeeper(bot))