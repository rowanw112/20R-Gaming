import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone
import discord
from discord import app_commands
from discord.ext import commands, tasks

from core.database import load_thread_mappings

logger = logging.getLogger(__name__)


def get_config_path(guild_id: int) -> str:
    path = f"data/{guild_id}"
    os.makedirs(path, exist_ok=True)
    return f"{path}/thread_keeper_config.json"


def load_config(guild_id: int) -> dict:
    filepath = get_config_path(guild_id)
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_config(guild_id: int, data: dict):
    filepath = get_config_path(guild_id)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)


# -------------------------------------------------------------------------
# PERSISTENT PROMPT VIEW FOR THREADS
# -------------------------------------------------------------------------
class ThreadKeepAlivePromptView(discord.ui.View):
    def __init__(self):
        # timeout=None ensures the buttons never expire
        super().__init__(timeout=None)

    def _can_interact(self, interaction: discord.Interaction) -> bool:
        """Restricts button clicks to Staff or the Thread Creator."""
        if interaction.user.guild_permissions.administrator:
            return True
        if interaction.user.guild_permissions.manage_threads:
            return True
        if isinstance(interaction.channel, discord.Thread) and interaction.user.id == interaction.channel.owner_id:
            return True
        return False

    def build_embed(self, is_kept_alive: bool) -> discord.Embed:
        embed = discord.Embed(
            title="📌 Thread Visibility Settings",
            description=(
                "Would you like the bot to keep this thread permanently active?\n"
                "• **Keep Thread Alive:** Automatically unarchives and bumps this thread so it never hides.\n"
                "• **Leave as Default:** Standard Discord behavior (archives on inactivity)."
            ),
            color=discord.Color.green() if is_kept_alive else discord.Color.light_grey()
        )
        status = "🟢 **Keep Alive (Auto-Bumped)**" if is_kept_alive else "🔴 **Default (Archives Normally)**"
        embed.add_field(name="Current Status", value=status, inline=False)
        embed.set_footer(text="Only staff or the thread creator can change this setting.")
        return embed

    @discord.ui.button(
        label="Keep Thread Alive",
        style=discord.ButtonStyle.success,
        custom_id="tk_keep_alive"
    )
    async def keep_alive(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._can_interact(interaction):
            await interaction.response.send_message(
                "❌ Only the thread creator or staff members can change this status.", ephemeral=True
            )
            return

        thread = interaction.channel
        if not isinstance(thread, discord.Thread):
            return

        guild = interaction.guild
        cfg = load_config(guild.id)
        
        keep_alive_ids = set(cfg.get("keep_alive_thread_ids", []))
        keep_alive_ids.add(thread.id)
        cfg["keep_alive_thread_ids"] = list(keep_alive_ids)
        save_config(guild.id, cfg)

        # Enforce max visibility (1 week)
        try:
            if thread.auto_archive_duration != 10080:
                await thread.edit(auto_archive_duration=10080, reason="ThreadKeeper: Opted into Keep-Alive")
        except (discord.Forbidden, discord.HTTPException):
            pass

        await interaction.response.edit_message(embed=self.build_embed(True), view=self)

    @discord.ui.button(
        label="Leave as Default",
        style=discord.ButtonStyle.secondary,
        custom_id="tk_leave_default"
    )
    async def leave_default(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._can_interact(interaction):
            await interaction.response.send_message(
                "❌ Only the thread creator or staff members can change this status.", ephemeral=True
            )
            return

        thread = interaction.channel
        if not isinstance(thread, discord.Thread):
            return

        guild = interaction.guild
        cfg = load_config(guild.id)
        
        keep_alive_ids = set(cfg.get("keep_alive_thread_ids", []))
        if thread.id in keep_alive_ids:
            keep_alive_ids.remove(thread.id)
            cfg["keep_alive_thread_ids"] = list(keep_alive_ids)
            save_config(guild.id, cfg)

        await interaction.response.edit_message(embed=self.build_embed(False), view=self)


# -------------------------------------------------------------------------
# THREAD KEEPER COG
# -------------------------------------------------------------------------
class ThreadKeeper(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.sweep_tracked_threads.start()
        self.bump_inactive_threads.start()

    async def cog_load(self):
        # Register the persistent view so buttons work across bot restarts
        self.bot.add_view(ThreadKeepAlivePromptView())

    def cog_unload(self):
        self.sweep_tracked_threads.cancel()
        self.bump_inactive_threads.cancel()

    def get_tracked_thread_ids(self, guild: discord.Guild) -> set[int]:
        """Returns the union of role-mapped threads and manually opted-in keep-alive threads."""
        mappings = load_thread_mappings(guild.id)
        role_mapped_ids = {
            m.get("thread_id")
            for m in mappings
            if isinstance(m, dict) and m.get("thread_id")
        }

        cfg = load_config(guild.id)
        manual_ids = set(cfg.get("keep_alive_thread_ids", []))

        return role_mapped_ids.union(manual_ids)

    def is_exempt(self, thread: discord.Thread) -> bool:
        """Returns True if thread is explicitly locked or tagged with 'archive'."""
        if thread.locked or "archive" in thread.name.lower():
            return True
        return False

    # -------------------------------------------------------------------------
    # 1. NEW THREAD LISTENER (INTERACTIVE PROMPT)
    # -------------------------------------------------------------------------
    @commands.Cog.listener()
    async def on_thread_create(self, thread: discord.Thread):
        """Fires when a thread is created; posts the pinned keep-alive status panel."""
        if getattr(self.bot, "is_passive", False): return # 🛑 Passive Mode Check
        await asyncio.sleep(1.5)

        guild = thread.guild
        if not guild:
            return

        # 1. If created by the bot or already mapped to a role, skip prompt (handled automatically)
        if thread.owner_id == self.bot.user.id:
            return

        tracked_ids = self.get_tracked_thread_ids(guild)
        if thread.id in tracked_ids:
            return

        # 2. Post the interactive control panel and pin it
        view = ThreadKeepAlivePromptView()
        embed = view.build_embed(is_kept_alive=False)

        try:
            msg = await thread.send(content=f"<@{thread.owner_id}>", embed=embed, view=view)
            await msg.pin(reason="ThreadKeeper Status Panel")
            
            # Instantly delete the system message "Bot pinned a message" to keep chat clean
            await asyncio.sleep(0.5)
            async for sys_msg in thread.history(limit=5):
                if sys_msg.type == discord.MessageType.pins_add and sys_msg.author == self.bot.user:
                    await sys_msg.delete()
                    break
                    
        except (discord.Forbidden, discord.HTTPException):
            pass

    # -------------------------------------------------------------------------
    # 2. REAL-TIME UNARCHIVE EVENT LISTENER
    # -------------------------------------------------------------------------
    @commands.Cog.listener()
    async def on_thread_update(self, before: discord.Thread, after: discord.Thread):
        """Immediately unarchives tracked threads if they become archived."""
        if getattr(self.bot, "is_passive", False): return # 🛑 Passive Mode Check
        if not before.archived and after.archived:
            guild = after.guild
            if not guild:
                return

            tracked_ids = self.get_tracked_thread_ids(guild)
            if after.id not in tracked_ids:
                return  # Leave untracked threads archived

            if self.is_exempt(after):
                return

            try:
                await after.edit(archived=False, reason="ThreadKeeper: Auto-keep alive tracked thread")
                logger.info(f"🔓 Instantly unarchived tracked thread: #{after.name} ({after.id}) in '{guild.name}'")
            except (discord.NotFound, discord.Forbidden, discord.HTTPException) as e:
                logger.warning(f"Could not auto-unarchive tracked thread #{after.name}: {e}")

    # -------------------------------------------------------------------------
    # 3. PERIODIC TRACKED-THREAD SWEEP (Runs Hourly)
    # -------------------------------------------------------------------------
    @tasks.loop(hours=1)
    async def sweep_tracked_threads(self):
        """Checks ONLY tracked keep-alive threads to ensure none were missed."""
        if getattr(self.bot, "is_passive", False): return # 🛑 Passive Mode Check
        for guild in self.bot.guilds:
            tracked_ids = self.get_tracked_thread_ids(guild)
            if not tracked_ids:
                continue

            for thread_id in list(tracked_ids):
                thread = guild.get_thread(thread_id)
                if not thread:
                    try:
                        thread = await guild.fetch_channel(thread_id)
                    except (discord.NotFound, discord.HTTPException, discord.ClientException):
                        continue

                if not isinstance(thread, discord.Thread) or self.is_exempt(thread):
                    continue

                if thread.archived:
                    try:
                        await thread.edit(archived=False, reason="ThreadKeeper: Hourly sweep auto-unarchive")
                        logger.info(f"🔓 [Sweep] Unarchived tracked thread '{thread.name}' in {guild.name}")
                        await asyncio.sleep(1.0)
                    except (discord.Forbidden, discord.HTTPException):
                        pass

    @sweep_tracked_threads.before_loop
    async def before_sweep(self):
        await self.bot.wait_until_ready()
        await asyncio.sleep(300)  # Wait 5 minutes after startup before running first sweep

    # -------------------------------------------------------------------------
    # 4. VISUAL BUMP LOOP (Runs every 12 hours)
    # -------------------------------------------------------------------------
    @tasks.loop(hours=12)
    async def bump_inactive_threads(self):
        """Maintains UI visibility by bumping tracked threads before the 1-week timeout."""
        if getattr(self.bot, "is_passive", False): return # 🛑 Passive Mode Check
        now = discord.utils.utcnow()
        bump_threshold = now - timedelta(days=6, hours=12)

        for guild in self.bot.guilds:
            tracked_ids = self.get_tracked_thread_ids(guild)
            if not tracked_ids:
                continue

            cfg = load_config(guild.id)
            if "global_last_bumps" not in cfg:
                cfg["global_last_bumps"] = {}

            bumps_made = False

            for thread_id in list(tracked_ids):
                thread = guild.get_thread(thread_id)
                if not thread:
                    try:
                        thread = await guild.fetch_channel(thread_id)
                    except (discord.NotFound, discord.HTTPException, discord.ClientException):
                        continue

                if not isinstance(thread, discord.Thread) or self.is_exempt(thread):
                    continue

                # 1. Enforce 1-Week hide timer
                if thread.auto_archive_duration != 10080:
                    try:
                        await thread.edit(auto_archive_duration=10080, reason="ThreadKeeper: Enforce 1-week visibility")
                    except (discord.Forbidden, discord.HTTPException):
                        pass

                # 2. Check if a bump is needed
                last_msg_time = None
                if thread.last_message_id:
                    last_msg_time = discord.utils.snowflake_time(thread.last_message_id)

                last_bump_timestamp = cfg["global_last_bumps"].get(str(thread.id))
                last_bump_time = datetime.fromtimestamp(last_bump_timestamp, timezone.utc) if last_bump_timestamp else None

                needs_bump_msg = not last_msg_time or last_msg_time < bump_threshold
                needs_bump_rec = not last_bump_time or last_bump_time < bump_threshold

                if needs_bump_msg and needs_bump_rec:
                    try:
                        msg = await thread.send("♻️ *Automated visibility bump...*", silent=True)
                        await msg.delete()

                        cfg["global_last_bumps"][str(thread.id)] = now.timestamp()
                        bumps_made = True
                        logger.info(f"♻️ Bumped tracked thread '{thread.name}' in {guild.name}")
                        await asyncio.sleep(1.5)
                    except (discord.Forbidden, discord.HTTPException, discord.NotFound):
                        pass

            if bumps_made:
                save_config(guild.id, cfg)

    @bump_inactive_threads.before_loop
    async def before_bump(self):
        await self.bot.wait_until_ready()

    # -------------------------------------------------------------------------
    # 5. MANAGEMENT COMMANDS
    # -------------------------------------------------------------------------
    @app_commands.command(
        name="test_thread_bump",
        description="Force a silent visibility bump and enforce 1-week inactivity on a thread."
    )
    @app_commands.checks.has_permissions(manage_threads=True)
    async def test_thread_bump(self, interaction: discord.Interaction, target_thread: discord.Thread = None):
        await interaction.response.defer(ephemeral=True)
        thread = target_thread or interaction.channel

        if not isinstance(thread, discord.Thread):
            await interaction.followup.send("❌ Target must be a thread.", ephemeral=True)
            return

        try:
            if thread.auto_archive_duration != 10080:
                await thread.edit(auto_archive_duration=10080, reason="ThreadKeeper: Test bump")

            msg = await thread.send("♻️ *Automated visibility bump test...*", silent=True)
            await msg.delete()

            await interaction.followup.send(f"✅ Bumped {thread.mention} and enforced 1-week visibility.", ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send("❌ Missing permissions in that thread.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Error bumping thread: {e}", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(ThreadKeeper(bot))