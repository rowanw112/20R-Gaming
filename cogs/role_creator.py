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
        description="Bulk create roles, optionally placing them under a specific category role.",
    )
    @app_commands.checks.has_permissions(manage_roles=True)
    @app_commands.describe(
        role_list="Comma separated. Format: Role Name | #HexCode OR ColorName",
        category_anchor="The role to place these new roles directly UNDER (Optional)",
        default_color="Hex code or color name to apply to ALL roles in this batch (Optional)",
        hoist="Display role members separately in the sidebar? (Default: False)",
        mentionable="Allow anyone to @mention these roles? (Default: False)",
    )
    async def create_roles(
        self,
        interaction: discord.Interaction,
        role_list: str,
        category_anchor: discord.Role | None = None,
        default_color: str | None = None,
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

        # Pre-parse the default color if one was provided
        base_color = parse_color(default_color) if default_color else discord.Color.default()

        created_roles = []
        failed_roles = []

        # 1. Create the roles
        for entry in parsed_entries:
            # If they used the specific inline override (e.g., Role | #FF0000)
            if "|" in entry:
                parts = entry.split("|", 1)
                name = parts[0].strip()
                color_input = parts[1].strip()
                color = parse_color(color_input)
            else:
                name = entry.strip()
                color = base_color

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

        if not created_roles:
            await interaction.followup.send(
                f"❌ Failed to create any roles.\nErrors: {', '.join(failed_roles)}", 
                ephemeral=True
            )
            return

        # 2. If an anchor is provided, bulk-move the newly created roles directly beneath it
        anchor_warning = ""
        if category_anchor:
            try:
                target_position = max(1, category_anchor.position - 1)
                
                position_updates = {
                    role: target_position for role in reversed(created_roles)
                }
                
                await guild.edit_role_positions(position_updates, reason=f"Anchoring under {category_anchor.name}")
            except discord.Forbidden:
                anchor_warning = f"\n\n⚠️ **Warning:** Created the roles, but I lack permission to drag them under **{category_anchor.name}**. (My top role must be higher than the anchor!)"
            except discord.HTTPException as e:
                logger.error(f"Failed to move roles under anchor: {e}")
                anchor_warning = "\n\n⚠️ **Warning:** Created the roles, but Discord threw an error when moving them. You may need to drag them manually."

        # 3. Success Output
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

        if category_anchor and not anchor_warning:
            summary.append(f"\n📌 *Anchored directly under {category_anchor.mention}.*")
        elif not category_anchor:
            summary.append("\n⬇️ *Placed at the bottom of the role list (No category selected).*")
            
        if anchor_warning:
            summary.append(anchor_warning)

        await interaction.followup.send("\n".join(summary), ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(RoleCreator(bot))