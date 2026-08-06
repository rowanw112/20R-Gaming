import asyncio
import logging
import re
import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger(__name__)

COLOR_MAP = {
    "red": discord.Color.red(),
    "blue": discord.Color.blue(),
    "green": discord.Color.green(),
    "yellow": discord.Color.gold(),
    "purple": discord.Color.purple(),
    "magenta": discord.Color.magenta(),
    "orange": discord.Color.orange(),
    "teal": discord.Color.teal(),
    "dark_teal": discord.Color.dark_teal(),
    "dark_red": discord.Color.dark_red(),
    "dark_blue": discord.Color.dark_blue(),
    "dark_purple": discord.Color.dark_purple(),
    "blurple": discord.Color.blurple(),
    "grey": discord.Color.greyple(),
    "gray": discord.Color.greyple(),
}


def parse_color(color_str: str) -> discord.Color:
    """Parses a hex code or color name into a discord.Color object."""
    clean = color_str.strip().lower()

    if clean in COLOR_MAP:
        return COLOR_MAP[clean]

    hex_match = re.search(r"^#?([0-9a-fA-F]{6})$", clean)
    if hex_match:
        return discord.Color(int(hex_match.group(1), 16))

    return discord.Color.default()


class RoleCreator(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="createroles",
        description="Bulk create roles using comma-separated values or newlines.",
    )
    @app_commands.checks.has_permissions(manage_roles=True)
    @app_commands.describe(
        role_list="Separate entries with commas. Format: Role Name | #HexCode OR ColorName",
        hoist="Display role members separately in the sidebar? (Default: False)",
        mentionable="Allow anyone to @mention these roles? (Default: False)",
    )
    async def create_roles(
        self,
        interaction: discord.Interaction,
        role_list: str,
        hoist: bool = False,
        mentionable: bool = False,
    ):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild

        # Cleanly split by both commas and newlines
        raw_entries = re.split(r"[,\n]+", role_list)
        parsed_entries = [entry.strip() for entry in raw_entries if entry.strip()]

        if not parsed_entries:
            await interaction.followup.send(
                "❌ No valid role names provided.", ephemeral=True
            )
            return

        created_roles = []
        failed_roles = []

        for entry in parsed_entries:
            if "|" in entry:
                parts = entry.split("|", 1)
                name = parts[0].strip()
                color_input = parts[1].strip()
                color = parse_color(color_input)
            else:
                name = entry.strip()
                color = discord.Color.default()

            try:
                role = await guild.create_role(
                    name=name,
                    color=color,
                    hoist=hoist,
                    mentionable=mentionable,
                    permissions=discord.Permissions.none(),
                    reason=f"Bulk role creation requested by {interaction.user}",
                )
                created_roles.append(role)

                await asyncio.sleep(0.5)

            except discord.HTTPException as e:
                failed_roles.append(f"`{name}` ({e.text})")

        summary = [
            f"✅ **Successfully created {len(created_roles)} role(s):**"
        ]
        for r in created_roles:
            color_hex = str(r.color) if r.color.value != 0 else "#000000"
            summary.append(f"• {r.mention} (`{color_hex}`)")

        if failed_roles:
            summary.append(f"\n❌ **Failed ({len(failed_roles)}):**")
            for err in failed_roles:
                summary.append(f"• {err}")

        await interaction.followup.send("\n".join(summary), ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(RoleCreator(bot))