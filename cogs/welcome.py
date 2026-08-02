import logging
import discord
from discord.ext import commands

logger = logging.getLogger(__name__)

CONFIG = {
    # Production Server Configuration
    531243268256694313: {
        "WELCOME_CHANNEL_ID": 589941950837293070,
        "DEFAULT_ROLES": [
            588931614017323058,  # Production Stranger Role
        ],
    },
    # Test Server Configuration
    1530922810275528774: {
        "WELCOME_CHANNEL_ID": 1533549537967214652,  # Test Join/Leave Channel
        "DEFAULT_ROLES": [
            1533544079156314313,  # Test Stranger Role
        ],
    },
}


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

        # 1. Assign Default Join Roles (Stranger Role)
        roles_to_add = []
        for role_id in guild_config.get("DEFAULT_ROLES", []):
            role = member.guild.get_role(role_id)
            if role and role not in member.roles:
                roles_to_add.append(role)

        if roles_to_add:
            try:
                await member.add_roles(*roles_to_add, reason="Auto-assigned on server join")
                logger.info(f"Assigned default join roles to {member.display_name}")
            except discord.HTTPException as e:
                logger.error(f"Failed to assign default roles to {member.display_name}: {e}")

        # 2. Send Welcome Embed Card
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