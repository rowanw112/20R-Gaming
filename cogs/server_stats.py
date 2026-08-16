import asyncio
import json
import logging
import os
import discord
from discord import app_commands
from discord.ext import commands, tasks

logger = logging.getLogger(__name__)


def get_config_path(guild_id: int) -> str:
    path = f"data/{guild_id}"
    os.makedirs(path, exist_ok=True)
    return f"{path}/server_stats_config.json"


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


class ServerStats(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.update_stats_loop.start()

    def cog_unload(self):
        self.update_stats_loop.cancel()

    async def _update_guild_stats(self, guild: discord.Guild):
        """Calculates current metrics and updates channel names using configured IDs."""
        cfg = load_config(guild.id)
        if not cfg:
            return

        category_id = cfg.get("category_id")
        voice_id = cfg.get("voice_id")
        members_id = cfg.get("members_id")

        if not category_id or not voice_id or not members_id:
            return

        category = guild.get_channel(category_id)
        if not category or not isinstance(category, discord.CategoryChannel):
            return

        # Calculate metrics
        human_count = sum(1 for m in guild.members if not m.bot)
        voice_count = sum(len(vc.members) for vc in guild.voice_channels)

        # Expected stats formatting
        target_voice_name = f"🔊 𝐕𝐨𝐢𝐜𝐞 𝐂𝐨𝐧𝐧𝐞𝐜𝐭𝐢𝐨𝐧: {voice_count}"
        target_members_name = f"👥 𝐌𝐞𝐦𝐛𝐞𝐫𝐬: {human_count}"

        # Update Voice Connection Channel
        voice_channel = guild.get_channel(voice_id)
        if voice_channel and isinstance(voice_channel, discord.VoiceChannel) and voice_channel.name != target_voice_name:
            try:
                await voice_channel.edit(name=target_voice_name, reason="Server Stats Auto-Update")
                await asyncio.sleep(1.0)
            except (discord.Forbidden, discord.HTTPException) as e:
                logger.warning(f"Could not update voice stat channel {voice_channel.name}: {e}")

        # Update Members Channel
        members_channel = guild.get_channel(members_id)
        if members_channel and isinstance(members_channel, discord.VoiceChannel) and members_channel.name != target_members_name:
            try:
                await members_channel.edit(name=target_members_name, reason="Server Stats Auto-Update")
                await asyncio.sleep(1.0)
            except (discord.Forbidden, discord.HTTPException) as e:
                logger.warning(f"Could not update members stat channel {members_channel.name}: {e}")

    # -------------------------------------------------------------------------
    # AUTOMATIC EVENT LISTENERS & TASK LOOPS
    # -------------------------------------------------------------------------
    @tasks.loop(minutes=10)
    async def update_stats_loop(self):
        """Periodic sweep to keep voice connections and member counts fresh."""
        await self.bot.wait_until_ready()
        for guild in self.bot.guilds:
            await self._update_guild_stats(guild)

    @update_stats_loop.before_loop
    async def before_loop(self):
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        """Instantly update member stats when someone joins."""
        await self._update_guild_stats(member.guild)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        """Instantly update member stats when someone leaves."""
        await self._update_guild_stats(member.guild)

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ):
        """Update voice connection stats when users join/leave voice channels."""
        if before.channel != after.channel:
            await self._update_guild_stats(member.guild)

    # -------------------------------------------------------------------------
    # SETUP SLASH COMMAND
    # -------------------------------------------------------------------------
    @app_commands.command(
        name="setup_server_stats",
        description="Creates the Server Stats category & locked stat voice channels and tracks their IDs.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_server_stats(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild

        category_name = "─── 📊 𝐒𝐄𝐑𝐕𝐄𝐑 𝐒𝐓𝐀𝐓𝐒 📊 ───"

        category_overwrites = {
            guild.default_role: discord.PermissionOverwrite(
                view_channel=True,
                connect=False,
            ),
            guild.me: discord.PermissionOverwrite(
                view_channel=True,
                connect=True,
                manage_channels=True,
            ),
        }
        
        category = await guild.create_category(
            name=category_name,
            overwrites=category_overwrites,
            reason="Server Stats Setup",
        )
        
        try:
            await category.edit(position=0)
        except (discord.Forbidden, discord.HTTPException):
            pass

        # Calculate initial stats
        human_count = sum(1 for m in guild.members if not m.bot)
        voice_count = sum(len(vc.members) for vc in guild.voice_channels)

        website_name = "🌐 𝟐𝟎𝐑.𝐠𝐠"
        invite_name = "🔗 𝐝𝐢𝐬𝐜𝐨𝐫𝐝.𝐠𝐠/𝟐𝟎𝐫"
        voice_name = f"🔊 𝐕𝐨𝐢𝐜𝐞 𝐂𝐨𝐧𝐧𝐞𝐜𝐭𝐢𝐨𝐧: {voice_count}"
        members_name = f"👥 𝐌𝐞𝐦𝐛𝐞𝐫𝐬: {human_count}"

        website_ch = await guild.create_voice_channel(name=website_name, category=category, reason="Server Stats Setup")
        invite_ch = await guild.create_voice_channel(name=invite_name, category=category, reason="Server Stats Setup")
        voice_ch = await guild.create_voice_channel(name=voice_name, category=category, reason="Server Stats Setup")
        members_ch = await guild.create_voice_channel(name=members_name, category=category, reason="Server Stats Setup")

        # Save exact IDs to config
        cfg = {
            "category_id": category.id,
            "website_id": website_ch.id,
            "invite_id": invite_ch.id,
            "voice_id": voice_ch.id,
            "members_id": members_ch.id
        }
        save_config(guild.id, cfg)

        await interaction.followup.send(
            f"✅ **Server Stats Setup Complete!**\nCategory active at top of server with channels:\n"
            f"• `{website_ch.name}`\n"
            f"• `{invite_ch.name}`\n"
            f"• `{voice_ch.name}`\n"
            f"• `{members_ch.name}`",
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(ServerStats(bot))