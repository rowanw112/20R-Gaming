import asyncio
import logging
import os
import discord
from discord import app_commands
from discord.ext import commands
import subprocess
import sys

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


    @app_commands.command(
        name="update_bot",
        description="Pulls the latest code from GitHub and restarts the bot."
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def update_bot(self, interaction: discord.Interaction):
        await interaction.response.send_message("⏳ Pulling latest code and rebooting...", ephemeral=True)
        
        try:
            # Run git pull
            subprocess.run(["git", "pull"], check=True, capture_output=True, text=True)
            
            # Exit the script. Docker will automatically restart it.
            logger.info("Bot is shutting down for a Docker restart/update.")
            sys.exit(0)
            
        except subprocess.CalledProcessError as e:
            await interaction.edit_original_response(content=f"❌ **Git Pull Failed:**\n```\n{e.stderr}\n```")
    
    # -------------------------------------------------------------------------
    # 1. BULK NICKNAME RENAMER
    # -------------------------------------------------------------------------
    @app_commands.command(
        name="update_names",
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
                
                # Pause every 10 updates to prevent hitting Discord's rate limits
                if updated_count % 10 == 0:
                    await asyncio.sleep(1.5)
                    

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
        name="update_roles",
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
                
            # Pause every 10 updates to prevent hitting Discord's rate limits
            if success_count % 10 == 0:
                await asyncio.sleep(1.5)

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
    # 4. MESSAGE PURGE / CLEAR TOOL
    # -------------------------------------------------------------------------
    @app_commands.command(
        name="clear",
        description="Delete the last X messages in the current text channel or thread.",
    )
    @app_commands.checks.has_permissions(manage_messages=True)
    @app_commands.describe(
        amount="Number of messages to delete (1-100)",
        user="Optional: Delete messages from a specific user only",
        ignore_pinned="Optional: Keep pinned messages (Default: True)",
    )
    async def clear_messages(
        self,
        interaction: discord.Interaction,
        amount: app_commands.Range[int, 1, 100],
        user: discord.Member | None = None,
        ignore_pinned: bool = True,
    ):
        await interaction.response.defer(ephemeral=True)

        channel = interaction.channel
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            await interaction.followup.send(
                "❌ Messages can only be cleared in text channels or threads.",
                ephemeral=True,
            )
            return

        def check(message: discord.Message) -> bool:
            if ignore_pinned and message.pinned:
                return False
            if user and message.author.id != user.id:
                return False
            return True

        try:
            deleted = await channel.purge(limit=amount, check=check)
            
            user_filter_str = f" from {user.mention}" if user else ""
            pinned_filter_str = " (skipping pinned)" if ignore_pinned else ""

            await interaction.followup.send(
                f"🧹 Successfully cleared `{len(deleted)}` message(s){user_filter_str}{pinned_filter_str}.",
                ephemeral=True,
            )
            logger.info(
                f"[AdminUtils] {interaction.user} cleared {len(deleted)} messages in #{channel.name}"
            )

        except discord.Forbidden:
            await interaction.followup.send(
                "❌ I lack the `Manage Messages` permission to delete messages here.",
                ephemeral=True,
            )
        except discord.HTTPException as e:
            logger.error(f"Failed to clear messages in #{channel.name}: {e}")
            await interaction.followup.send(
                "❌ Failed to delete messages (Note: Messages older than 14 days cannot be bulk deleted by Discord).",
                ephemeral=True,
            )

    # -------------------------------------------------------------------------
    # 5. MENTION PERMISSION LOCKDOWN TOOL
    # -------------------------------------------------------------------------
    @app_commands.command(
        name="restrict_mentions",
        description="Lock down role settings to prevent roles from being mentioned or pinging @everyone.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(
        disable_mentionable="Set roles to NOT be mentionable (@Role) by anyone (Default: True)",
        disable_mention_everyone="Strip the 'Mention @everyone, @here, and All Roles' permission from roles (Default: True)",
        exclude_staff="Keep staff roles unaffected (Default: True)",
    )
    async def restrict_mentions(
        self,
        interaction: discord.Interaction,
        disable_mentionable: bool = True,
        disable_mention_everyone: bool = True,
        exclude_staff: bool = True,
    ):
        await interaction.response.defer(ephemeral=True)

        guild = interaction.guild
        if not guild:
            await interaction.followup.send("This command can only be used in a server.", ephemeral=True)
            return

        bot_member = guild.me
        updated_count = 0
        skipped_count = 0

        for role in guild.roles:
            # Skip @everyone role (handled via channel overwrites or server defaults)
            if role.is_default():
                continue

            # Skip roles higher than or equal to the bot's highest role
            if role.position >= bot_member.top_role.position:
                skipped_count += 1
                continue

            # Skip managed integration/bot roles
            if role.is_bot_managed() or role.is_premium_subscriber():
                skipped_count += 1
                continue

            # Exclude Staff Roles if requested
            if exclude_staff and "staff" in role.name.lower():
                skipped_count += 1
                continue

            try:
                new_perms = role.permissions
                if disable_mention_everyone:
                    new_perms.update(mention_everyone=False)

                new_mentionable = role.mentionable
                if disable_mentionable:
                    new_mentionable = False

                await role.edit(
                    permissions=new_perms,
                    mentionable=new_mentionable,
                    reason=f"Mention lockdown by {interaction.user}",
                )
                updated_count += 1

            except (discord.Forbidden, discord.HTTPException) as e:
                logger.error(f"[AdminUtils] Failed to update permissions for role {role.name}: {e}")
                skipped_count += 1

        actions = []
        if disable_mentionable:
            actions.append("`Mentionable = False`")
        if disable_mention_everyone:
            actions.append("`Mention @everyone Permission = Disabled`")

        action_str = " and ".join(actions) if actions else "No changes selected"

        await interaction.followup.send(
            f"🔒 **Mention Lockdown Complete**\n"
            f"• **Applied Settings:** {action_str}\n"
            f"• **Roles Updated:** `{updated_count}`\n"
            f"• **Roles Skipped/Protected:** `{skipped_count}` *(Staff/Higher Roles)*",
            ephemeral=True,
        )

    # -------------------------------------------------------------------------
    # ERROR HANDLERS
    # -------------------------------------------------------------------------
    @update_names.error
    @update_roles.error
    @get_logs.error
    @clear_messages.error
    @restrict_mentions.error
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