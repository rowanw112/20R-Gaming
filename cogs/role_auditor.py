import csv
import io
import discord
from discord import app_commands
from discord.ext import commands

class RoleAuditor(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="export_roster",
        description="Generates a full CSV backup of every server member and their assigned roles."
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def export_roster(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild

        # Create an in-memory string buffer for the CSV data
        buffer = io.StringIO()
        
        # Write the UTF-8 BOM (Byte Order Mark) so Excel reads special characters/emojis correctly!
        buffer.write('\ufeff')
        
        writer = csv.writer(buffer)

        # Write the header row
        writer.writerow([
            "User ID", 
            "Username", 
            "Display Name", 
            "Joined Server", 
            "Top Role", 
            "All Assigned Roles"
        ])

        # Iterate through all members and compile their data
        for member in guild.members:
            # We filter out the default @everyone role to keep the data clean
            role_names = [r.name for r in member.roles if r.name != "@everyone"]
            roles_str = " | ".join(role_names)
            
            joined_date = member.joined_at.strftime("%Y-%m-%d %H:%M:%S") if member.joined_at else "Unknown"

            writer.writerow([
                str(member.id),
                str(member.name),
                str(member.display_name),
                joined_date,
                str(member.top_role.name),
                roles_str
            ])

        # Reset the buffer's position to the beginning so Discord can read it
        buffer.seek(0)
        
        # Package the buffer into a Discord file attachment
        file = discord.File(fp=buffer, filename=f"{guild.name.replace(' ', '_')}_Roster_Backup.csv")

        await interaction.followup.send(
            f"✅ **Roster Export Complete!**\nCompiled data for **{len(guild.members)}** members. You can open this file in Excel or Google Sheets.",
            file=file,
            ephemeral=True
        )

async def setup(bot: commands.Bot):
    await bot.add_cog(RoleAuditor(bot))