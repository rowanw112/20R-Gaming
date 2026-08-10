import asyncio
import json
import logging
import os
import re
import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger(__name__)

CONFIG_FILE = "data/rank_system_config.json"
DATA_FILE = "guild_categories.json"


def load_json(filepath: str) -> dict:
    if not os.path.exists(filepath):
        return {}
    with open(filepath, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}


def save_json(filepath: str, data: dict):
    if "/" in filepath:
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)


def parse_role_ids(guild: discord.Guild, input_str: str | None) -> list[int]:
    """Parses role mentions (<@&12345>), raw IDs, or lists into an ordered list of valid role IDs."""
    if not input_str or not input_str.strip():
        return []

    raw_tokens = re.findall(r"\d+", input_str)
    valid_ids = []

    for token in raw_tokens:
        role_id = int(token)
        if guild.get_role(role_id) and role_id not in valid_ids:
            valid_ids.append(role_id)

    return valid_ids


# -------------------------------------------------------------------------
# HIERARCHY ORDER CONFIGURATION SELECT & VIEW
# -------------------------------------------------------------------------
class StaffHierarchyOrderSelect(discord.ui.Select):
    def __init__(self, guild: discord.Guild, staff_roles: list[discord.Role]):
        self.guild = guild
        self.staff_roles = staff_roles

        options = [
            discord.SelectOption(
                label=r.name[:100],
                value=str(r.id),
                description=f"Role ID: {r.id}"
            )
            for r in staff_roles[:25]
        ]

        super().__init__(
            placeholder="Select Staff Roles in HIGHEST to LOWEST order...",
            min_values=1,
            max_values=len(options),
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild

        ordered_ids = [int(v) for v in self.values]
        
        configs = load_json(CONFIG_FILE)
        cfg = configs.get(str(guild.id), {})
        cfg["staff_role_ids"] = ordered_ids
        configs[str(guild.id)] = cfg
        save_json(CONFIG_FILE, configs)

        cog = interaction.client.get_cog("RoleManager")
        if cog:
            await cog.update_rank_dashboard(guild)

        summary = "\n".join([f"{idx+1}. <@&{rid}>" for idx, rid in enumerate(ordered_ids)])
        await interaction.followup.send(
            f"✅ **Staff Hierarchy Saved (Highest ➔ Lowest):**\n{summary}",
            ephemeral=True,
        )


class RankHierarchyOrderSelect(discord.ui.Select):
    def __init__(self, guild: discord.Guild, rank_roles: list[discord.Role]):
        self.guild = guild
        self.rank_roles = rank_roles

        options = [
            discord.SelectOption(
                label=r.name[:100],
                value=str(r.id),
                description=f"Role ID: {r.id}"
            )
            for r in rank_roles[:25]
        ]

        super().__init__(
            placeholder="Select Rank Roles in HIGHEST to LOWEST order...",
            min_values=1,
            max_values=len(options),
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild

        ordered_ids = [int(v) for v in self.values]
        
        configs = load_json(CONFIG_FILE)
        cfg = configs.get(str(guild.id), {})
        cfg["rank_role_ids"] = ordered_ids
        configs[str(guild.id)] = cfg
        save_json(CONFIG_FILE, configs)

        cog = interaction.client.get_cog("RoleManager")
        if cog:
            await cog.update_rank_dashboard(guild)

        summary = "\n".join([f"{idx+1}. <@&{rid}>" for idx, rid in enumerate(ordered_ids)])
        await interaction.followup.send(
            f"✅ **Rank Progression Hierarchy Saved (Highest ➔ Lowest):**\n{summary}",
            ephemeral=True,
        )


class HierarchyCategorySelectView(discord.ui.View):
    def __init__(self, guild: discord.Guild, cfg: dict):
        super().__init__(timeout=60)
        self.guild = guild
        self.cfg = cfg

    @discord.ui.button(label="Re-Order Staff Hierarchy", style=discord.ButtonStyle.primary, emoji="🛡️")
    async def configure_staff(self, interaction: discord.Interaction, button: discord.ui.Button):
        staff_ids = self.cfg.get("staff_role_ids", [])
        staff_roles = [self.guild.get_role(rid) for rid in staff_ids if self.guild.get_role(rid)]

        if not staff_roles:
            await interaction.response.send_message("❌ No staff roles configured yet. Run `/setup_rank_roles` first!", ephemeral=True)
            return

        select_view = discord.ui.View(timeout=60)
        select_view.add_item(StaffHierarchyOrderSelect(self.guild, staff_roles))
        await interaction.response.send_message(
            "Select the staff roles below in order from **HIGHEST permissions** to **LOWEST permissions**:",
            view=select_view,
            ephemeral=True
        )

    @discord.ui.button(label="Re-Order Rank Progression", style=discord.ButtonStyle.success, emoji="🎖️")
    async def configure_ranks(self, interaction: discord.Interaction, button: discord.ui.Button):
        rank_ids = self.cfg.get("rank_role_ids", [])
        rank_roles = [self.guild.get_role(rid) for rid in rank_ids if self.guild.get_role(rid)]

        if not rank_roles:
            await interaction.response.send_message("❌ No rank roles configured yet. Run `/setup_rank_roles` first!", ephemeral=True)
            return

        select_view = discord.ui.View(timeout=60)
        select_view.add_item(RankHierarchyOrderSelect(self.guild, rank_roles))
        await interaction.response.send_message(
            "Select the rank roles below in order from **HIGHEST rank** to **LOWEST rank**:",
            view=select_view,
            ephemeral=True
        )


# -------------------------------------------------------------------------
# BATCH FORM MODAL (Fills up to 5 Roles per Form)
# -------------------------------------------------------------------------
class BatchPrefixFormModal(discord.ui.Modal):
    def __init__(self, category_name: str, roles: list[discord.Role], current_prefixes: dict[str, str]):
        super().__init__(title=f"Set Tags: {category_name[:20]}")
        self.roles = roles[:5]
        self.inputs: dict[int, discord.ui.TextInput] = {}

        for role in self.roles:
            current = current_prefixes.get(str(role.id), "")
            text_input = discord.ui.TextInput(
                label=f"Tag for {role.name[:30]}",
                placeholder="e.g. [R], [I], [Mod], or leave blank",
                default=current,
                required=False,
                max_length=15,
            )
            self.inputs[role.id] = text_input
            self.add_item(text_input)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild

        configs = load_json(CONFIG_FILE)
        cfg = configs.get(str(guild.id), {})
        prefixes = cfg.get("role_prefixes", {})

        updated_summary = []
        for role_id, text_input in self.inputs.items():
            new_val = text_input.value.strip()
            role = guild.get_role(role_id)
            if new_val:
                prefixes[str(role_id)] = new_val
                updated_summary.append(f"• {role.mention if role else role_id} ➔ `{new_val}`")
            else:
                prefixes.pop(str(role_id), None)
                updated_summary.append(f"• {role.mention if role else role_id} ➔ *Cleared*")

        cfg["role_prefixes"] = prefixes
        configs[str(guild.id)] = cfg
        save_json(CONFIG_FILE, configs)

        cog = interaction.client.get_cog("RoleManager")
        if cog:
            await cog.update_rank_dashboard(guild)

        summary_text = "\n".join(updated_summary) if updated_summary else "No changes made."
        logger.info(f"[RoleManager] Prefix tags updated by {interaction.user.display_name} in guild '{guild.name}'.")
        await interaction.followup.send(
            f"✅ **Prefix Tags Updated!**\n{summary_text}",
            ephemeral=True,
        )


class PrefixCategorySelect(discord.ui.Select):
    def __init__(self, guild: discord.Guild, cfg: dict):
        self.cfg = cfg
        self.guild = guild

        options = []
        
        staff_ids = cfg.get("staff_role_ids", [])
        if staff_ids:
            for i in range(0, len(staff_ids), 5):
                batch_num = (i // 5) + 1
                options.append(discord.SelectOption(
                    label=f"🛡️ Staff Roles (Batch {batch_num})", 
                    value=f"staff_{i}", 
                    description=f"Configure Staff Roles {i+1} to {min(i+5, len(staff_ids))}"
                ))

        rank_ids = cfg.get("rank_role_ids", [])
        if rank_ids:
            for i in range(0, len(rank_ids), 5):
                batch_num = (i // 5) + 1
                options.append(discord.SelectOption(
                    label=f"🎖️ Rank Roles (Batch {batch_num})", 
                    value=f"rank_{i}", 
                    description=f"Configure Ranks {i+1} to {min(i+5, len(rank_ids))}"
                ))

        basic_ids = cfg.get("basic_role_ids", [])
        recruit_id = cfg.get("recruit_role_id")
        combined_basic = list(set(basic_ids + ([recruit_id] if recruit_id else [])))
        if combined_basic:
            options.append(discord.SelectOption(label="🔰 Basic & Recruit Roles", value="basic", description="Configure Basic/Recruit Role Tags"))

        super().__init__(
            placeholder="Choose a category to open its Tag Form...",
            min_values=1,
            max_values=1,
            options=options if options else [discord.SelectOption(label="No Configured Roles", value="none")],
        )

    async def callback(self, interaction: discord.Interaction):
        choice = self.values[0]
        if choice == "none":
            await interaction.response.send_message("❌ No roles configured yet.", ephemeral=True)
            return

        prefixes = self.cfg.get("role_prefixes", {})
        target_roles: list[discord.Role] = []
        cat_label = "Role Tags"

        if choice.startswith("staff_"):
            offset = int(choice.split("_")[1])
            cat_label = f"Staff Roles ({offset+1}-{offset+5})"
            s_ids = self.cfg.get("staff_role_ids", [])[offset:offset+5]
            target_roles = [self.guild.get_role(rid) for rid in s_ids if self.guild.get_role(rid)]

        elif choice.startswith("rank_"):
            offset = int(choice.split("_")[1])
            cat_label = f"Rank Roles ({offset+1}-{offset+5})"
            r_ids = self.cfg.get("rank_role_ids", [])[offset:offset+5]
            target_roles = [self.guild.get_role(rid) for rid in r_ids if self.guild.get_role(rid)]

        elif choice == "basic":
            cat_label = "Basic & Recruit Roles"
            b_ids = self.cfg.get("basic_role_ids", [])
            rec_id = self.cfg.get("recruit_role_id")
            combined = list(set(b_ids + ([rec_id] if rec_id else [])))
            target_roles = [self.guild.get_role(rid) for rid in combined if self.guild.get_role(rid)]

        if not target_roles:
            await interaction.response.send_message("❌ Selected category has no valid server roles.", ephemeral=True)
            return

        await interaction.response.send_modal(
            BatchPrefixFormModal(cat_label, target_roles, prefixes)
        )


class RankDashboardView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Configure Nickname Prefixes",
        style=discord.ButtonStyle.primary,
        emoji="🏷️",
        custom_id="rank_dashboard_config_prefixes",
    )
    async def configure_prefixes(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "❌ Only Administrators can configure role prefixes!",
                ephemeral=True,
            )
            return

        guild = interaction.guild
        configs = load_json(CONFIG_FILE)
        cfg = configs.get(str(guild.id), {})

        select_view = discord.ui.View(timeout=60)
        select_view.add_item(PrefixCategorySelect(guild, cfg))

        await interaction.response.send_message(
            "Select a category below to open a form for its role tags:",
            view=select_view,
            ephemeral=True,
        )

    @discord.ui.button(
        label="Configure Hierarchy Order",
        style=discord.ButtonStyle.secondary,
        emoji="⚙️",
        custom_id="rank_dashboard_config_hierarchy",
    )
    async def configure_hierarchy(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "❌ Only Administrators can configure role hierarchies!",
                ephemeral=True,
            )
            return

        guild = interaction.guild
        configs = load_json(CONFIG_FILE)
        cfg = configs.get(str(guild.id), {})

        await interaction.response.send_message(
            "Choose a category below to adjust its role ranking hierarchy:",
            view=HierarchyCategorySelectView(guild, cfg),
            ephemeral=True,
        )


# -------------------------------------------------------------------------
# CATEGORY ROLE CREATION SELECT
# -------------------------------------------------------------------------
class RoleCategorySelect(discord.ui.Select):
    def __init__(
        self,
        categories: list[discord.Role],
        role_list_str: str,
        hoist: bool,
        mentionable: bool,
    ):
        self.categories = categories
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

        if created_roles and target_category_role:
            try:
                all_roles = sorted(guild.roles, key=lambda r: r.position, reverse=True)
                pivot_role = (
                    next_category_role if next_category_role else target_category_role
                )
                existing_roles = [r for r in all_roles if r not in created_roles]

                insert_idx = (
                    existing_roles.index(pivot_role)
                    if next_category_role
                    else existing_roles.index(pivot_role) + 1
                )
                new_role_order = (
                    existing_roles[:insert_idx]
                    + created_roles
                    + existing_roles[insert_idx:]
                )

                position_payload = {}
                total_count = len(new_role_order)
                for idx, r in enumerate(new_role_order):
                    if not r.is_default():
                        position_payload[r] = total_count - idx

                await guild.edit_role_positions(positions=position_payload)

            except (discord.HTTPException, ValueError) as e:
                logger.error(f"[RoleManager] Failed to set role positions: {e}", exc_info=True)

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


# -------------------------------------------------------------------------
# MAIN ROLE MANAGER COG
# -------------------------------------------------------------------------
class RoleManager(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._processing_users = set()

    async def cog_load(self):
        self.bot.add_view(RankDashboardView())

    @commands.Cog.listener()
    async def on_ready(self):
        logger.info("[RoleManager] 🔄 Refreshing Rank Rules Dashboards on startup...")
        configs = load_json(CONFIG_FILE)
        for guild in self.bot.guilds:
            if str(guild.id) in configs:
                try:
                    await self.update_rank_dashboard(guild)
                except Exception as e:
                    logger.error(f"[RoleManager] Failed to auto-update dashboard for guild '{guild.name}': {e}", exc_info=True)
        logger.info("[RoleManager] ✅ Rank Rules Dashboards refreshed!")

    async def _update_member_nickname_prefix(
        self, member: discord.Member, cfg: dict
    ):
        if member.id == member.guild.owner_id:
            return

        prefixes = cfg.get("role_prefixes", {})
        if not prefixes:
            return

        staff_ids = cfg.get("staff_role_ids", [])
        rank_ids = cfg.get("rank_role_ids", [])
        recruit_id = cfg.get("recruit_role_id")
        basic_ids = cfg.get("basic_role_ids", [])

        priority_order = []
        priority_order.extend(staff_ids)
        priority_order.extend(rank_ids)
        if recruit_id:
            priority_order.append(recruit_id)
        priority_order.extend(basic_ids)

        active_prefix = None
        user_role_ids = {r.id for r in member.roles}

        for rid in priority_order:
            if rid in user_role_ids and str(rid) in prefixes:
                active_prefix = prefixes[str(rid)]
                break

        current_nick = member.display_name
        clean_name = re.sub(r"^\[.*?\]\s*|^\(.*?\)\s*", "", current_nick).strip()

        target_nick = f"{active_prefix} {clean_name}" if active_prefix else clean_name
        target_nick = target_nick[:32]

        if current_nick != target_nick:
            try:
                await member.edit(
                    nick=target_nick, reason="Dynamic Role Prefix Sync"
                )
                logger.info(
                    f"[RoleManager] 🏷️ Nickname Updated: '{current_nick}' ➔ '{target_nick}' "
                    f"for user {member.display_name} ({member.id}) [Matched Prefix: '{active_prefix}']"
                )
            except discord.Forbidden:
                logger.warning(
                    f"[RoleManager] ⚠️ Forbidden: Lacking permissions to edit nickname for {member.display_name} ({member.id})."
                )
            except discord.HTTPException as e:
                logger.error(
                    f"[RoleManager] ❌ Failed to update nickname for {member.display_name} ({member.id}): {e}"
                )

    async def update_rank_dashboard(self, guild: discord.Guild):
        configs = load_json(CONFIG_FILE)
        cfg = configs.get(str(guild.id), {})

        channel_id = cfg.get("dashboard_channel_id")
        message_id = cfg.get("dashboard_message_id")

        if not channel_id:
            return

        channel = guild.get_channel(channel_id)
        if not channel:
            try:
                channel = await guild.fetch_channel(channel_id)
            except (discord.NotFound, discord.HTTPException):
                return

        if not isinstance(channel, discord.TextChannel):
            return

        prefixes = cfg.get("role_prefixes", {})

        basic_ids = cfg.get("basic_role_ids", [])
        basic_roles = [guild.get_role(rid) for rid in basic_ids if guild.get_role(rid)]
        basic_formatted = [
            f"{r.mention} [`{prefixes.get(str(r.id), 'None')}`]" for r in basic_roles
        ]
        basic_str = ", ".join(basic_formatted) if basic_formatted else "`None Configured`"

        recruit_role = guild.get_role(cfg.get("recruit_role_id", 0))
        recruit_pfx = prefixes.get(str(recruit_role.id)) if recruit_role else None
        recruit_str = (
            f"{recruit_role.mention} [`{recruit_pfx or 'None'}`]"
            if recruit_role
            else "`Not Configured`"
        )

        member_role = guild.get_role(cfg.get("member_role_id", 0))
        member_str = member_role.mention if member_role else "the required Member role"

        staff_ids = cfg.get("staff_role_ids", [])
        staff_roles = [guild.get_role(rid) for rid in staff_ids if guild.get_role(rid)]
        staff_formatted = [
            f"{r.mention} [`{prefixes.get(str(r.id), 'None')}`]" for r in staff_roles
        ]
        staff_str = " ➔ ".join(staff_formatted) if staff_formatted else "`None Configured`"

        rank_ids = cfg.get("rank_role_ids", [])
        rank_roles = [guild.get_role(rid) for rid in rank_ids if guild.get_role(rid)]
        ranks_formatted = [
            f"{r.mention} [`{prefixes.get(str(r.id), 'None')}`]" for r in rank_roles
        ]
        ranks_str = " ➔ ".join(ranks_formatted) if ranks_formatted else "`None Configured`"

        bot_member = guild.me
        problematic_roles = []
        all_configured_roles = staff_roles + rank_roles + ([recruit_role] if recruit_role else []) + ([member_role] if member_role else [])
        
        for r in all_configured_roles:
            if r and r.position >= bot_member.top_role.position:
                problematic_roles.append(r.mention)

        hierarchy_warning = ""
        if problematic_roles:
            hierarchy_warning = (
                f"\n\n⚠️ **CRITICAL BOT ROLE HIERARCHY WARNING:**\n"
                f"The bot's top role is below the following role(s): {', '.join(problematic_roles)}.\n"
                f"Please drag the bot's role **above** these roles in Discord Role Settings so it can assign them!"
            )

        basic_rules_text = (
            f"Members can only hold **one** basic role ({', '.join([r.mention for r in basic_roles])}) at a time."
            if basic_roles
            else "Members can only hold **one** configured Basic Role at a time."
        )

        embed = discord.Embed(
            title="📊 20R Staff, Membership & Rank System Rules",
            description=(
                "This dashboard details how basic roles, staff permissions, "
                "member progression, rank restrictions, and nickname tags operate automatically."
                f"{hierarchy_warning}"
            ),
            color=discord.Color.red() if problematic_roles else discord.Color.gold(),
            timestamp=discord.utils.utcnow(),
        )

        embed.add_field(
            name="🆔 Configured Server Roles & Prefixes",
            value=(
                f"• **Basic Roles:** {basic_str}\n"
                f"• **Recruit Role:** {recruit_str}\n"
                f"• **Member Requirement:** {member_str}\n"
                f"• **Staff Hierarchy (Highest ➔ Lowest):** {staff_str}\n"
                f"• **Rank Hierarchy (Highest ➔ Lowest):** {ranks_str}"
            ),
            inline=False,
        )

        embed.add_field(
            name="🛠️ Staff Instructions: How to Change Server Roles",
            value=(
                "Admins can configure or re-link any category of roles anytime using `/setup_rank_roles`:\n"
                "• `basic_roles` — Pass space or comma separated mentions (e.g. `@Visitor @Friend`).\n"
                "• `recruit_role` — Select the role granted upon passing application.\n"
                "• `member_role` — Select the required full member role (e.g. `@20R Member`).\n"
                "• `staff_roles` — List all staff roles (e.g. `@Moderator @Admin`).\n"
                "• `rank_roles` — List all dynamic ranks (e.g. `@Rank I @Rank II ...`).\n\n"
                "*Note: You can update a single option while leaving others omitted—the bot will retain your existing settings!*"
            ),
            inline=False,
        )

        embed.add_field(
            name="🚫 Incompatible & Mutually Exclusive Rules",
            value=(
                f"• **Basic Roles Exclusivity:** {basic_rules_text}\n"
                f"• **Member Requirement:** Holding any Rank or Staff role strictly enforces having {member_str}.\n"
                f"• **Recruit Exclusivity:** Holding {recruit_str if recruit_role else 'Recruit'} strictly strips {member_str}, Rank, and Staff roles.\n"
                f"• **Multiple Ranks:** Rank roles are mutually exclusive. Progression maintains a single active rank."
            ),
            inline=False,
        )

        embed.add_field(
            name="🏷️ Nickname Tag System",
            value=(
                "Staff can click the button below to assign custom nickname tags for Staff, Rank, or Basic roles.\n"
                "• Gaining a role automatically prepends its tag to the member's server nickname.\n"
                "• Staff tags take priority over rank tags if a member holds both."
            ),
            inline=False,
        )

        embed.set_footer(text="Live Dynamic Staff & Rank Rules | 20R System")

        view = RankDashboardView()

        if message_id:
            try:
                msg = await channel.fetch_message(message_id)
                await msg.edit(embed=embed, view=view)
                return
            except (discord.NotFound, discord.HTTPException):
                pass

        posted_msg = await channel.send(embed=embed, view=view)
        try:
            await posted_msg.pin(reason="Rank Mapping System Rules")
        except (discord.Forbidden, discord.HTTPException):
            pass

        cfg["dashboard_message_id"] = posted_msg.id
        configs[str(guild.id)] = cfg
        save_json(CONFIG_FILE, configs)

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role):
        """Scorched-earth cleanup if a configured role is deleted from Discord Settings."""
        configs = load_json(CONFIG_FILE)
        cfg = configs.get(str(role.guild.id), {})

        modified = False
        for key in ["basic_role_ids", "staff_role_ids", "rank_role_ids"]:
            if role.id in cfg.get(key, []):
                cfg[key].remove(role.id)
                modified = True

        if cfg.get("recruit_role_id") == role.id:
            cfg["recruit_role_id"] = None
            modified = True

        if cfg.get("member_role_id") == role.id:
            cfg["member_role_id"] = None
            modified = True

        if str(role.id) in cfg.get("role_prefixes", {}):
            cfg["role_prefixes"].pop(str(role.id), None)
            modified = True

        if modified:
            logger.info(f"[RoleManager] 🧹 Cleaned up deleted role '{role.name}' ({role.id}) from guild '{role.guild.name}' config.")
            configs[str(role.guild.id)] = cfg
            save_json(CONFIG_FILE, configs)
            await self.update_rank_dashboard(role.guild)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        """Strict Dynamic ID-based Listener for Basic Roles, Staff, Ranks, and Prefixes."""
        if after.bot:
            return

        if after.id in self._processing_users:
            return

        guild = after.guild
        configs = load_json(CONFIG_FILE)
        cfg = configs.get(str(guild.id), {})

        # ---------------------------------------------------------------------
        # SELF-NICKNAME OVERRIDE PROTECTION
        # Triggered when roles remain identical but the user changed their display name
        # ---------------------------------------------------------------------
        if before.roles == after.roles:
            if before.display_name != after.display_name:
                self._processing_users.add(after.id)
                try:
                    await self._update_member_nickname_prefix(after, cfg)
                finally:
                    self._processing_users.remove(after.id)
            return

        self._processing_users.add(after.id)

        try:
            basic_role_ids = cfg.get("basic_role_ids", [])
            recruit_role_id = cfg.get("recruit_role_id")
            member_role_id = cfg.get("member_role_id")
            staff_role_ids = cfg.get("staff_role_ids", [])
            rank_role_ids = cfg.get("rank_role_ids", [])

            added_role_ids = {r.id for r in (set(after.roles) - set(before.roles))}
            removed_role_ids = {r.id for r in (set(before.roles) - set(after.roles))}
            user_role_ids = {r.id for r in after.roles}

            added_roles_str = ", ".join([f"'{r.name}' ({r.id})" for r in (set(after.roles) - set(before.roles))])
            removed_roles_str = ", ".join([f"'{r.name}' ({r.id})" for r in (set(before.roles) - set(after.roles))])
            logger.info(
                f"[RoleManager] 🔄 Role Change Detected for {after.display_name} ({after.id}) in '{guild.name}': "
                f"Gained: [{added_roles_str or 'None'}] | Lost: [{removed_roles_str or 'None'}]"
            )

            roles_to_remove = []
            roles_to_add = []

            pure_basic_ids = [rid for rid in basic_role_ids if rid != member_role_id and rid != recruit_role_id]

            # 1. GAINED RECRUIT OR BASIC ENTRY ROLE -> STRIP STAFF & RANKS
            if recruit_role_id and recruit_role_id in added_role_ids:
                for r in after.roles:
                    if r.id in rank_role_ids or r.id in staff_role_ids or r.id == member_role_id or r.id in pure_basic_ids:
                        if r.id != recruit_role_id and r not in roles_to_remove:
                            roles_to_remove.append(r)

            elif any(rid in added_role_ids for rid in pure_basic_ids):
                for r in after.roles:
                    if r.id in rank_role_ids or r.id in staff_role_ids or r.id == member_role_id or r.id == recruit_role_id:
                        if r.id not in added_role_ids and r not in roles_to_remove:
                            roles_to_remove.append(r)

            # 2. PURE BASIC ROLES MUTUAL EXCLUSIVITY (Visitor vs Stranger vs Friend)
            active_pure_basic_ids = [
                rid for rid in pure_basic_ids 
                if rid in user_role_ids and rid not in [r.id for r in roles_to_remove]
            ]
            if len(active_pure_basic_ids) > 1:
                newest_pure_id = next((rid for rid in added_role_ids if rid in pure_basic_ids), None)
                primary_pure_id = newest_pure_id if newest_pure_id else active_pure_basic_ids[0]

                for rid in active_pure_basic_ids:
                    if rid != primary_pure_id:
                        b_obj = guild.get_role(rid)
                        if b_obj and b_obj not in roles_to_remove:
                            roles_to_remove.append(b_obj)

            # 3. MUTUAL EXCLUSIVITY: RANK ROLES (Keep newest rank)
            active_rank_ids = [
                rid for rid in rank_role_ids 
                if rid in user_role_ids and rid not in [r.id for r in roles_to_remove]
            ]
            if len(active_rank_ids) > 1:
                newest_rank_id = next((rid for rid in added_role_ids if rid in rank_role_ids), None)
                primary_rank_id = newest_rank_id if newest_rank_id else active_rank_ids[0]

                for rid in active_rank_ids:
                    if rid != primary_rank_id:
                        r_obj = guild.get_role(rid)
                        if r_obj and r_obj not in roles_to_remove:
                            roles_to_remove.append(r_obj)

            # 4. MUTUAL EXCLUSIVITY: STAFF ROLES (Keep newest staff role)
            active_staff_ids = [
                rid for rid in staff_role_ids 
                if rid in user_role_ids and rid not in [r.id for r in roles_to_remove]
            ]
            if len(active_staff_ids) > 1:
                newest_staff_id = next((rid for rid in added_role_ids if rid in staff_role_ids), None)
                primary_staff_id = newest_staff_id if newest_staff_id else active_staff_ids[0]

                for rid in active_staff_ids:
                    if rid != primary_staff_id:
                        s_obj = guild.get_role(rid)
                        if s_obj and s_obj not in roles_to_remove:
                            roles_to_remove.append(s_obj)

            # 5. MEMBER EXPLICITLY LOST MEMBER ROLE -> STRIP STAFF, RANKS, RECRUIT
            if member_role_id and member_role_id in removed_role_ids:
                for r in after.roles:
                    if r.id in rank_role_ids or r.id in staff_role_ids or r.id == recruit_role_id:
                        if r not in roles_to_remove:
                            roles_to_remove.append(r)

                if roles_to_remove:
                    try:
                        await after.remove_roles(
                            *roles_to_remove,
                            reason="Lost Member status — Automatically stripped Staff and Rank roles.",
                        )
                        logger.info(f"[RoleManager] 🧹 Stripped Staff/Rank roles from {after.display_name} due to Member Role loss.")
                    except discord.HTTPException as e:
                        logger.error(f"[RoleManager] Failed to strip staff/ranks: {e}")
                await self._update_member_nickname_prefix(after, cfg)
                return

            remaining_staff = [rid for rid in staff_role_ids if rid in user_role_ids and rid not in [r.id for r in roles_to_remove]]
            remaining_ranks = [rid for rid in rank_role_ids if rid in user_role_ids and rid not in [r.id for r in roles_to_remove]]

            # 6. MEMBER HAS STAFF OR RANK ROLES -> ENFORCE MEMBER ROLE AND STRIP PURE BASIC & RECRUIT ROLES
            has_member = member_role_id and member_role_id in user_role_ids
            if remaining_staff or remaining_ranks:
                if member_role_id and member_role_id not in user_role_ids:
                    m_role = guild.get_role(member_role_id)
                    if m_role and m_role not in roles_to_add:
                        roles_to_add.append(m_role)

            if has_member or remaining_staff or remaining_ranks:
                for rid in pure_basic_ids + ([recruit_role_id] if recruit_role_id else []):
                    if rid in user_role_ids and rid not in added_role_ids:
                        b_role = guild.get_role(rid)
                        if b_role and b_role not in roles_to_remove:
                            roles_to_remove.append(b_role)

            # Safeguard: Explicitly block recruit_role_id from ever appearing in roles_to_remove if added in this event
            if recruit_role_id and recruit_role_id in added_role_ids:
                roles_to_remove = [r for r in roles_to_remove if r.id != recruit_role_id]

            if roles_to_add:
                add_names = ", ".join([f"'{r.name}' ({r.id})" for r in roles_to_add])
                try:
                    await after.add_roles(
                        *roles_to_add,
                        reason="Auto-assigned Member Role for Staff/Ranked Member",
                    )
                    logger.info(f"[RoleManager] ✅ Granted required role(s) [{add_names}] to {after.display_name} ({after.id}).")
                except discord.HTTPException as e:
                    logger.error(f"[RoleManager] ❌ Failed to add role(s) [{add_names}] to {after.display_name} ({after.id}): {e}", exc_info=True)

            if roles_to_remove:
                remove_names = ", ".join([f"'{r.name}' ({r.id})" for r in roles_to_remove])
                try:
                    await after.remove_roles(
                        *roles_to_remove, reason="Role Exclusivity Reconciliation"
                    )
                    logger.info(f"[RoleManager] 🧹 Stripped exclusive role(s) [{remove_names}] from {after.display_name} ({after.id}).")
                except discord.HTTPException as e:
                    logger.error(f"[RoleManager] ❌ Failed to remove role(s) [{remove_names}] from {after.display_name} ({after.id}): {e}", exc_info=True)

            fresh_member = guild.get_member(after.id) or after
            await self._update_member_nickname_prefix(fresh_member, cfg)

        finally:
            self._processing_users.remove(after.id)

    @app_commands.command(
        name="force_rank_audit",
        description="Run a full server audit to enforce rank rules and nickname tags across all members.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def force_rank_audit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        configs = load_json(CONFIG_FILE)
        cfg = configs.get(str(guild.id), {})

        audited_count = 0
        for member in guild.members:
            if not member.bot:
                await self._update_member_nickname_prefix(member, cfg)
                audited_count += 1
                await asyncio.sleep(0.05)

        await interaction.followup.send(
            f"✅ **Server Audit Complete!** Audited and reconciled nickname tags for {audited_count} members.",
            ephemeral=True,
        )

    @app_commands.command(
        name="setup_rank_roles",
        description="Configure dynamic lists of Basic, Recruit, Member, Staff, and Rank roles.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_rank_roles(
        self,
        interaction: discord.Interaction,
        member_role: discord.Role = None,
        recruit_role: discord.Role = None,
        basic_roles: str = None,
        staff_roles: str = None,
        rank_roles: str = None,
    ):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild

        configs = load_json(CONFIG_FILE)
        guild_cfg = configs.get(str(guild.id), {})

        if member_role:
            guild_cfg["member_role_id"] = member_role.id
        if recruit_role:
            guild_cfg["recruit_role_id"] = recruit_role.id

        if basic_roles is not None:
            parsed_basic_ids = parse_role_ids(guild, basic_roles)
            if member_role and member_role.id in parsed_basic_ids:
                parsed_basic_ids.remove(member_role.id)
            guild_cfg["basic_role_ids"] = parsed_basic_ids

        if staff_roles is not None:
            parsed_staff_ids = parse_role_ids(guild, staff_roles)
            guild_cfg["staff_role_ids"] = parsed_staff_ids

        if rank_roles is not None:
            parsed_rank_ids = parse_role_ids(guild, rank_roles)
            guild_cfg["rank_role_ids"] = parsed_rank_ids

        configs[str(guild.id)] = guild_cfg
        save_json(CONFIG_FILE, configs)

        await self.update_rank_dashboard(guild)

        b_str = (
            ", ".join([f"<@&{rid}>" for rid in guild_cfg.get("basic_role_ids", [])])
            if guild_cfg.get("basic_role_ids")
            else "`Not Set`"
        )
        rec_str = (
            f"<@&{guild_cfg.get('recruit_role_id')}>"
            if guild_cfg.get("recruit_role_id")
            else "`Not Set`"
        )
        s_str = (
            ", ".join([f"<@&{rid}>" for rid in guild_cfg.get("staff_role_ids", [])])
            if guild_cfg.get("staff_role_ids")
            else "`Not Set`"
        )
        m_str = (
            f"<@&{guild_cfg.get('member_role_id')}>"
            if guild_cfg.get("member_role_id")
            else "`Not Set`"
        )
        ranks_str = (
            ", ".join([f"<@&{rid}>" for rid in guild_cfg.get("rank_role_ids", [])])
            if guild_cfg.get("rank_role_ids")
            else "`Not Set`"
        )

        await interaction.followup.send(
            f"✅ **Dynamic Roles Configuration Updated!**\n"
            f"• **Basic Roles:** {b_str}\n"
            f"• **Recruit Role:** {rec_str}\n"
            f"• **Member Requirement Role:** {m_str}\n"
            f"• **Staff Roles:** {s_str}\n"
            f"• **Rank Roles:** {ranks_str}",
            ephemeral=True,
        )

    @app_commands.command(
        name="set_rank_dashboard",
        description="Set the channel to post and maintain the live Rank Rules Dashboard.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def set_rank_dashboard(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel | None = None,
    ):
        await interaction.response.defer(ephemeral=True)
        target_channel = channel or interaction.channel

        if not isinstance(target_channel, discord.TextChannel):
            await interaction.followup.send(
                "❌ Target channel must be a text channel!", ephemeral=True
            )
            return

        configs = load_json(CONFIG_FILE)
        guild_cfg = configs.get(str(interaction.guild_id), {})

        guild_cfg["dashboard_channel_id"] = target_channel.id
        guild_cfg["dashboard_message_id"] = None
        configs[str(interaction.guild_id)] = guild_cfg
        save_json(CONFIG_FILE, configs)

        await self.update_rank_dashboard(interaction.guild)

        await interaction.followup.send(
            f"✅ Rank Dashboard active in {target_channel.mention}!", ephemeral=True
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(RoleManager(bot))