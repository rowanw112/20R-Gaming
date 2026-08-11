import sys
from pathlib import Path

# Add project root directory to sys.path
ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import asyncio
import logging
import os
from logging.handlers import RotatingFileHandler
import discord
from discord import app_commands
from discord.ext import commands
import config

# -----------------------------------------------------------------------------
# LOGGING SETUP
# -----------------------------------------------------------------------------
LOG_DIR = ROOT_DIR / "logs"
os.makedirs(LOG_DIR, exist_ok=True)  # Ensures the logs/ directory exists

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Standard formatter for log files
file_formatter = logging.Formatter(
    fmt="[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# Custom colored formatter for console output (Prints ERROR logs in bright red)
class ColoredConsoleFormatter(logging.Formatter):
    COLOR_RED = "\033[91m"
    COLOR_RESET = "\033[0m"

    def format(self, record):
        formatted_msg = super().format(record)
        if record.levelno >= logging.ERROR:
            return f"{self.COLOR_RED}{formatted_msg}{self.COLOR_RESET}"
        return formatted_msg

console_formatter = ColoredConsoleFormatter(
    fmt="[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# 1. Rotating File Handler targeting logs/bot.log (5 MB limit, 5 backups)
file_handler = RotatingFileHandler(
    filename=LOG_DIR / "bot.log",
    encoding="utf-8",
    maxBytes=5 * 1024 * 1024,
    backupCount=5,
)
file_handler.setFormatter(file_formatter)
logger.addHandler(file_handler)

# 2. Console Handler printing to terminal (With Red Error Formatting)
console_handler = logging.StreamHandler()
console_handler.setFormatter(console_formatter)
logger.addHandler(console_handler)


# -----------------------------------------------------------------------------
# COMMUNITY BOT CLASS
# -----------------------------------------------------------------------------
class CommunityBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True

        super().__init__(
            command_prefix="!",
            intents=intents,
            help_command=None
        )

    async def setup_hook(self):
        # 1. Load all cogs inside /cogs directory
        cogs_dir = ROOT_DIR / "cogs"
        if cogs_dir.exists():
            for file in cogs_dir.glob("*.py"):
                if not file.name.startswith("__"):
                    cog_name = file.stem
                    try:
                        await self.load_extension(f"cogs.{cog_name}")
                        logging.info(f"Loaded Cog: {cog_name}")
                    except Exception as e:
                        logging.error(f"Failed to load Cog {cog_name}: {e}")

        # 2. Sync application slash commands
        guild_ids = getattr(config, "GUILD_IDS", [])
        if guild_ids:
            for guild_id in guild_ids:
                guild = discord.Object(id=guild_id)
                self.tree.copy_global_to(guild=guild)  # Copies cog global commands into guild tree
                synced = await self.tree.sync(guild=guild)
                logging.info(f"Synced {len(synced)} command(s) instantly to Guild ID: {guild_id}")
        else:
            synced = await self.tree.sync()
            logging.info(f"Synced {len(synced)} command(s) globally across all guilds.")

    async def on_ready(self):
        logging.info("--------------------------------------------------")
        logging.info(f"Logged in as: {self.user.name} (ID: {self.user.id})")
        logging.info("Bot is ready and operational!")
        logging.info("--------------------------------------------------")


async def main():
    if not getattr(config, "TOKEN", None):
        raise ValueError("DISCORD_TOKEN is missing from your config or .env file!")
    
    bot = CommunityBot()

    # -------------------------------------------------------------------------
    # SLASH COMMAND MANAGEMENT
    # -------------------------------------------------------------------------
    @bot.tree.command(name="sync", description="Force sync slash commands across guilds.")
    @app_commands.checks.has_permissions(administrator=True)
    async def sync_slash(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild_ids = getattr(config, "GUILD_IDS", [])
        
        if guild_ids:
            for guild_id in guild_ids:
                guild = discord.Object(id=guild_id)
                bot.tree.copy_global_to(guild=guild)  # Copies global commands to guild tree on manual sync
                synced = await bot.tree.sync(guild=guild)
                await interaction.followup.send(
                    f"✅ Synced `{len(synced)}` slash commands to Guild `{guild_id}`!",
                    ephemeral=True,
                )
        else:
            synced = await bot.tree.sync()
            await interaction.followup.send(
                f"✅ Globally synced `{len(synced)}` slash commands!",
                ephemeral=True,
            )

    @bot.tree.command(name="reload", description="Reload all cogs on the fly without restarting.")
    @app_commands.checks.has_permissions(administrator=True)
    async def reload_slash(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        cogs_dir = ROOT_DIR / "cogs"
        reloaded = []
        failed = []

        if cogs_dir.exists():
            for file in cogs_dir.glob("*.py"):
                if not file.name.startswith("__"):
                    cog_name = file.stem
                    try:
                        await bot.reload_extension(f"cogs.{cog_name}")
                        reloaded.append(f"`{cog_name}`")
                    except commands.ExtensionNotLoaded:
                        try:
                            await bot.load_extension(f"cogs.{cog_name}")
                            reloaded.append(f"`{cog_name}` *(new)*")
                        except Exception as e:
                            logging.error(f"Failed to load Cog {cog_name}: {e}")
                            failed.append(f"`{cog_name}` ({e})")
                    except Exception as e:
                        logging.error(f"Failed to reload Cog {cog_name}: {e}")
                        failed.append(f"`{cog_name}` ({e})")

        msg = f"🔄 **Reloaded Cogs ({len(reloaded)}):** {', '.join(reloaded) if reloaded else 'None'}"
        if failed:
            msg += f"\n❌ **Failed ({len(failed)}):** {', '.join(failed)}"

        await interaction.followup.send(msg, ephemeral=True)

    async with bot:
        await bot.start(config.TOKEN)


if __name__ == "__main__":
    asyncio.run(main())