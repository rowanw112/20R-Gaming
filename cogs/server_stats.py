import asyncio
import logging
import unicodedata
import discord
from discord import app_commands
from discord.ext import commands, tasks

logger = logging.getLogger(__name__)


class ServerStats(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.update_stats_loop.start()

    def cog_unload(self):
        self.update_stats_loop.cancel()

    async def _update_guild_stats(self, guild: discord.Guild):
        """Calculates current metrics and updates channel names if they've changed."""
        category = discord.utils.get(guild.categories, name="─── 📊 𝐒𝐄𝐑𝐕𝐄𝐑 𝐒𝐓𝐀𝐓𝐒 📊 ───")
        if not category:
            return

        # Calculate metrics
        human_count = sum(1 for m in guild.members if not m.bot)
        voice_count = sum(len(vc.members) for vc in guild.voice_channels)

        # Expected stats formatting
        expected_names = {
            "website": "🌐 𝟐𝟎𝐑.𝐠𝐠",
            "invite": "🔗 𝐝𝐢𝐬𝐜𝐨𝐫𝐝.𝐠𝐠/𝟐𝟎𝐫",
            "voice": f"🔊 𝐕𝐨𝐢𝐜𝐞 𝐂𝐨𝐧𝐧𝐞𝐜𝐭𝐢𝐨𝐧: {voice_count}",
            "members": f"👥 𝐌𝐞𝐦𝐛𝐞𝐫𝐬: {human_count}",
        }

        # Match and update channels safely using NFKD normalization
        for channel in category.voice_channels:
            norm_name = unicodedata.normalize("NFKD", channel.name).lower()

            target_name = None
            # Evaluate discord.gg FIRST to prevent "20r" from matching the invite link
            if "discord.gg" in norm_name or "invite" in norm_name:
                target_name = expected_names["invite"]
            elif "20r" in norm_name or "website" in norm_name:
                target_name = expected_names["website"]
            elif "voice" in norm_name or "connection" in norm_name:
                target_name = expected_names["voice"]
            elif "member" in norm_name:
                target_name = expected_names["members"]

            if target_name and channel.name != target_name:
                try:
                    await channel.edit(
                        name=target_name, reason="Server Stats Auto-Update"
                    )
                    await asyncio.sleep(1.0)
                except (discord.Forbidden, discord.HTTPException) as e:
                    logger.warning(
                        f"Could not update channel {channel.name}: {e}"
                    )

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
        description="Creates the Server Stats category & locked stat voice channels.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_server_stats(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild

        # 1. Check if category already exists
        category = discord.utils.get(guild.categories, name="📊 SERVER STATS")
        if not category:
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
                name="📊 SERVER STATS",
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

        stat_targets = [
            ("website", "🌐 𝟐𝟎𝐑.𝐠𝐠", "website"),
            ("invite", "🔗 𝐝𝐢𝐬𝐜𝐨𝐫𝐝.𝐠𝐠/𝟐𝟎𝐫", "discord.gg"),
            ("voice", f"🔊 𝐕𝐨𝐢𝐜𝐞 𝐂𝐨𝐧𝐧𝐞𝐜𝐭𝐢𝐨𝐧: {voice_count}", ["voice", "connection"]),
            ("members", f"👥 𝐌𝐞𝐦𝐛𝐞𝐫𝐬: {human_count}", "member"),
        ]

        created_list = []
        for key, target_name, match_keywords in stat_targets:
            existing = None
            for ch in category.voice_channels:
                norm = unicodedata.normalize("NFKD", ch.name).lower()
                if isinstance(match_keywords, list):
                    if any(kw in norm for kw in match_keywords):
                        existing = ch
                        break
                elif match_keywords in norm:
                    existing = ch
                    break

            if not existing:
                ch = await guild.create_voice_channel(
                    name=target_name,
                    category=category,
                    reason="Server Stats Setup",
                )
                created_list.append(ch.name)
            else:
                if existing.name != target_name:
                    await existing.edit(name=target_name)
                created_list.append(f"{target_name} (Updated Existing)")

        await interaction.followup.send(
            f"✅ **Server Stats Setup Complete!**\nCategory active at top of server with channels:\n"
            + "\n".join(f"• `{name}`" for name in created_list),
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(ServerStats(bot))