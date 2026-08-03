import json
import logging
import os
import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger(__name__)

DATA_FILE = os.path.join("data", "bait_stats.json")


def load_data() -> dict:
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load bait stats file: {e}")
    return {}


def save_data(data: dict):
    os.makedirs("data", exist_ok=True)
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        logger.error(f"Failed to save bait stats file: {e}")


class BotTrap(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.data = load_data()

    def build_warning_embed(self, ban_count: int) -> discord.Embed:
        embed = discord.Embed(
            title="⛔ DANGER: DO NOT POST IN THIS CHANNEL ⛔",
            description=(
                "### ⚠️ AUTOMATED BOT TRAP — EXTREME WARNING ⚠️\n\n"
                "This channel is an automated security honeypot strictly used to detect spam bots.\n\n"
                "🛑 **IF YOU SEND ANY MESSAGE HERE, YOU WILL BE INSTANTLY AND PERMANENTLY BANNED.**\n\n"
                "• **Automated Enforcement:** Banning takes place immediately upon sending a message.\n"
                "• **No Exceptions:** Applies to all Members, Recruits, and Strangers.\n"
                "• **No Appeals:** Claims of \"accidental posts\" or \"testing\" will **NOT** be appealed.\n\n"
                "🚫 **DO NOT TYPE OR SEND ANYTHING IN THIS CHANNEL!**"
            ),
            color=discord.Color.brand_red(),  # Pure High-Alert Red (#ED4245)
        )
        embed.set_footer(text=f"Total Bots Caught: {ban_count}")
        return embed

    # -------------------------------------------------------------------------
    # 1. SETUP COMMAND
    # -------------------------------------------------------------------------
    @app_commands.command(
        name="setupbait",
        description="Sets up a bot bait channel with the severe warning embed and persistent ban counter.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(
        channel="Select the channel to use as the bot trap (or leave empty to create a new one)"
    )
    async def setup_bait(
        self, interaction: discord.Interaction, channel: discord.TextChannel = None
    ):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild

        target_channel = channel
        if not target_channel:
            target_channel = await guild.create_text_channel(
                name="bot-bait",
                reason=f"Bot Trap setup requested by {interaction.user}",
            )

        guild_id_str = str(guild.id)
        current_bans = self.data.get(guild_id_str, {}).get("ban_count", 0)

        # Post the initial warning embed
        embed = self.build_warning_embed(current_bans)
        message = await target_channel.send(embed=embed)

        # Save config
        self.data[guild_id_str] = {
            "channel_id": target_channel.id,
            "message_id": message.id,
            "ban_count": current_bans,
        }
        save_data(self.data)

        await interaction.followup.send(
            f"✅ **Bot Trap Setup Complete!**\n"
            f"• **Channel:** {target_channel.mention}\n"
            f"• **Current Ban Counter:** `{current_bans}`"
        )

    # -------------------------------------------------------------------------
    # 2. REFRESH / UPDATE EMBED COMMAND
    # -------------------------------------------------------------------------
    @app_commands.command(
        name="updatebaitembed",
        description="Refreshes the warning embed in the configured bait channel without resetting stats.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def update_bait_embed(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        guild_id_str = str(guild.id)

        guild_data = self.data.get(guild_id_str)
        if not guild_data or "channel_id" not in guild_data:
            await interaction.followup.send(
                "❌ No bot bait channel configured for this server. Run `/setupbait` first."
            )
            return

        channel = guild.get_channel(guild_data["channel_id"])
        if not channel:
            await interaction.followup.send("❌ Configured bait channel no longer exists.")
            return

        current_bans = guild_data.get("ban_count", 0)
        new_embed = self.build_warning_embed(current_bans)

        try:
            # Try editing the existing embed message if it exists
            embed_msg = await channel.fetch_message(guild_data["message_id"])
            await embed_msg.edit(embed=new_embed)
            await interaction.followup.send("✅ **Bot Trap Embed Updated!**")
        except discord.NotFound:
            # If the old message was accidentally deleted, post a new one
            new_msg = await channel.send(embed=new_embed)
            guild_data["message_id"] = new_msg.id
            self.data[guild_id_str] = guild_data
            save_data(self.data)
            await interaction.followup.send(
                "⚠️ Old embed message was missing. **New embed message created and saved!**"
            )
        except discord.HTTPException as e:
            logger.error(f"Failed to update bait embed: {e}")
            await interaction.followup.send(f"❌ HTTP Error updating embed: `{e}`")

    # -------------------------------------------------------------------------
    # 3. AUTO-BAN EVENT LISTENER
    # -------------------------------------------------------------------------
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # Ignore messages sent by bots or outside guilds
        if message.author.bot or not message.guild:
            return

        guild_id_str = str(message.guild.id)
        guild_data = self.data.get(guild_id_str)

        if not guild_data or message.channel.id != guild_data.get("channel_id"):
            return

        # Protection: Ignore administrators to prevent accidental self-bans
        if (
            isinstance(message.author, discord.Member)
            and message.author.guild_permissions.administrator
        ):
            return

        # Delete the trigger message immediately
        try:
            await message.delete()
        except discord.HTTPException:
            pass

        # Execute Ban
        try:
            await message.guild.ban(
                message.author,
                reason="Auto-banned by Bot Trap (posted in honeypot channel)",
                delete_message_days=1,
            )
            logger.info(
                f"🛡️ Bot Trap banned user: {message.author} ({message.author.id})"
            )
        except discord.Forbidden:
            logger.warning(f"⚠️ Bot Trap lacks permissions to ban {message.author}")
            return
        except discord.HTTPException as e:
            logger.error(f"Failed to ban user {message.author}: {e}")
            return

        # Increment ban counter & update stored state
        guild_data["ban_count"] = guild_data.get("ban_count", 0) + 1
        self.data[guild_id_str] = guild_data
        save_data(self.data)

        # Update the live warning embed footer
        try:
            channel = message.guild.get_channel(guild_data["channel_id"])
            if channel:
                embed_msg = await channel.fetch_message(guild_data["message_id"])
                if embed_msg:
                    new_embed = self.build_warning_embed(guild_data["ban_count"])
                    await embed_msg.edit(embed=new_embed)
        except Exception as e:
            logger.error(f"Failed to update bait counter embed: {e}")

    # -------------------------------------------------------------------------
    # ERROR HANDLER
    # -------------------------------------------------------------------------
    @setup_bait.error
    @update_bait_embed.error
    async def bait_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ):
        if isinstance(error, app_commands.MissingPermissions):
            msg = "❌ You do not have permission to run this command."
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(BotTrap(bot))