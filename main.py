import sys
from pathlib import Path

# Add project root directory to sys.path
ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import asyncio
import os
import discord
from discord.ext import commands
import config

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
        cogs_dir = ROOT_DIR / "cogs"
        if cogs_dir.exists():
            for file in cogs_dir.glob("*.py"):
                if not file.name.startswith("__"):
                    cog_name = file.stem
                    await self.load_extension(f"cogs.{cog_name}")
                    print(f"Loaded Cog: {cog_name}")

        if config.GUILD_IDS:
            for guild_id in config.GUILD_IDS:
                guild = discord.Object(id=guild_id)
                self.tree.copy_global_to(guild=guild)
                await self.tree.sync(guild=guild)
                print(f"Synced slash commands to Guild ID: {guild_id}")
        else:
            await self.tree.sync()
            print("Synced slash commands globally across all guilds.")

    async def on_ready(self):
        print("--------------------------------------------------")
        print(f"Logged in as: {self.user.name} (ID: {self.user.id})")
        print("Bot is ready and operational!")
        print("--------------------------------------------------")

async def main():
    if not config.TOKEN:
        raise ValueError("DISCORD_TOKEN is missing from your .env file!")
    
    bot = CommunityBot()
    async with bot:
        await bot.start(config.TOKEN)

if __name__ == "__main__":
    asyncio.run(main())