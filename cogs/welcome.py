import logging
import os
import discord
from discord.ext import commands

logger = logging.getLogger(__name__)

CONFIG = {
    # Production Server Configuration
    531243268256694313: {
        "WELCOME_CHANNEL_ID": 589941950837293070,
    },
    # Test Server Configuration
    1530922810275528774: {
        "WELCOME_CHANNEL_ID": 1533549537967214652,  # Test Join/Leave Channel
    },
}

WELCOME_IMAGE_PATH = "data/images/20r-show-channels.png"


class Welcome(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        guild_id = member.guild.id
        guild_config = CONFIG.get(guild_id)

        if not guild_config:
            logger.warning(f"Join event in unconfigured guild: {member.guild.name} ({guild_id})")
            return

        # 1. Send Welcome Instructions DM (Replaces Default Role Assignment)
        if not member.bot:
            embed = discord.Embed(
                title="Welcome to the official 20r discord!",
                description=(
                    "Please ensure that you have the **\"Show All Channels\"** option enabled.\n"
                    "This will make the Discord server easier to navigate and ensure that you don't miss "
                    "any useful channels. If you find that you prefer not to use it, you can always "
                    "disable it later.\n\n"
                    "To enable this option, follow these steps:\n\n"
                    "**1.** Click on the server name **20R Gaming** at the top of your Discord app.\n"
                    "**2.** In the drop-down menu, click on **\"Show All Channels\"**.\n"
                    "**3.** Make sure there is a checkmark next to it.\n\n"
                    "I have provided a picture below to show you what it is supposed to look like.\n\n"
                    "Thank you for your cooperation and enjoy your stay!"
                ),
                color=discord.Color.blurple(),
            )

            files = []
            if os.path.exists(WELCOME_IMAGE_PATH):
                filename = "20r-show-channels.png"
                file = discord.File(WELCOME_IMAGE_PATH, filename=filename)
                embed.set_image(url=f"attachment://{filename}")
                files.append(file)
            else:
                logger.warning(f"[Welcome] ⚠️ Image not found at path: {os.path.abspath(WELCOME_IMAGE_PATH)}")

            try:
                if files:
                    await member.send(embed=embed, files=files)
                else:
                    await member.send(embed=embed)
                logger.info(f"Successfully sent welcome instruction DM to {member.display_name}")
            except (discord.Forbidden, discord.HTTPException) as e:
                logger.warning(f"Could not send welcome DM to {member.display_name} (DMs might be closed): {e}")

        # 2. Send Public Welcome Embed Card in Channel
        channel_id = guild_config.get("WELCOME_CHANNEL_ID")
        channel = member.guild.get_channel(channel_id)

        if channel and isinstance(channel, discord.TextChannel):
            created_at_str = member.created_at.strftime("%Y/%m/%d @ %H:%M UTC")

            embed = discord.Embed(
                description=(
                    f"{member.mention} has **__joined__** the server\n\n"
                    f"**Account Created:**\n{created_at_str}"
                ),
                color=discord.Color.from_rgb(123, 0, 0),
                timestamp=member.joined_at,
            )
            embed.set_thumbnail(url=member.display_avatar.url)
            embed.set_footer(text="Joined at")

            try:
                await channel.send(content=f"{member.mention}", embed=embed)
            except discord.HTTPException as e:
                logger.error(f"Failed to send welcome message in {channel.name}: {e}")

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        guild_id = member.guild.id
        guild_config = CONFIG.get(guild_id)

        if not guild_config:
            return

        channel_id = guild_config.get("WELCOME_CHANNEL_ID")
        channel = member.guild.get_channel(channel_id)

        if channel and isinstance(channel, discord.TextChannel):
            try:
                await channel.send(f"**{member.display_name}** has left the server.")
                logger.info(f"Logged member leave for {member.display_name}")
            except discord.HTTPException as e:
                logger.error(f"Failed to send leave message in {channel.name}: {e}")


async def setup(bot: commands.Bot):
    await bot.add_cog(Welcome(bot))