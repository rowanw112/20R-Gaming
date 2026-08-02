import logging
import os
import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger(__name__)

LOG_DIR = "logs"


class AdminUtils(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # Autocomplete function to list files inside the logs/ directory
    async def log_file_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        if not os.path.exists(LOG_DIR):
            return []

        files = [
            f for f in os.listdir(LOG_DIR) 
            if os.path.isfile(os.path.join(LOG_DIR, f))
        ]
        
        # Sort files so active bot.log appears first, followed by backups
        files.sort(key=lambda x: (x != "bot.log", x))

        return [
            app_commands.Choice(name=f, value=f)
            for f in files
            if current.lower() in f.lower()
        ][:25]  # Discord limits autocomplete options to 25

    # -------------------------------------------------------------------------
    # 1. BULK NICKNAME RENAMER
    # -------------------------------------------------------------------------
    @app_commands.command(
        name="updatenames",
        description="Mass update member display names by replacing or removing a target prefix/text.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(
        old_text="The existing text or prefix in nicknames you want to replace",
        new_text="The replacement text (leave empty to just remove old_text)",
    )
    async def update_names(
        self, interaction: discord.Interaction, old_text: str, new_text: str = ""
    ):
        await interaction.response.defer(ephemeral=True)

        guild = interaction.guild
        if not guild:
            await interaction.followup.send("This command can only be used in a server.")
            return

        updated_count = 0
        skipped_count = 0
        failed_count = 0

        for member in guild.members:
            if old_text in member.display_name:
                updated_nickname = member.display_name.replace(old_text, new_text).strip()
                try:
                    await member.edit(
                        nick=updated_nickname, reason=f"Bulk rename by {interaction.user}"
                    )
                    updated_count += 1
                except discord.Forbidden:
                    skipped_count += 1
                except discord.HTTPException as e:
                    logger.error(f"Failed to update nickname for {member.display_name}: {e}")
                    failed_count += 1

        await interaction.followup.send(
            f"**Bulk Rename Complete**\n"
            f"✅ Updated: `{updated_count}` members\n"
            f"⚠️ Skipped (Insufficient Permissions): `{skipped_count}` members\n"
            f"❌ Failed (HTTP Error): `{failed_count}` members"
        )

    # -------------------------------------------------------------------------
    # 2. ROLE MIGRATION TOOL
    # -------------------------------------------------------------------------
    @app_commands.command(
        name="updateroles",
        description="Migrate all members from an old role to a new role.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(
        old_role="The role currently assigned to members",
        new_role="The role to assign to members",
        remove_old="Whether to strip the old role after assigning the new one (Default: True)",
    )
    async def update_roles(
        self,
        interaction: discord.Interaction,
        old_role: discord.Role,
        new_role: discord.Role,
        remove_old: bool = True,
    ):
        await interaction.response.defer(ephemeral=True)

        target_members = old_role.members
        if not target_members:
            await interaction.followup.send(f"No members found holding the {old_role.mention} role.")
            return

        success_count = 0
        failed_count = 0

        for member in target_members:
            try:
                if new_role not in member.roles:
                    await member.add_roles(new_role, reason=f"Role migration from {old_role.name}")

                if remove_old and old_role in member.roles:
                    await member.remove_roles(old_role, reason=f"Role migration to {new_role.name}")

                success_count += 1
            except discord.Forbidden:
                failed_count += 1
            except discord.HTTPException as e:
                logger.error(f"Failed role migration for {member.display_name}: {e}")
                failed_count += 1

        await interaction.followup.send(
            f"**Role Migration Complete**\n"
            f"🔄 Migrated: `{old_role.name}` ➔ `{new_role.name}`\n"
            f"✅ Successfully Updated: `{success_count}` members\n"
            f"❌ Failed (Hierarchy/Permission Error): `{failed_count}` members"
        )

    # -------------------------------------------------------------------------
    # 3. LOG EXTRACTOR
    # -------------------------------------------------------------------------
    @app_commands.command(
        name="logs", description="Retrieve and upload a log file from the logs folder."
    )
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.autocomplete(file_name=log_file_autocomplete)
    @app_commands.describe(file_name="The log file to download (defaults to bot.log)")
    async def get_logs(self, interaction: discord.Interaction, file_name: str = "bot.log"):
        await interaction.response.defer(ephemeral=True)

        target_path = os.path.join(LOG_DIR, file_name)

        # Prevent Directory Traversal attacks (e.g. file_name = "../main.py")
        if not os.path.abspath(target_path).startswith(os.path.abspath(LOG_DIR)):
            await interaction.followup.send("❌ Invalid log file selection.")
            return

        if not os.path.exists(target_path):
            await interaction.followup.send(
                f"❌ Log file `{file_name}` not found in `{LOG_DIR}/`."
            )
            return

        try:
            log_file = discord.File(target_path, filename=file_name)
            await interaction.followup.send(
                content=f"📄 Here is the requested log file (`{file_name}`):", file=log_file
            )
            logger.info(f"Log file '{file_name}' retrieved by {interaction.user}")
        except discord.HTTPException as e:
            logger.error(f"Failed to send log file: {e}")
            await interaction.followup.send("❌ Failed to upload log file due to an HTTP error.")

    # -------------------------------------------------------------------------
    # ERROR HANDLERS
    # -------------------------------------------------------------------------
    @update_names.error
    @update_roles.error
    @get_logs.error
    async def admin_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ):
        if isinstance(error, app_commands.MissingPermissions):
            msg = "❌ You do not have permission to run this command."
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(AdminUtils(bot))