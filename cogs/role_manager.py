import asyncio
import json
import logging
import os
import re
import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger(__name__)


def get_config_path(guild_id: int) -> str:
    path = f"data/{guild_id}"
    os.makedirs(path, exist_ok=True)
    return f"{path}/rank_system_config.json"


def load_json(guild_id: int) -> dict:
    filepath = get_config_path(guild_id)
    if not os.path.exists(filepath):
        return {}
    with open(filepath, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}


def save_json(guild_id: int, data: dict):
    filepath = get_config_path(guild_id)
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
class EliteHierarchyOrderSelect(discord.ui.Select):
    def __init__(self, guild: discord.Guild, elite_roles: list[discord.Role]):
        self.guild = guild
        self.elite_roles = elite_roles

        options = [
            discord.SelectOption(
                label=r.name[:100],
                value=str(r.id),
                description=f"Role ID: {r.id}"
            )
            for r in elite_roles[:25]
        ]

        super().__init__(
            placeholder="Select Elite Roles in HIGHEST to LOWEST order...",
            min_values=1,
            max_values=len(options),
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild

        ordered_ids = [int(v) for v in self.values]
        
        cfg = load_json(guild.id)
        cfg["elite_role_ids"] = ordered_ids
        save_json(guild.id, cfg)

        cog = interaction.client.get_cog("RoleManager")
        if cog:
            await cog.update_rank_dashboard(guild)

        rank_disp = interaction.client.get_cog("RankDisplay")
        if rank_disp:
            await rank_disp.update_public_display(guild)

        summary = "\n".join([f"{idx+1}. <@&{rid}>" for idx, rid in enumerate(ordered_ids)])
        await interaction.followup.send(
            f"✅ **Elite Hierarchy Saved (Highest ➔ Lowest):**\n{summary}",
            ephemeral=True,
        )


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
        
        cfg = load_json(guild.id)
        cfg["staff_role_ids"] = ordered_ids
        save_json(guild.id, cfg)

        cog = interaction.client.get_cog("RoleManager")
        if cog:
            await cog.update_rank_dashboard(guild)

        rank_disp = interaction.client.get_cog("RankDisplay")
        if rank_disp:
            await rank_disp.update_public_display(guild)

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
        
        cfg = load_json(guild.id)
        cfg["rank_role_ids"] = ordered_ids
        save_json(guild.id, cfg)

        cog = interaction.client.get_cog("RoleManager")
        if cog:
            await cog.update_rank_dashboard(guild)

        rank_disp = interaction.client.get_cog("RankDisplay")
        if rank_disp:
            await rank_disp.update_public_display(guild)

        summary = "\n".join([f"{idx+1}. <@&{rid}>" for idx, rid in enumerate(ordered_ids)])
        await interaction.followup.send(
            f"✅ **Rank Progression Hierarchy Saved (Highest ➔ Lowest):**\n{summary}",
            ephemeral=True,
        )


class BasicHierarchyOrderSelect(discord.ui.Select):
    def __init__(self, guild: discord.Guild, basic_roles: list[discord.Role]):
        self.guild = guild
        self.basic_roles = basic_roles

        options = [
            discord.SelectOption(
                label=r.name[:100],
                value=str(r.id),
                description=f"Role ID: {r.id}"
            )
            for r in basic_roles[:25]
        ]

        super().__init__(
            placeholder="Select Visitor Roles in HIGHEST to LOWEST order...",
            min_values=1,
            max_values=len(options),
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild

        ordered_ids = [int(v) for v in self.values]
        
        cfg = load_json(guild.id)
        cfg["basic_role_ids"] = ordered_ids
        save_json(guild.id, cfg)

        cog = interaction.client.get_cog("RoleManager")
        if cog:
            await cog.update_rank_dashboard(guild)

        rank_disp = interaction.client.get_cog("RankDisplay")
        if rank_disp:
            await rank_disp.update_public_display(guild)

        summary = "\n".join([f"{idx+1}. <@&{rid}>" for idx, rid in enumerate(ordered_ids)])
        await interaction.followup.send(
            f"✅ **Visitor & Guest Hierarchy Saved (Highest ➔ Lowest):**\n{summary}",
            ephemeral=True,
        )


class HierarchyCategorySelectView(discord.ui.View):
    def __init__(self, guild: discord.Guild, cfg: dict):
        super().__init__(timeout=60)
        self.guild = guild
        self.cfg = cfg

    @discord.ui.button(label="Re-Order Elite Roles", style=discord.ButtonStyle.primary, emoji="🔱")
    async def configure_elite(self, interaction: discord.Interaction, button: discord.ui.Button):
        elite_ids = self.cfg.get("elite_role_ids", [])
        elite_roles = [self.guild.get_role(rid) for rid in elite_ids if self.guild.get_role(rid)]

        if not elite_roles:
            await interaction.response.send_message("❌ No elite roles configured yet. Run `/setup_rank_roles` first!", ephemeral=True)
            return

        select_view = discord.ui.View(timeout=60)
        select_view.add_item(EliteHierarchyOrderSelect(self.guild, elite_roles))
        await interaction.response.send_message(
            "Select the Elite roles below in order from **HIGHEST prestige** to **LOWEST prestige**:",
            view=select_view,
            ephemeral=True
        )

    @discord.ui.button(label="Re-Order Staff Roles", style=discord.ButtonStyle.primary, emoji="🛡️")
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

    @discord.ui.button(label="Re-Order Visitor/Guest Tiers", style=discord.ButtonStyle.secondary, emoji="🔰")
    async def configure_basic(self, interaction: discord.Interaction, button: discord.ui.Button):
        basic_ids = self.cfg.get("basic_role_ids", [])
        visitor_ids = self.cfg.get("visitor_role_ids", [])
        combined_ids = list(set(basic_ids + visitor_ids))

        basic_roles = [self.guild.get_role(rid) for rid in combined_ids if self.guild.get_role(rid)]

        if not basic_roles:
            await interaction.response.send_message("❌ No visitor/guest roles configured yet. Run `/setup_rank_roles` first!", ephemeral=True)
            return

        select_view = discord.ui.View(timeout=60)
        select_view.add_item(BasicHierarchyOrderSelect(self.guild, basic_roles))
        await interaction.response.send_message(
            "Select the visitor/guest roles below in order from **HIGHEST guest** (e.g. Friend) to **ENTRY level** (e.g. Stranger):",
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
                placeholder="e.g. [R], [I], [VG], or leave blank",
                default=current,
                required=False,
                max_length=15,
            )
            self.inputs[role.id] = text_input
            self.add_item(text_input)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild

        cfg = load_json(guild.id)
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
        save_json(guild.id, cfg)

        cog = interaction.client.get_cog("RoleManager")
        if cog:
            await cog.update_rank_dashboard(guild)

        rank_disp = interaction.client.get_cog("RankDisplay")
        if rank_disp:
            await rank_disp.update_public_display(guild)

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
        
        elite_ids = cfg.get("elite_role_ids", [])
        if elite_ids:
            for i in range(0, len(elite_ids), 5):
                batch_num = (i // 5) + 1
                options.append(discord.SelectOption(
                    label=f"🔱 Elite Roles (Batch {batch_num})", 
                    value=f"elite_{i}", 
                    description=f"Configure Elite Roles {i+1} to {min(i+5, len(elite_ids))}"
                ))

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
        visitor_ids = cfg.get("visitor_role_ids", [])
        recruit_id = cfg.get("recruit_role_id")
        combined_basic = list(set(basic_ids + visitor_ids + ([recruit_id] if recruit_id else [])))
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

        if choice.startswith("elite_"):
            offset = int(choice.split("_")[1])
            cat_label = f"Elite Roles ({offset+1}-{offset+5})"
            e_ids = self.cfg.get("elite_role_ids", [])[offset:offset+5]
            target_roles = [self.guild.get_role(rid) for rid in e_ids if self.guild.get_role(rid)]

        elif choice.startswith("staff_"):
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
            v_ids = self.cfg.get("visitor_role_ids", [])
            rec_id = self.cfg.get("recruit_role_id")
            combined = list(set(b_ids + v_ids + ([rec_id] if rec_id else [])))
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
        cfg = load_json(guild.id)

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
        cfg = load_json(guild.id)

        await interaction.response.send_message(
            "Choose a category below to adjust its role ranking hierarchy:",
            view=HierarchyCategorySelectView(guild, cfg),
            ephemeral=True,
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
        for guild in self.bot.guilds:
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

        user_role_ids = {r.id for r in member.roles}

        # 1. CUSTOM PREFIX BYPASS CHECK
        custom_prefix_role_id = cfg.get("custom_prefix_role_id")
        if custom_prefix_role_id and custom_prefix_role_id in user_role_ids:
            return

        prefixes = cfg.get("role_prefixes", {})
        if not prefixes:
            return
        
        def clean_tag(tag: str) -> str:
            clean = tag.strip().strip("[]()")
            return f"[{clean}]"

        elite_ids = cfg.get("elite_role_ids", [])
        staff_ids = cfg.get("staff_role_ids", [])
        rank_ids = cfg.get("rank_role_ids", [])
        recruit_id = cfg.get("recruit_role_id")
        basic_ids = cfg.get("basic_role_ids", [])
        visitor_ids = cfg.get("visitor_role_ids", [])

        # Priority order for Tag Prefixes (Elite > Staff > Rank > Recruit > Basic)
        priority_order = []
        priority_order.extend(staff_ids)
        priority_order.extend(elite_ids)
        priority_order.extend(rank_ids)
        if recruit_id:
            priority_order.append(recruit_id)
        priority_order.extend(basic_ids)
        priority_order.extend(visitor_ids)

        active_prefix = None
        for rid in priority_order:
            if rid in user_role_ids and str(rid) in prefixes:
                active_prefix = prefixes[str(rid)]
                break

        current_nick = member.display_name
        clean_name = re.sub(r"^\[.*?\]\s*|^\(.*?\)\s*", "", current_nick).strip()

        # 2. STRIP LEFTOVER/UNAUTHORIZED OFFICIAL TAGS
        if not active_prefix:
            all_bot_tags = [clean_tag(t) for t in prefixes.values() if t.strip()]
            
            # Check if they have an official tag they no longer qualify for
            has_unauthorized_tag = any(current_nick.startswith(tag + " ") or current_nick == tag for tag in all_bot_tags)
            
            if has_unauthorized_tag:
                target_nick = clean_name[:32]
                if current_nick != target_nick:
                    try:
                        await member.edit(nick=target_nick, reason="Stripped leftover/unauthorized bot prefix")
                        logger.info(f"[RoleManager] 🧹 Stripped leftover/unauthorized tag from {member.display_name}")
                    except discord.HTTPException:
                        pass
            return

        # 3. APPLY VALID TAG
        formatted_prefix = clean_tag(active_prefix)
        target_nick = f"{formatted_prefix} {clean_name}"[:32]

        if current_nick != target_nick:
            try:
                await member.edit(nick=target_nick, reason="Dynamic Role Prefix Sync")
                logger.info(f"[RoleManager] 🏷️ Nickname Updated: '{current_nick}' ➔ '{target_nick}'")
            except discord.Forbidden:
                logger.warning(f"[RoleManager] ⚠️ Lacking permissions to edit nickname for {member.display_name}.")
            except discord.HTTPException:
                pass
            
        def clean_tag(tag: str) -> str:
            clean = tag.strip().strip("[]()")
            return f"[{clean}]"

        formatted_prefix = clean_tag(active_prefix)

        current_nick = member.display_name
        clean_name = re.sub(r"^\[.*?\]\s*|^\(.*?\)\s*", "", current_nick).strip()

        target_nick = f"{formatted_prefix} {clean_name}"[:32]

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
        cfg = load_json(guild.id)

        channel_id = cfg.get("dashboard_channel_id")
        message_id = cfg.get("dashboard_message_id")

        if not channel_id:
            return

        channel = guild.get_channel(channel_id)
        if not channel:
            try:
                channel = await guild.fetch_channel(channel_id)
            except (discord.NotFound, discord.HTTPException, discord.ClientException):
                return

        if not isinstance(channel, discord.TextChannel):
            return

        prefixes = cfg.get("role_prefixes", {})

        def clean_tag_display(tag: str | None) -> str:
            if not tag:
                return "None"
            clean = tag.strip().strip("[]()")
            return f"[{clean}]"

        basic_ids = cfg.get("basic_role_ids", [])
        visitor_ids = cfg.get("visitor_role_ids", [])
        combined_basic_ids = list(dict.fromkeys(basic_ids + visitor_ids))

        basic_roles = [guild.get_role(rid) for rid in combined_basic_ids if guild.get_role(rid)]
        basic_formatted = [
            f"{r.mention} [`{clean_tag_display(prefixes.get(str(r.id)))}`]" for r in basic_roles
        ]
        basic_str = ", ".join(basic_formatted) if basic_formatted else "`None Configured`"

        recruit_role = guild.get_role(cfg.get("recruit_role_id", 0))
        recruit_pfx = clean_tag_display(prefixes.get(str(recruit_role.id))) if recruit_role else None
        recruit_str = (
            f"{recruit_role.mention} [`{recruit_pfx or 'None'}`]"
            if recruit_role
            else "`Not Configured`"
        )

        member_role = guild.get_role(cfg.get("member_role_id", 0))
        member_str = member_role.mention if member_role else "the required Member role"

        custom_prefix_role = guild.get_role(cfg.get("custom_prefix_role_id", 0))
        custom_prefix_str = custom_prefix_role.mention if custom_prefix_role else "`Not Configured`"
        
        elite_ids = cfg.get("elite_role_ids", [])
        elite_roles = [guild.get_role(rid) for rid in elite_ids if guild.get_role(rid)]
        elite_formatted = [
            f"{r.mention} [`{clean_tag_display(prefixes.get(str(r.id)))}`]" for r in elite_roles
        ]
        elite_str = " ➔ ".join(elite_formatted) if elite_formatted else "`None Configured`"

        staff_ids = cfg.get("staff_role_ids", [])
        staff_roles = [guild.get_role(rid) for rid in staff_ids if guild.get_role(rid)]
        staff_formatted = [
            f"{r.mention} [`{clean_tag_display(prefixes.get(str(r.id)))}`]" for r in staff_roles
        ]
        staff_str = " ➔ ".join(staff_formatted) if staff_formatted else "`None Configured`"

        rank_ids = cfg.get("rank_role_ids", [])
        rank_roles = [guild.get_role(rid) for rid in rank_ids if guild.get_role(rid)]
        ranks_formatted = [
            f"{r.mention} [`{clean_tag_display(prefixes.get(str(r.id)))}`]" for r in rank_roles
        ]
        ranks_str = " ➔ ".join(ranks_formatted) if ranks_formatted else "`None Configured`"

        bot_member = guild.me
        problematic_roles = []
        all_configured_roles = elite_roles + staff_roles + rank_roles + ([recruit_role] if recruit_role else []) + ([member_role] if member_role else [])
        
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
                "This dashboard details how basic roles, elite/staff permissions, "
                "member progression, rank restrictions, and nickname tags operate automatically."
                f"{hierarchy_warning}"
            ),
            color=discord.Color.red() if problematic_roles else discord.Color.gold(),
            timestamp=discord.utils.utcnow(),
        )

        embed.add_field(
            name="🆔 Configured Server Roles & Prefixes",
            value=(
                f"• **Basic & Visitor Roles:** {basic_str}\n"
                f"• **Recruit Role:** {recruit_str}\n"
                f"• **Member Requirement:** {member_str}\n"
                f"• **Custom Prefix Bypass:** {custom_prefix_str}\n"
                f"• **Staff Hierarchy (Highest ➔ Lowest):** {staff_str}\n"
                f"• **Elite Roles (Highest ➔ Lowest):** {elite_str}\n"
                f"• **Rank Hierarchy (Highest ➔ Lowest):** {ranks_str}"
            ),
            inline=False,
        )

        embed.add_field(
            name="🛠️ Staff Instructions: How to Change Server Roles",
            value=(
                "Admins can configure or re-link any category of roles anytime using `/setup_rank_roles`:\n"
                "• `elite_roles` — List top-tier prestigious roles (e.g. `@Vanguard @Elder`).\n"
                "• `staff_roles` — List all staff roles (e.g. `@Moderator @Admin`).\n"
                "• `rank_roles` — List all dynamic ranks (e.g. `@Rank I @Rank II ...`).\n"
                "• `basic_roles` — Pass space or comma separated mentions (e.g. `@Visitor @Friend`).\n"
                "• `recruit_role` — Select the role granted upon passing application.\n"
                "• `member_role` — Select the required full member role (e.g. `@20R Member`).\n"
                "• `custom_prefix_role` — Select the role that allows custom nicknames without bot override.\n\n"
                "*Note: You can update a single option while leaving others omitted—the bot will retain your existing settings!*"
            ),
            inline=False,
        )

        embed.add_field(
            name="🚫 Incompatible & Mutually Exclusive Rules",
            value=(
                f"• **Basic Roles Exclusivity:** {basic_rules_text}\n"
                f"• **Member Requirement:** Holding any Rank, Staff, or Elite role strictly enforces having {member_str}.\n"
                f"• **Recruit Exclusivity:** Holding {recruit_str if recruit_role else 'Recruit'} strictly strips {member_str}, Rank, Staff, and Elite roles.\n"
                f"• **Multiple Ranks:** Rank roles are mutually exclusive. Progression maintains a single active rank.\n"
                f"• **Custom Prefix Override:** Members holding {custom_prefix_str} bypass prefix enforcement."
            ),
            inline=False,
        )

        embed.add_field(
            name="🏷️ Nickname Tag Priority",
            value=(
                "Prefixes follow a strict priority order: **Staff > Elite > Rank > Recruit > Basic**.\n"
                "Staff can click the button below to assign custom nickname tags to any of these role categories."
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
        save_json(guild.id, cfg)

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role):
        """Scorched-earth cleanup if a configured role is deleted from Discord Settings."""
        cfg = load_json(role.guild.id)

        modified = False
        for key in ["basic_role_ids", "visitor_role_ids", "elite_role_ids", "staff_role_ids", "rank_role_ids"]:
            if role.id in cfg.get(key, []):
                cfg[key].remove(role.id)
                modified = True

        if cfg.get("recruit_role_id") == role.id:
            cfg["recruit_role_id"] = None
            modified = True

        if cfg.get("member_role_id") == role.id:
            cfg["member_role_id"] = None
            modified = True

        if cfg.get("custom_prefix_role_id") == role.id:
            cfg["custom_prefix_role_id"] = None
            modified = True

        if str(role.id) in cfg.get("role_prefixes", {}):
            cfg["role_prefixes"].pop(str(role.id), None)
            modified = True

        if modified:
            logger.info(f"[RoleManager] 🧹 Cleaned up deleted role '{role.name}' ({role.id}) from guild '{role.guild.name}' config.")
            save_json(role.guild.id, cfg)
            await self.update_rank_dashboard(role.guild)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        """Event-Driven Hierarchy Listener following the Flowchart logic strictly."""
        if after.bot or after.id in self._processing_users:
            return

        guild = after.guild
        cfg = load_json(guild.id)

        # -----------------------------------------------------------------
        # NICKNAME PROTECTION / OVERRIDE BRANCH
        # -----------------------------------------------------------------
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
            visitor_role_ids = cfg.get("visitor_role_ids", [])
            all_basic_ids = set(basic_role_ids + visitor_role_ids)

            recruit_role_id = cfg.get("recruit_role_id")
            member_role_id = cfg.get("member_role_id")

            elite_role_ids = cfg.get("elite_role_ids", [])
            staff_role_ids = cfg.get("staff_role_ids", [])
            rank_role_ids = cfg.get("rank_role_ids", [])

            added_role_ids = {r.id for r in (set(after.roles) - set(before.roles))}
            removed_role_ids = {r.id for r in (set(before.roles) - set(after.roles))}
            user_role_ids = {r.id for r in after.roles}

            roles_to_remove = []
            roles_to_add = []

            # Identify specific role gained/lost events
            gained_basic = next((r for r in after.roles if r.id in added_role_ids and r.id in all_basic_ids), None)
            gained_recruit = next((r for r in after.roles if r.id in added_role_ids and r.id == recruit_role_id), None)
            gained_rank = next((r for r in after.roles if r.id in added_role_ids and r.id in rank_role_ids), None)
            gained_staff = next((r for r in after.roles if r.id in added_role_ids and r.id in staff_role_ids), None)
            gained_elite = next((r for r in after.roles if r.id in added_role_ids and r.id in elite_role_ids), None)
            gained_member = next((r for r in after.roles if r.id in added_role_ids and r.id == member_role_id), None)
            lost_member = member_role_id in removed_role_ids if member_role_id else False

            # -----------------------------------------------------------------
            # BRANCH 1: GAINED BASIC ROLE (Visitor, Friend, Stranger)
            # -----------------------------------------------------------------
            if gained_basic:
                for r in after.roles:
                    if r.id in rank_role_ids or r.id in staff_role_ids or r.id in elite_role_ids or r.id == member_role_id or r.id == recruit_role_id:
                        if r not in roles_to_remove:
                            roles_to_remove.append(r)

                for r in after.roles:
                    if r.id in all_basic_ids and r.id != gained_basic.id:
                        if r not in roles_to_remove:
                            roles_to_remove.append(r)

            # -----------------------------------------------------------------
            # BRANCH 2: GAINED RECRUIT ROLE
            # -----------------------------------------------------------------
            elif gained_recruit:
                for r in after.roles:
                    if r.id in rank_role_ids or r.id in staff_role_ids or r.id in elite_role_ids or r.id == member_role_id or r.id in all_basic_ids:
                        if r.id != recruit_role_id and r not in roles_to_remove:
                            roles_to_remove.append(r)

            # -----------------------------------------------------------------
            # BRANCH 3: GAINED RANK ROLE
            # -----------------------------------------------------------------
            elif gained_rank:
                for r in after.roles:
                    if r.id in all_basic_ids or r.id == recruit_role_id:
                        if r not in roles_to_remove:
                            roles_to_remove.append(r)

                if member_role_id and member_role_id not in user_role_ids:
                    m_role = guild.get_role(member_role_id)
                    if m_role and m_role not in roles_to_add:
                        roles_to_add.append(m_role)

                for r in after.roles:
                    if r.id in rank_role_ids and r.id != gained_rank.id:
                        if r not in roles_to_remove:
                            roles_to_remove.append(r)

            # -----------------------------------------------------------------
            # BRANCH 4: GAINED STAFF ROLE
            # -----------------------------------------------------------------
            elif gained_staff:
                for r in after.roles:
                    if r.id in all_basic_ids or r.id == recruit_role_id:
                        if r not in roles_to_remove:
                            roles_to_remove.append(r)

                if member_role_id and member_role_id not in user_role_ids:
                    m_role = guild.get_role(member_role_id)
                    if m_role and m_role not in roles_to_add:
                        roles_to_add.append(m_role)

                for r in after.roles:
                    if r.id in staff_role_ids and r.id != gained_staff.id:
                        if r not in roles_to_remove:
                            roles_to_remove.append(r)
                            
            # -----------------------------------------------------------------
            # BRANCH 5: GAINED ELITE ROLE (Vanguard / Elder)
            # -----------------------------------------------------------------
            elif gained_elite:
                for r in after.roles:
                    if r.id in all_basic_ids or r.id == recruit_role_id:
                        if r not in roles_to_remove:
                            roles_to_remove.append(r)

                if member_role_id and member_role_id not in user_role_ids:
                    m_role = guild.get_role(member_role_id)
                    if m_role and m_role not in roles_to_add:
                        roles_to_add.append(m_role)

                for r in after.roles:
                    if r.id in elite_role_ids and r.id != gained_elite.id:
                        if r not in roles_to_remove:
                            roles_to_remove.append(r)

            # -----------------------------------------------------------------
            # BRANCH 6: GAINED MEMBER ROLE MANUALLY
            # -----------------------------------------------------------------
            elif gained_member:
                for r in after.roles:
                    if r.id in all_basic_ids or r.id == recruit_role_id:
                        if r not in roles_to_remove:
                            roles_to_remove.append(r)

            # -----------------------------------------------------------------
            # BRANCH 7: MEMBER STATUS REMOVED (Full Demotion to Visitor)
            # -----------------------------------------------------------------
            elif lost_member:
                for r in after.roles:
                    if r.id in rank_role_ids or r.id in staff_role_ids or r.id in elite_role_ids or r.id in all_basic_ids or r.id == recruit_role_id:
                        if r not in roles_to_remove:
                            roles_to_remove.append(r)

                visitor_id = list(visitor_role_ids)[0] if visitor_role_ids else None
                if visitor_id:
                    v_role = guild.get_role(visitor_id)
                    if v_role and v_role not in roles_to_add:
                        roles_to_add.append(v_role)

            # -----------------------------------------------------------------
            # FALLBACK RECONCILIATION
            # -----------------------------------------------------------------
            else:
                active_ranks = [r for r in after.roles if r.id in rank_role_ids]
                active_staff = [r for r in after.roles if r.id in staff_role_ids]
                active_elite = [r for r in after.roles if r.id in elite_role_ids]
                has_member_role = member_role_id and member_role_id in user_role_ids

                if active_ranks or active_staff or active_elite or has_member_role:
                    for r in after.roles:
                        if (r.id in all_basic_ids or r.id == recruit_role_id) and r not in roles_to_remove:
                            roles_to_remove.append(r)

            # -----------------------------------------------------------------
            # EXECUTION
            # -----------------------------------------------------------------
            if roles_to_add:
                add_names = ", ".join([f"'{r.name}'" for r in roles_to_add])
                try:
                    await after.add_roles(*roles_to_add, reason="Role Flowchart Auto-Assignment")
                    logger.info(f"[RoleManager] ✅ Granted role(s) [{add_names}] to {after.display_name}.")
                except discord.HTTPException as e:
                    logger.error(f"[RoleManager] ❌ Failed to add roles [{add_names}] to {after.display_name}: {e}")

            if roles_to_remove:
                remove_names = ", ".join([f"'{r.name}'" for r in roles_to_remove])
                try:
                    await after.remove_roles(*roles_to_remove, reason="Role Flowchart Exclusivity")
                    logger.info(f"[RoleManager] 🧹 Stripped role(s) [{remove_names}] from {after.display_name}.")
                except discord.HTTPException as e:
                    logger.error(f"[RoleManager] ❌ Failed to remove roles [{remove_names}] from {after.display_name}: {e}")

            fresh_member = guild.get_member(after.id) or after
            await self._update_member_nickname_prefix(fresh_member, cfg)

        finally:
            self._processing_users.remove(after.id)


    @app_commands.command(
        name="mass_visitor_reset",
        description="One-time cleanup: Demotes stuck Members, current Recruits, and unassigned users to Visitor.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def mass_visitor_reset(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        cfg = load_json(guild.id)

        visitor_ids = cfg.get("visitor_role_ids", [])
        if not visitor_ids:
            return await interaction.followup.send("❌ No Visitor role configured! Please run `/setup_rank_roles` first.", ephemeral=True)
            
        target_visitor_role = guild.get_role(visitor_ids[0])
        if not target_visitor_role:
            return await interaction.followup.send("❌ The configured Visitor role could not be found in the server.", ephemeral=True)

        member_role_id = cfg.get("member_role_id")
        recruit_role_id = cfg.get("recruit_role_id")
        rank_ids = cfg.get("rank_role_ids", [])
        basic_ids = cfg.get("basic_role_ids", [])
        
        # Combine all mapped roles to check for completely unassigned users
        all_mapped_ids = set(visitor_ids + basic_ids + rank_ids + cfg.get("staff_role_ids", []) + cfg.get("elite_role_ids", []))
        if member_role_id: all_mapped_ids.add(member_role_id)
        if recruit_role_id: all_mapped_ids.add(recruit_role_id)

        changes = 0
        logger.info(f"[MassReset] 🚀 Starting mass reset in guild: '{guild.name}'")
        
        for member in guild.members:
            if member.bot: 
                continue
            
            user_roles = {r.id for r in member.roles}
            needs_visitor = False
            roles_to_remove = []
            log_reason = ""

            has_member = member_role_id in user_roles
            has_recruit = recruit_role_id in user_roles
            has_rank = any(r_id in user_roles for r_id in rank_ids)
            
            # Condition 1: Has 20R Member, but NO Recruit and NO Rank
            if has_member and not has_recruit and not has_rank:
                needs_visitor = True
                roles_to_remove.append(guild.get_role(member_role_id))
                log_reason = "Stuck Member (Has 20R Member, but no Recruit/Rank)"
                
            # Condition 2: Is a current Recruit
            elif has_recruit:
                needs_visitor = True
                roles_to_remove.append(guild.get_role(recruit_role_id))
                if has_member: 
                    roles_to_remove.append(guild.get_role(member_role_id))
                log_reason = "Current Recruit"
                    
            # Condition 3: Missing basic roles, member, recruit, ranks, or staff (completely unassigned)
            elif not any(r_id in user_roles for r_id in all_mapped_ids):
                needs_visitor = True
                log_reason = "Completely Unassigned (Missing all basic/staff/rank roles)"
                
            # Execution for this member
            if needs_visitor:
                roles_to_add = [target_visitor_role] if target_visitor_role.id not in user_roles else []
                valid_removals = [r for r in roles_to_remove if r is not None]
                
                if roles_to_add or valid_removals:
                    try:
                        add_names = [r.name for r in roles_to_add]
                        remove_names = [r.name for r in valid_removals]
                        
                        # Logging exactly what it is doing to this specific user
                        logger.info(
                            f"[MassReset] 🛠️ Processing {member.display_name} ({member.id}) | "
                            f"Reason: {log_reason} | Adding: {add_names} | Removing: {remove_names}"
                        )
                        
                        if roles_to_add:
                            await member.add_roles(*roles_to_add, reason=f"Mass Visitor Reset: {log_reason}")
                        if valid_removals:
                            await member.remove_roles(*valid_removals, reason=f"Mass Visitor Reset: {log_reason}")
                        
                        changes += 1
                        await asyncio.sleep(0.05)
                    except discord.HTTPException as e:
                        logger.error(f"[MassReset] ❌ Failed on {member.display_name}: {e}")
        
        logger.info(f"[MassReset] ✅ Completed in guild '{guild.name}'. Total members updated: {changes}")
        await interaction.followup.send(
            f"✅ **Mass Reset Complete!** Successfully processed and demoted **{changes}** members. Check your console logs for a detailed breakdown of exactly who was changed and why.",
            ephemeral=True
        )

    @app_commands.command(
        name="force_rank_audit",
        description="Run a full server audit to enforce rank rules and nickname tags across all members.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def force_rank_audit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        cfg = load_json(guild.id)

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
        description="Configure dynamic lists of Basic, Recruit, Member, Custom Prefix, Elite, Staff, and Rank roles.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_rank_roles(
        self,
        interaction: discord.Interaction,
        member_role: discord.Role = None,
        recruit_role: discord.Role = None,
        custom_prefix_role: discord.Role = None,
        basic_roles: str = None,
        elite_roles: str = None,
        staff_roles: str = None,
        rank_roles: str = None,
    ):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild

        guild_cfg = load_json(guild.id)

        if member_role:
            guild_cfg["member_role_id"] = member_role.id
        if recruit_role:
            guild_cfg["recruit_role_id"] = recruit_role.id
        if custom_prefix_role:
            guild_cfg["custom_prefix_role_id"] = custom_prefix_role.id

        if basic_roles is not None:
            parsed_basic_ids = parse_role_ids(guild, basic_roles)
            if member_role and member_role.id in parsed_basic_ids:
                parsed_basic_ids.remove(member_role.id)
            guild_cfg["basic_role_ids"] = parsed_basic_ids

        if elite_roles is not None:
            parsed_elite_ids = parse_role_ids(guild, elite_roles)
            guild_cfg["elite_role_ids"] = parsed_elite_ids

        if staff_roles is not None:
            parsed_staff_ids = parse_role_ids(guild, staff_roles)
            guild_cfg["staff_role_ids"] = parsed_staff_ids

        if rank_roles is not None:
            parsed_rank_ids = parse_role_ids(guild, rank_roles)
            guild_cfg["rank_role_ids"] = parsed_rank_ids

        save_json(guild.id, guild_cfg)

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
        c_str = (
            f"<@&{guild_cfg.get('custom_prefix_role_id')}>"
            if guild_cfg.get("custom_prefix_role_id")
            else "`Not Set`"
        )
        e_str = (
            ", ".join([f"<@&{rid}>" for rid in guild_cfg.get("elite_role_ids", [])])
            if guild_cfg.get("elite_role_ids")
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
            f"• **Custom Prefix Bypass Role:** {c_str}\n"
            f"• **Elite Roles:** {e_str}\n"
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

        guild_cfg = load_json(interaction.guild_id)

        guild_cfg["dashboard_channel_id"] = target_channel.id
        guild_cfg["dashboard_message_id"] = None
        save_json(interaction.guild_id, guild_cfg)

        await self.update_rank_dashboard(interaction.guild)

        await interaction.followup.send(
            f"✅ Rank Dashboard active in {target_channel.mention}!", ephemeral=True
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(RoleManager(bot))