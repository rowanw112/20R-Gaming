import logging
import subprocess
import sys
import asyncio
import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger(__name__)

class System(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # -------------------------------------------------------------------------
    # 1. UPDATE AND RESTART BOT
    # -------------------------------------------------------------------------
    @app_commands.command(
        name="update_bot",
        description="Pulls the latest code from GitHub, reports version changes, and restarts."
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def update_bot(self, interaction: discord.Interaction):
        await interaction.response.send_message("⏳ Fetching latest updates from GitHub...", ephemeral=True)
        
        try:
            # 1. Tell Git this directory is safe
            subprocess.run(["git", "config", "--global", "--add", "safe.directory", "/app"], check=True)
            
            # 2. Fetch remote data to get the latest GitHub hash without overwriting code yet
            subprocess.run(["git", "fetch"], check=True)
            
            # 3. Get BEFORE version (Local)
            before_hash = subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"], text=True
            ).strip()
            
            # 4. Execute the git pull
            pull_process = subprocess.run(["git", "pull"], check=True, capture_output=True, text=True)
            logger.info(f"[Update] Git Pull Success: {pull_process.stdout}")
            
            # 5. Get AFTER version (Local) and REMOTE version (GitHub)
            after_hash = subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"], text=True
            ).strip()
            remote_hash = subprocess.check_output(
                ["git", "rev-parse", "--short", "origin/main"], text=True
            ).strip()
            
            # 6. Determine Sync Status
            is_synced = after_hash == remote_hash
            sync_status = "✅ **In Sync**" if is_synced else "⚠️ **Out of Sync** (Merge error or uncommitted changes)"
            
            # 7. Build the Status Report Embed
            embed = discord.Embed(
                title="🔄 Bot Update & Restart Report", 
                color=discord.Color.brand_green() if is_synced else discord.Color.brand_red()
            )
            embed.add_field(name="Previous Version", value=f"`{before_hash}`", inline=True)
            embed.add_field(name="New Version", value=f"`{after_hash}`", inline=True)
            embed.add_field(name="GitHub Version", value=f"`{remote_hash}`", inline=True)
            embed.add_field(name="Sync Status", value=sync_status, inline=False)
            
            if before_hash == after_hash:
                embed.description = "No new commits found. Rebooting to refresh the system..."
            else:
                embed.description = "Update successfully pulled! Rebooting to apply changes..."
                
            # Edit the message to show the report
            await interaction.edit_original_response(content=None, embed=embed)
            
            # Wait 2 seconds to ensure Discord processes the edited message before we sever the connection
            await asyncio.sleep(2)
            
            # 8. Shutdown for Docker auto-reboot
            logger.info("[Update] Shutting down for Docker auto-reboot...")
            await self.bot.close()
            
        except subprocess.CalledProcessError as e:
            logger.error(f"[Update] Git Pull Failed: {e.stderr}")
            await interaction.edit_original_response(
                content=f"❌ **Git Process Failed:**\n```sh\n{e.stderr}\n```"
            )

    @update_bot.error
    async def update_bot_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            msg = "❌ You do not have permission to run this command."
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)

    # -------------------------------------------------------------------------
    # 2. VERSION CHECK COMMAND
    # -------------------------------------------------------------------------
    @app_commands.command(
        name="version",
        description="Check the currently running bot version and its sync status with GitHub."
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def check_version(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        try:
            # Ensure git directory is safe
            subprocess.run(["git", "config", "--global", "--add", "safe.directory", "/app"], check=True)
            
            # Fetch latest from remote to ensure we know if we are behind
            subprocess.run(["git", "fetch"], check=True)
            
            # Get Hashes
            local_hash = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
            remote_hash = subprocess.check_output(["git", "rev-parse", "--short", "origin/main"], text=True).strip()
            
            # Get latest commit details
            commit_msg = subprocess.check_output(["git", "log", "-1", "--pretty=%s"], text=True).strip()
            commit_time = subprocess.check_output(["git", "log", "-1", "--pretty=%cd", "--date=relative"], text=True).strip()

            is_synced = local_hash == remote_hash
            sync_status = "✅ **In Sync**" if is_synced else "⚠️ **Out of Sync** (Run `/update_bot` to sync)"

            embed = discord.Embed(
                title="🤖 Bot Version & Revision", 
                color=discord.Color.green() if is_synced else discord.Color.orange()
            )
            embed.add_field(name="Current Version", value=f"`{local_hash}`", inline=True)
            embed.add_field(name="GitHub Version", value=f"`{remote_hash}`", inline=True)
            embed.add_field(name="Sync Status", value=sync_status, inline=False)
            embed.add_field(name="Latest Commit", value=f"`{commit_msg}`\n*{commit_time}*", inline=False)
            
            await interaction.followup.send(embed=embed)
            
        except subprocess.CalledProcessError as e:
            logger.error(f"[Version] Failed to read git history: {e}")
            await interaction.followup.send(
                "❌ **Failed to retrieve version information.**", 
                ephemeral=True
            )

async def setup(bot: commands.Bot):
    await bot.add_cog(System(bot))