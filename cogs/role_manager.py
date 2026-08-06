import asyncio
import json
import logging
import os
import re
import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger(__name__)

DATA_FILE = "guild_categories.json"


def load_data() -> dict:
    if not os.path.exists(DATA_FILE):
        return {}
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}


def save_data(data: dict):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)


class RoleCategorySelect(discord.ui.Select):
    def __init__(
        self,
        categories: list[discord.Role],
        role_list_str: str,
        hoist: bool,
        mentionable: bool,
    ):
        self.categories = categories  # Sorted highest to lowest position
        self.role_list_str = role_list_str
        self.hoist = hoist
        self.mentionable = mentionable

        options = [
            discord.SelectOption(
                label=role.name,
                value=str(role.id),
                description=f"Category Divider (Pos: {role.position})",
            )
            for role in categories
        ]
        options.append(
            discord.SelectOption(
                label="No Category (Default creation at bottom)",
                value="none",
            )
        )

        super().__init__(
            placeholder="Select category (roles will be placed at the bottom of it)...",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild

        raw_entries = re.split(r"[,\n]+", self.role_list_str)
        parsed_entries = [e.strip() for e in raw_entries if e.strip()]

        selected_id = self.values[0]
        target_category_role = None
        next_category_role = None

        if selected_id != "none":
            for idx, r in enumerate(self.categories):
                if str(r.id) == selected_id:
                    target_category_role = r
                    if idx + 1 < len(self.categories):
                        next_category_role = self.categories[idx + 1]
                    break

        created_roles = []
        failed_roles = []

        # 1. Create all roles first
        for entry in parsed_entries:
            if "|" in entry:
                parts = entry.split("|", 1)
                name = parts[0].strip()
                color_hex = parts[1].strip().lstrip("#")
                try:
                    color = discord.Color(int(color_hex, 16))
                except ValueError:
                    color = discord.Color.default()
            else:
                name = entry.strip()
                color = discord.Color.default()

            try:
                role = await guild.create_role(
                    name=name,
                    color=color,
                    hoist=self.hoist,
                    mentionable=self.mentionable,
                    permissions=discord.Permissions.none(),
                    reason=f"Bulk creation by {interaction.user}",
                )
                created_roles.append(role)
                await asyncio.sleep(0.3)
            except discord.HTTPException as e:
                failed_roles.append(f"`{name}` ({e.text})")

        # 2. Safely reposition created roles into the target category as a single atomic batch
        if created_roles and target_category_role:
            try:
                # Fetch fresh list of all guild roles, sorted highest to lowest position
                all_roles = sorted(guild.roles, key=lambda r: r.position, reverse=True)

                # Determine pivot role index: directly above the NEXT category divider if available,
                # otherwise directly below the TARGET category divider.
                pivot_role = next_category_role if next_category_role else target_category_role
                pivot_idx = all_roles.index(pivot_role)

                # Exclude created roles from existing list to avoid duplicates
                existing_roles = [r for r in all_roles if r not in created_roles]

                # Insert created roles directly above the next divider (or below target divider)
                insert_idx = existing_roles.index(pivot_role) if next_category_role else existing_roles.index(pivot_role) + 1
                new_role_order = existing_roles[:insert_idx] + created_roles + existing_roles[insert_idx:]

                # Calculate position map (Discord API requires mapping from lowest position 1 to highest)
                position_payload = {}
                total_count = len(new_role_order)
                for idx, r in enumerate(new_role_order):
                    if not r.is_default():  # Skip @everyone
                        position_payload[r] = total_count - idx

                await guild.edit_role_positions(positions=position_payload)

            except (discord.HTTPException, ValueError) as e:
                logger.error(f"Failed to set role positions: {e}")

        # Summary output
        msg = f"✅ **Created {len(created_roles)} role(s)**"
        if target_category_role:
            msg += f" at the bottom of **{target_category_role.name}**"
        msg += ":\n" + "\n".join(f"• {r.mention}" for r in created_roles)

        if failed_roles:
            msg += "\n\n❌ **Failed:**\n" + "\n".join(failed_roles)

        await interaction.followup.send(msg, ephemeral=True)


class RoleCategoryView(discord.ui.View):
    def __init__(
        self,
        categories: list[discord.Role],
        role_list_str: str,
        hoist: bool,
        mentionable: bool,
    ):
        super().__init__(timeout=120)
        self.add_item(
            RoleCategorySelect(categories, role_list_str, hoist, mentionable)
        )


class RoleManager(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="set_category_roles",
        description="Define category dividers in order from TOP to BOTTOM.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def set_category_roles(
        self,
        interaction: discord.Interaction,
        role1: discord.Role,
        role2: discord.Role = None,
        role3: discord.Role = None,
        role4: discord.Role = None,
        role5: discord.Role = None,
        role6: discord.Role = None,
        role7: discord.Role = None,
        role8: discord.Role = None,
        role9: discord.Role = None,
        role10: discord.Role = None,
    ):
        await interaction.response.defer(ephemeral=True)

        passed_roles = [
            r
            for r in [
                role1,
                role2,
                role3,
                role4,
                role5,
                role6,
                role7,
                role8,
                role9,
                role10,
            ]
            if r is not None
        ]

        sorted_roles = sorted(passed_roles, key=lambda r: r.position, reverse=True)
        role_ids = [r.id for r in sorted_roles]

        data = load_data()
        data[str(interaction.guild_id)] = role_ids
        save_data(data)

        summary = "\n".join(
            f"{idx + 1}. {r.mention} (Pos: `{r.position}`)"
            for idx, r in enumerate(sorted_roles)
        )
        await interaction.followup.send(
            f"✅ **Saved Category Order for {interaction.guild.name}:**\n{summary}",
            ephemeral=True,
        )

    @app_commands.command(
        name="createroles_in_category",
        description="Bulk create roles and insert them at the bottom of the chosen category.",
    )
    @app_commands.checks.has_permissions(manage_roles=True)
    async def createroles_in_category(
        self,
        interaction: discord.Interaction,
        role_list: str,
        hoist: bool = False,
        mentionable: bool = False,
    ):
        data = load_data()
        guild_id = str(interaction.guild_id)

        if guild_id not in data or not data[guild_id]:
            await interaction.response.send_message(
                "⚠️ No Category Roles defined for this server yet. Run `/set_category_roles` first!",
                ephemeral=True,
            )
            return

        category_roles = []
        for r_id in data[guild_id]:
            role = interaction.guild.get_role(r_id)
            if role:
                category_roles.append(role)

        if not category_roles:
            await interaction.response.send_message(
                "❌ None of the configured category roles were found in this server.",
                ephemeral=True,
            )
            return

        category_roles.sort(key=lambda r: r.position, reverse=True)

        view = RoleCategoryView(category_roles, role_list, hoist, mentionable)
        await interaction.response.send_message(
            "Select which category these roles belong in:",
            view=view,
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(RoleManager(bot))