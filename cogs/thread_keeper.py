import asyncio
import json
import logging
import os
import re
from datetime import timedelta
import discord
from discord import app_commands
from discord.ext import commands, tasks
from datetime import datetime, timezone

from core.database import load_thread_mappings

logger = logging.getLogger(__name__)

CONFIG_FILE = "data/thread_keeper_config.json"

# Pattern to match threads starting with numbers (e.g. "1234-ticket-name" or "0012 - support")
RE_TICKET_PREFIX = re.compile(r"^\d+")


def load_config() -> dict:
    if not os.path.exists(CONFIG_FILE):
        return {}
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}


def save_config(data: dict):
    if "/" in CONFIG_FILE:
        os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)


class ThreadKeeper(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.sweep_archived_threads.start()
        self.bump_inactive_threads.start()

    def cog_unload(self):
        self.sweep_archived_threads.cancel()
        self.bump_inactive_threads.cancel()

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
        except discord.NotFound:
            pass  # Thread or channel was deleted mid-operation
        except (discord.Forbidden, discord.HTTPException) as e:
            logger.warning(
                f"Could not send unarchive notice in {thread.name}: {e}"
            )

    async def _unarchive_guild_threads(self, guild: discord.Guild, context_reason: str):
        """Sweeps and unarchives valid inactive threads across text channels in the guild."""
        mappings = load_thread_mappings()
        
        # Safe extraction ensuring item is a dictionary before calling .get()
        mapped_role_thread_ids = {
            item.get("thread_id")
            for item in mappings
            if isinstance(item, dict) and item.get("thread_id")
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

            except discord.NotFound:
                # Channel or thread was deleted during teardown/sweep; ignore cleanly
                pass
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
                    item.get("thread_id")
                    for item in mappings
                    if isinstance(item, dict) and item.get("thread_id")
                }
                is_linked = after.id in mapped_role_thread_ids

                await self.notify_unarchive_if_needed(after, is_linked)

            except discord.NotFound:
                pass  # Thread was deleted
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

    # -------------------------------------------------------------------------
    # 4. VISUAL BUMP TASK LOOP (Runs every 12 hours)
    # -------------------------------------------------------------------------
    @tasks.loop(hours=12)
    async def bump_inactive_threads(self):
        """Sends and instantly deletes a silent message to physically bump UI visibility for mapped threads."""
        await self.bot.wait_until_ready()
        
        now = discord.utils.utcnow()
        bump_threshold = now - timedelta(hours=24) # Thread is considered visually inactive after 24 hours

        mappings = load_thread_mappings()
        mapped_role_thread_ids = {
            item.get("thread_id")
            for item in mappings
            if isinstance(item, dict) and item.get("thread_id")
        }

        # Load persistent bump ledger
        configs = load_config()
        if "global_last_bumps" not in configs:
            configs["global_last_bumps"] = {}
            
        bumps_made = False

        for thread_id in mapped_role_thread_ids:
            # Safely fetch the thread globally across the bot's cache
            thread = self.bot.get_channel(thread_id)
            
            if not isinstance(thread, discord.Thread):
                continue
                
            # Skip locked or specifically exempt threads
            if self.is_exempt_from_unarchive(thread):
                continue
            
            # Check last actual Discord message time
            last_msg_time = None
            if thread.last_message_id:
                last_msg_time = discord.utils.snowflake_time(thread.last_message_id)
                
            # Check our internal bump ledger
            last_bump_timestamp = configs["global_last_bumps"].get(str(thread.id))
            last_bump_time = datetime.fromtimestamp(last_bump_timestamp, timezone.utc) if last_bump_timestamp else None
            
            # We only bump if BOTH the last real message AND the last internal bump were > 24 hours ago
            needs_bump_for_msg = not last_msg_time or last_msg_time < bump_threshold
            needs_bump_for_record = not last_bump_time or last_bump_time < bump_threshold
            
            if needs_bump_for_msg and needs_bump_for_record:
                try:
                    # Send a silent message so it doesn't trigger push notifications, then delete it
                    msg = await thread.send("♻️ *Automated visibility bump...*", silent=True)
                    await msg.delete()
                    
                    # Log the bump in our persistent tracker
                    configs["global_last_bumps"][str(thread.id)] = now.timestamp()
                    bumps_made = True
                    
                    logger.info(f"♻️ Bumped inactive mapped thread to maintain UI visibility: {thread.name}")
                    await asyncio.sleep(1.5) # Rate limit safety
                except (discord.Forbidden, discord.HTTPException, discord.NotFound):
                    pass

        # Save config only if we actually performed bumps
        if bumps_made:
            save_config(configs)

    @bump_inactive_threads.before_loop
    async def before_bump(self):
        await self.bot.wait_until_ready()

    # -------------------------------------------------------------------------
    # 5. TESTING COMMAND
    # -------------------------------------------------------------------------
    @app_commands.command(
        name="test_thread_bump",
        description="Force a silent visibility bump in a specific thread to test Discord UI behavior."
    )
    @app_commands.checks.has_permissions(manage_threads=True)
    async def test_thread_bump(self, interaction: discord.Interaction, target_thread: discord.Thread):
        await interaction.response.defer(ephemeral=True)
        
        if self.is_exempt_from_unarchive(target_thread):
            await interaction.followup.send("⚠️ This thread is marked as exempt (locked or archived).", ephemeral=True)
            return

        try:
            msg = await target_thread.send("♻️ *Automated visibility bump test...*", silent=True)
            await msg.delete()
            await interaction.followup.send(
                f"✅ **Bump Sent!** Check your sidebar to see if {target_thread.mention} moved or became visible.", 
                ephemeral=True
            )
        except discord.Forbidden:
            await interaction.followup.send("❌ Missing permissions to send messages in that thread.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Error bumping thread: {e}", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(ThreadKeeper(bot))