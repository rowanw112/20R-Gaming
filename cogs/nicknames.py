import logging
import re
import discord
from discord.ext import commands

logger = logging.getLogger(__name__)

ROLE_IDS = {
    # Production Role IDs
    "PROD": {
        "DL": 605857237407236097,
        "DA": 611442318305787914,
        "TL": 531857333664481280,
        "TS": 772257836654002176,
        "IN": 622594532793516072,
        "VG": 599080943755591695,
        "V": 880225976376758353,
        "IV": 880225940901359646,
        "III": 880225900174667837,
        "II": 876573539749216287,
        "I": 876573382521540678,
        "R": 588816938202038292,
        "MEMBER": 531857621603450881,
        "STRANGER": 588931614017323058,
    },
    # Test Server Role IDs
    "TEST": {
        "MANAGER": 1533542768532787230,
        "DL": 1533542677440630994,
        "DA": 1533542663360483429,
        "TL": 1533542640245805198,
        "TS": 1533542613238415632,
        "IN": 1533542587703758948,
        "CO": 1533544439878779101,
        "VG": 1533542912325976144,
        "VII": 1533542353955061780,
        "VI": 1533542351773896754,
        "V": 1533542349593120848,
        "IV": 1533542346623418429,
        "III": 1533542344207630507,
        "II": 1533542343355924590,
        "I": 1533542289731752087,
        "R": 1533544382270144794,
        "MEMBER": 1533544055743709264,
        "STRANGER": 1533544079156314313,
    },
}

# Staff Roles Hierarchy (Highest to Lowest)
STAFF_HIERARCHY = [
    (ROLE_IDS["TEST"]["MANAGER"], "[M]"),
    (ROLE_IDS["TEST"]["DL"], "[DL]"),
    (ROLE_IDS["PROD"]["DL"], "[DL]"),
    (ROLE_IDS["TEST"]["DA"], "[DA]"),
    (ROLE_IDS["PROD"]["DA"], "[DA]"),
    (ROLE_IDS["TEST"]["TL"], "[TL]"),
    (ROLE_IDS["PROD"]["TL"], "[TL]"),
    (ROLE_IDS["TEST"]["TS"], "[TS]"),
    (ROLE_IDS["PROD"]["TS"], "[TS]"),
    (ROLE_IDS["TEST"]["IN"], "[IN]"),
    (ROLE_IDS["PROD"]["IN"], "[IN]"),
    (ROLE_IDS["TEST"]["CO"], "[CO]"),
]

# Non-Staff Member Activity Ranks Hierarchy (Highest to Lowest)
RANK_HIERARCHY = [
    (ROLE_IDS["TEST"]["VII"], "[Ⅶ]"),
    (ROLE_IDS["TEST"]["VI"], "[Ⅵ]"),
    (ROLE_IDS["TEST"]["V"], "[Ⅴ]"),
    (ROLE_IDS["PROD"]["V"], "[Ⅴ]"),
    (ROLE_IDS["TEST"]["IV"], "[ⅠⅤ]"),
    (ROLE_IDS["PROD"]["IV"], "[ⅠⅤ]"),
    (ROLE_IDS["TEST"]["III"], "[ⅠⅠⅠ]"),
    (ROLE_IDS["PROD"]["III"], "[ⅠⅠⅠ]"),
    (ROLE_IDS["TEST"]["II"], "[ⅠⅠ]"),
    (ROLE_IDS["PROD"]["II"], "[ⅠⅠ]"),
    (ROLE_IDS["TEST"]["I"], "[Ⅰ]"),
    (ROLE_IDS["PROD"]["I"], "[Ⅰ]"),
    (ROLE_IDS["TEST"]["R"], "[R]"),
    (ROLE_IDS["PROD"]["R"], "[R]"),
]

VG_ROLE_IDS = {ROLE_IDS["TEST"]["VG"], ROLE_IDS["PROD"]["VG"]}
RECRUIT_ROLE_IDS = {ROLE_IDS["TEST"]["R"], ROLE_IDS["PROD"]["R"]}
ALL_MEMBER_ROLE_IDS = {ROLE_IDS["PROD"]["MEMBER"], ROLE_IDS["TEST"]["MEMBER"]}
ALL_STRANGER_ROLE_IDS = {ROLE_IDS["PROD"]["STRANGER"], ROLE_IDS["TEST"]["STRANGER"]}

ALL_STAFF_ROLE_IDS = {item[0] for item in STAFF_HIERARCHY}
ALL_RANK_ROLE_IDS = {item[0] for item in RANK_HIERARCHY}

PREFIX_PATTERN = re.compile(
    r"^\[(M|DL|DA|L|TL|TS|IN|CO|VG|R|Ⅰ|ⅠⅠ|ⅠⅠⅠ|ⅠⅤ|Ⅴ|Ⅵ|Ⅶ)\]\s*", re.IGNORECASE
)


class NicknameSync(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def clean_name(self, display_name: str) -> str:
        """Strips all managed prefixes from the front of a display name."""
        cleaned = display_name
        while True:
            new_cleaned = PREFIX_PATTERN.sub("", cleaned)
            if new_cleaned == cleaned:
                break
            cleaned = new_cleaned
        return cleaned.strip()

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        before_roles = set(before.roles)
        after_roles = set(after.roles)

        if before_roles == after_roles:
            return

        added_roles = after_roles - before_roles
        added_role_ids = {r.id for r in added_roles}
        user_role_ids = {r.id for r in after.roles}

        roles_to_remove = []
        roles_to_add = []

        # 1. Handle Staff Role changes (Only strip OTHER staff roles when a new staff role is added)
        new_staff_added = [r_id for r_id in added_role_ids if r_id in ALL_STAFF_ROLE_IDS]
        if new_staff_added:
            target_staff_id = new_staff_added[0]
            for role in after.roles:
                if role.id in ALL_STAFF_ROLE_IDS and role.id != target_staff_id:
                    roles_to_remove.append(role)

        # 2. Handle Activity Rank changes (Only strip OTHER activity ranks when Statbot/Admin assigns a new rank)
        new_rank_added = [r_id for r_id in added_role_ids if r_id in ALL_RANK_ROLE_IDS]
        if new_rank_added:
            target_rank_id = new_rank_added[0]
            for role in after.roles:
                if role.id in ALL_RANK_ROLE_IDS and role.id != target_rank_id:
                    roles_to_remove.append(role)

        # Calculate user's active roles after scheduled removals
        current_user_roles = user_role_ids - {r.id for r in roles_to_remove}

        # 3. Determine Display Prefix Priority: Staff > Vanguard > Activity Rank
        active_prefix = ""

        # Priority 1: Staff Rank Prefix
        for role_id, prefix in STAFF_HIERARCHY:
            if role_id in current_user_roles:
                active_prefix = prefix
                break

        # Priority 2: Vanguard Prefix (if no Staff role)
        if not active_prefix:
            if any(vg_id in current_user_roles for vg_id in VG_ROLE_IDS):
                active_prefix = "[VG]"

        # Priority 3: Activity Rank Prefix (if no Staff or Vanguard role)
        if not active_prefix:
            for role_id, prefix in RANK_HIERARCHY:
                if role_id in current_user_roles:
                    active_prefix = prefix
                    break

        # 4. Synchronize Member vs Stranger Roles
        has_any_managed_role = bool(current_user_roles & (ALL_STAFF_ROLE_IDS | ALL_RANK_ROLE_IDS | VG_ROLE_IDS))

        if has_any_managed_role:
            is_only_recruit = (
                any(r_id in current_user_roles for r_id in RECRUIT_ROLE_IDS) and 
                not any(r_id in current_user_roles for r_id in (ALL_STAFF_ROLE_IDS | ALL_RANK_ROLE_IDS | VG_ROLE_IDS) - RECRUIT_ROLE_IDS)
            )

            if not is_only_recruit:
                for member_id in ALL_MEMBER_ROLE_IDS:
                    m_role = after.guild.get_role(member_id)
                    if m_role and m_role not in after.roles:
                        roles_to_add.append(m_role)

                for stranger_id in ALL_STRANGER_ROLE_IDS:
                    s_role = after.guild.get_role(stranger_id)
                    if s_role and s_role in after.roles:
                        roles_to_remove.append(s_role)

        # Batch execute role updates
        if roles_to_add:
            try:
                await after.add_roles(*roles_to_add, reason="Rank Sync: Added Member role")
            except discord.HTTPException as e:
                logger.error(f"Failed to add roles for {after.display_name}: {e}")

        if roles_to_remove:
            try:
                await after.remove_roles(*roles_to_remove, reason="Rank Sync: Cleared conflicting roles")
            except discord.HTTPException as e:
                logger.error(f"Failed to remove roles for {after.display_name}: {e}")

        # 5. Apply Nickname Prefix
        base_name = self.clean_name(after.display_name)
        new_nickname = f"{active_prefix} {base_name}".strip() if active_prefix else base_name

        if after.display_name == new_nickname:
            return

        try:
            await after.edit(nick=new_nickname, reason="Rank Prefix Auto-Sync")
            logger.info(f"✅ Updated nickname for {after.name}: '{after.display_name}' ➔ '{new_nickname}'")
        except discord.Forbidden:
            logger.warning(f"⚠️ Cannot update nickname for {after.display_name} (Insufficient permissions or server owner).")
        except discord.HTTPException as e:
            logger.error(f"❌ HTTP Error updating nickname for {after.display_name}: {e}")


async def setup(bot: commands.Bot):
    await bot.add_cog(NicknameSync(bot))