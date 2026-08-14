import logging
import subprocess
import sys
import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger(__name__)

class System(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="update_bot",
        description="Pulls the latest code from GitHub and restarts the bot."
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def update_bot(self, interaction: discord.Interaction):
        await interaction.response.send_message("⏳ Pulling latest code and rebooting...", ephemeral=True)
        
        try:
            # Tell Git this directory is safe
            subprocess.run(["git", "config", "--global", "--add", "safe.directory", "/app"], check=True)
            
            # Run git pull
            pull_process = subprocess.run(["git", "pull"], check=True, capture_output=True, text=True)
            logger.info(f"[Update] Git Pull Success: {pull_process.stdout}")
            
            # Shutdown for Docker auto-reboot
            logger.info("[Update] Shutting down for Docker auto-reboot...")
            sys.exit(0)
            
        except subprocess.CalledProcessError as e:
            logger.error(f"[Update] Git Pull Failed: {e.stderr}")
            await interaction.original_response(
                content=f"❌ **Git Pull Failed:**\n```sh\n{e.stderr}\n```"
            )

    @update_bot.error
    async def update_bot_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            msg = "❌ You do not have permission to run this command."
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)

# THIS IS THE CRITICAL FUNCTION DISCORD.PY LOOKS FOR:
async def setup(bot: commands.Bot):
    await bot.add_cog(System(bot))