import logging
import discord
import asyncio
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger(__name__)


def get_role_category_mapping(guild: discord.Guild) -> tuple[dict[int, discord.Role], set[int]]:
    """
    Scans guild roles from top to bottom based on position.
    Returns:
      - role_to_category: Map of normal_role_id -> category_divider_role
      - category_role_ids: Set of all role IDs that act as category headers (starts with '───')
    """
    sorted_roles = sorted(guild.roles, key=lambda r: r.position, reverse=True)
    role_to_category = {}
    category_role_ids = set()
    current_category_role = None

    for role in sorted_roles:
        clean_name = role.name.strip()
        if clean_name.startswith("───") or "───" in clean_name:
            current_category_role = role
            category_role_ids.add(role.id)
        elif current_category_role and not role.is_default():
            role_to_category[role.id] = current_category_role

    return role_to_category, category_role_ids


class CategoryRoleSync(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._processing_members = set()

    @commands.Cog.listener()
    async def on_ready(self):
        """Runs an initial audit across all members (including bots) when the bot starts up."""
        logger.info("[CategoryRoleSync] 🔄 Running startup category divider audit...")
        for guild in self.bot.guilds:
            for member in guild.members:
                try:
                    await self.sync_member_categories(member)
                    # Yield to the event loop so the bot doesn't freeze on large servers
                    await asyncio.sleep(0.1)
                except Exception as e:
                    logger.error(f"[CategorySync] Startup error for {member.display_name}: {e}")
        logger.info("[CategoryRoleSync] ✅ Startup category divider audit complete!")

    async def sync_member_categories(self, member: discord.Member):
        """Scans member/bot roles and adds/removes category header roles dynamically."""
        if not member.guild or member.id in self._processing_members:
            return

        self._processing_members.add(member.id)

        try:
            guild = member.guild
            role_to_category, category_role_ids = get_role_category_mapping(guild)

            if not category_role_ids:
                return

            # Determine which category headers the user/bot SHOULD hold
            needed_category_role_ids = set()
            for role in member.roles:
                if role.id in role_to_category:
                    needed_category_role_ids.add(role_to_category[role.id].id)

            # Determine which category headers the user/bot CURRENTLY holds
            current_category_role_ids = {r.id for r in member.roles if r.id in category_role_ids}

            # Calculate differences
            to_add_ids = needed_category_role_ids - current_category_role_ids
            to_remove_ids = current_category_role_ids - needed_category_role_ids

            roles_to_add = [guild.get_role(rid) for rid in to_add_ids if guild.get_role(rid)]
            roles_to_remove = [guild.get_role(rid) for rid in to_remove_ids if guild.get_role(rid)]

            # Apply Additions
            if roles_to_add:
                try:
                    await member.add_roles(*roles_to_add, reason="Auto-assigned Category Header Role(s)")
                    added_names = ", ".join([r.name for r in roles_to_add])
                    logger.info(f"[CategorySync] Added category header(s) '{added_names}' to {member.display_name}")
                except discord.HTTPException as e:
                    logger.error(f"[CategorySync] Failed to add category roles to {member.display_name}: {e}")

            # Apply Removals
            if roles_to_remove:
                try:
                    await member.remove_roles(*roles_to_remove, reason="Auto-removed unused Category Header Role(s)")
                    removed_names = ", ".join([r.name for r in roles_to_remove])
                    logger.info(f"[CategorySync] Removed category header(s) '{removed_names}' from {member.display_name}")
                except discord.HTTPException as e:
                    logger.error(f"[CategorySync] Failed to remove category roles from {member.display_name}: {e}")

        finally:
            self._processing_members.remove(member.id)

    # -------------------------------------------------------------------------
    # REAL-TIME LISTENERS
    # -------------------------------------------------------------------------
    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        """Fires ONLY when roles actually change (ignoring nickname edits)."""
        before_roles = set(before.roles)
        after_roles = set(after.roles)

        if before_roles != after_roles:
            await self.sync_member_categories(after)

    # -------------------------------------------------------------------------
    # MANAGEMENT COMMANDS
    # -------------------------------------------------------------------------
    @app_commands.command(
        name="sync_category_roles",
        description="Force a full audit across all server members and bots to sync category divider roles.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def sync_category_roles(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild

        synced_count = 0
        for member in guild.members:
            await self.sync_member_categories(member)
            synced_count += 1

        await interaction.followup.send(
            f"✅ **Category Role Audit Complete!** Re-synced category headers for `{synced_count}` members and bots.",
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(CategoryRoleSync(bot))