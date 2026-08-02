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
from discord.ext import commands
import config

# -----------------------------------------------------------------------------
# LOGGING SETUP
# -----------------------------------------------------------------------------
LOG_DIR = ROOT_DIR / "logs"
os.makedirs(LOG_DIR, exist_ok=True)  # Ensures the logs/ directory exists

logger = logging.getLogger()
logger.setLevel(logging.INFO)

formatter = logging.Formatter(
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
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

# 2. Console Handler printing to terminal
console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
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
        # Auto-load all cogs inside /cogs directory
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

        # Sync application slash commands
        if getattr(config, "GUILD_IDS", None):
            for guild_id in config.GUILD_IDS:
                guild = discord.Object(id=guild_id)
                self.tree.copy_global_to(guild=guild)
                await self.tree.sync(guild=guild)
                logging.info(f"Synced slash commands to Guild ID: {guild_id}")
        else:
            await self.tree.sync()
            logging.info("Synced slash commands globally across all guilds.")

    async def on_ready(self):
        logging.info("--------------------------------------------------")
        logging.info(f"Logged in as: {self.user.name} (ID: {self.user.id})")
        logging.info("Bot is ready and operational!")
        logging.info("--------------------------------------------------")


async def main():
    if not getattr(config, "TOKEN", None):
        raise ValueError("DISCORD_TOKEN is missing from your config or .env file!")
    
    bot = CommunityBot()
    async with bot:
        await bot.start(config.TOKEN)


if __name__ == "__main__":
    asyncio.run(main())