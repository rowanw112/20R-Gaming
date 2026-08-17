import logging
import discord
from discord import app_commands
from discord.ext import commands

from core.database import (
    load_division_records,
    load_legacy_division_records,
    save_legacy_division_records,
    load_role_sync_config,
    save_role_sync_config,
    load_casual_records,
    save_casual_records,
)
from cogs.application_manager import load_rank_config

logger = logging.getLogger(__name__)


class DivisionRoleSync(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        """Runs a full member audit on startup/reload and refreshes the Mapping Dashboard."""
        logger.info("[DivisionRoleSync] 🔄 Running startup division role audit & dashboard refresh...")
        for guild in self.bot.guilds:
            try:
                await self.update_sync_dashboard(guild)
            except Exception as e:
                logger.error(f"[RoleSync] Dashboard refresh error for '{guild.name}': {e}")

            for member in guild.members:
                if not member.bot:
                    try:
                        await self.sync_member_division_roles(member)
                    except Exception as e:
                        logger.error(f"[RoleSync] Startup audit error for {member.display_name}: {e}")
        logger.info("[DivisionRoleSync] ✅ Startup division role audit & dashboard refresh complete!")

    async def update_sync_dashboard(self, guild: discord.Guild):
        """Creates or updates the live Division Sync & Mapping Dashboard embed in the configured channel."""
        cfg = load_role_sync_config(guild.id)
        guild_cfg = cfg.get(str(guild.id), {})

        if isinstance(guild_cfg, int):  # Migration check for old config format
            guild_cfg = {"channel_id": guild_cfg, "message_id": None}

        chan_id = guild_cfg.get("channel_id")
        msg_id = guild_cfg.get("message_id")

        if not chan_id:
            return

        channel = guild.get_channel(chan_id)
        if not channel:
            try:
                channel = await guild.fetch_channel(chan_id)
            except (discord.NotFound, discord.HTTPException):
                return

        if not isinstance(channel, discord.TextChannel):
            return

        hub_records = load_division_records(guild.id) or []
        legacy_records = load_legacy_division_records(guild.id) or []

        embed = discord.Embed(
            title="🗺️ Division Mapping & Auto-Sync Dashboard",
            description=(
                "**📌 How Division Access Works:**\n"
                "• **🔓 Open (Auto-Synced):** When a user holds a `Recruit` or `Member` rank role and picks up a Public Game Role, the bot automatically grants them the matching Division Role. Removing the Public Role will automatically remove the Division Role.\n"
                "• **🔒 Restrictive (Application Only):** Public Game Roles remain open to everyone, but Division Roles are locked and require a separate application process. The bot will **never** auto-grant restrictive roles."
            ),
            color=discord.Color.gold(),
            timestamp=discord.utils.utcnow(),
        )

        def format_record(r: dict) -> str:
            pub = guild.get_role(r.get("game_role_id"))
            div = guild.get_role(r.get("member_role_id"))
            pub_str = pub.mention if pub else "`Unknown`"
            div_str = div.mention if div else "`Unknown`"
            return f"• **{r.get('game_name')}**: {pub_str} ➔ {div_str}"

        # 1. Active Hub Divisions
        hub_open = [format_record(r) for r in hub_records if not r.get("is_restrictive", False)]
        hub_restrictive = [format_record(r) for r in hub_records if r.get("is_restrictive", False)]

        embed.add_field(
            name="🛡️ Active Hub Divisions — 🔓 Open (Auto-Synced)",
            value="\n".join(hub_open) if hub_open else "*None registered.*",
            inline=False,
        )

        embed.add_field(
            name="🛡️ Active Hub Divisions — 🔒 Restrictive (Application Only)",
            value="\n".join(hub_restrictive) if hub_restrictive else "*None registered.*",
            inline=False,
        )

        # 2. Legacy Divisions
        legacy_open = [format_record(r) for r in legacy_records if not r.get("is_restrictive", False)]
        legacy_restrictive = [format_record(r) for r in legacy_records if r.get("is_restrictive", False)]

        embed.add_field(
            name="📜 Legacy Divisions — 🔓 Open (Auto-Synced)",
            value="\n".join(legacy_open) if legacy_open else "*None registered.*",
            inline=False,
        )

        embed.add_field(
            name="📜 Legacy Divisions — 🔒 Restrictive (Application Only)",
            value="\n".join(legacy_restrictive) if legacy_restrictive else "*None registered.*",
            inline=False,
        )

        embed.set_footer(text="Auto-updates live when divisions are created, updated, or removed.")

        # Update existing message or post a new pinned dashboard
        if msg_id:
            try:
                msg = await channel.fetch_message(msg_id)
                await msg.edit(embed=embed)
                return
            except (discord.NotFound, discord.HTTPException):
                pass

        try:
            posted_msg = await channel.send(embed=embed)
            try:
                await posted_msg.pin(reason="Live Division Sync Mapping Dashboard")
            except (discord.Forbidden, discord.HTTPException):
                pass

            guild_cfg["channel_id"] = channel.id
            guild_cfg["message_id"] = posted_msg.id
            cfg[str(guild.id)] = guild_cfg
            save_role_sync_config(guild.id, cfg)

        except (discord.Forbidden, discord.HTTPException) as e:
            logger.error(f"❌ Error posting Sync Dashboard in #{channel.name}: {e}")

    def _is_member_or_recruit(self, member: discord.Member, rank_cfg: dict) -> bool:
        """Checks if a user holds a Recruit, Member, or higher Rank role."""
        recruit_role_id = rank_cfg.get("recruit_role_id")
        member_role_id = rank_cfg.get("member_role_id")
        rank_role_ids = set(rank_cfg.get("rank_role_ids", []))

        if recruit_role_id:
            rank_role_ids.add(recruit_role_id)
        if member_role_id:
            rank_role_ids.add(member_role_id)

        user_role_ids = {r.id for r in member.roles}
        return bool(user_role_ids.intersection(rank_role_ids))

    async def sync_member_division_roles(self, member: discord.Member):
        """Scans member roles against both New Hub and Legacy Division records (Adds OR Removes)."""
        if member.bot:
            return

        guild = member.guild
        rank_cfg = load_rank_config(guild.id)

        is_official = self._is_member_or_recruit(member, rank_cfg)

        hub_records = load_division_records(guild.id) or []
        legacy_records = load_legacy_division_records(guild.id) or []
        all_records = hub_records + legacy_records

        if not all_records:
            return

        user_role_ids = {r.id for r in member.roles}
        roles_to_add = []
        roles_to_remove = []

        for record in all_records:
            game_role_id = record.get("game_role_id")
            div_role_id = record.get("member_role_id")

            if not game_role_id or not div_role_id:
                continue

            has_game_role = game_role_id in user_role_ids
            has_div_role = div_role_id in user_role_ids
            is_restrictive = record.get("is_restrictive", False)

            # 1. ADD ROLE LOGIC (Only for Open Divisions if user has official rank and game role)
            if is_official and not is_restrictive:
                if has_game_role and not has_div_role:
                    div_role = guild.get_role(div_role_id)
                    if div_role:
                        roles_to_add.append(div_role)

            # 2. REMOVE ROLE LOGIC (If user lost the public game role OR lost official rank status)
            if has_div_role and (not has_game_role or not is_official):
                div_role = guild.get_role(div_role_id)
                if div_role:
                    roles_to_remove.append(div_role)

        # Apply Additions
        if roles_to_add:
            try:
                await member.add_roles(*roles_to_add, reason="Auto-synced Division Role(s) Granted")
                role_names = ", ".join([r.name for r in roles_to_add])
                logger.info(f"[RoleSync] Auto-assigned division role(s) '{role_names}' to {member.display_name}")
            except discord.HTTPException as e:
                logger.error(f"[RoleSync] Failed to add division roles to {member.display_name}: {e}")

        # Apply Removals
        if roles_to_remove:
            try:
                await member.remove_roles(*roles_to_remove, reason="Auto-synced Division Role(s) Removed (Lost Public Role/Rank)")
                role_names = ", ".join([r.name for r in roles_to_remove])
                logger.info(f"[RoleSync] Auto-removed division role(s) '{role_names}' from {member.display_name}")
            except discord.HTTPException as e:
                logger.error(f"[RoleSync] Failed to remove division roles from {member.display_name}: {e}")

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        """Fires whenever roles change on a user."""
        if getattr(self.bot, "is_passive", False): return # 🛑 Passive Mode Check
        
        before_role_ids = {r.id for r in before.roles}
        after_role_ids = {r.id for r in after.roles}

        if before_role_ids != after_role_ids:
            await self.sync_member_division_roles(after)

    # -------------------------------------------------------------------------
    # CONFIG & LEGACY MANAGEMENT COMMANDS
    # -------------------------------------------------------------------------
    @app_commands.command(
        name="set_role_sync_log_channel",
        description="Set the channel where the live Division Mapping Dashboard is displayed.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def set_role_sync_log_channel(
        self, interaction: discord.Interaction, log_channel: discord.TextChannel | None = None
    ):
        await interaction.response.defer(ephemeral=True)
        target_channel = log_channel or interaction.channel

        if not isinstance(target_channel, discord.TextChannel):
            await interaction.followup.send(
                "❌ Mapping dashboard must be placed inside a standard text channel.",
                ephemeral=True,
            )
            return

        cfg = load_role_sync_config(interaction.guild.id)
        guild_cfg = cfg.get(str(interaction.guild.id), {})
        if isinstance(guild_cfg, int):
            guild_cfg = {"channel_id": guild_cfg, "message_id": None}

        old_msg_id = guild_cfg.get("message_id")
        old_chan_id = guild_cfg.get("channel_id")

        if old_chan_id and old_msg_id:
            try:
                old_chan = interaction.guild.get_channel(old_chan_id)
                if isinstance(old_chan, discord.TextChannel):
                    old_msg = await old_chan.fetch_message(old_msg_id)
                    await old_msg.delete()
            except (discord.NotFound, discord.HTTPException):
                pass

        guild_cfg["channel_id"] = target_channel.id
        guild_cfg["message_id"] = None
        cfg[str(interaction.guild.id)] = guild_cfg
        save_role_sync_config(interaction.guild.id, cfg)

        await self.update_sync_dashboard(interaction.guild)

        await interaction.followup.send(
            f"✅ Division Mapping Dashboard set to {target_channel.mention}!",
            ephemeral=True,
        )

    @app_commands.command(
        name="add_legacy_division",
        description="Register an existing legacy division into the auto-role sync system.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def add_legacy_division(
        self,
        interaction: discord.Interaction,
        division_name: str,
        public_role: discord.Role,
        division_role: discord.Role,
        is_restrictive: bool = False,
    ):
        await interaction.response.defer(ephemeral=True)

        records = load_legacy_division_records(interaction.guild.id)

        existing = next((r for r in records if r.get("member_role_id") == division_role.id), None)
        if existing:
            existing["game_role_id"] = public_role.id
            existing["is_restrictive"] = is_restrictive
            existing["game_name"] = division_name
            msg = f"🔄 Updated existing legacy record for **{division_name}**."
        else:
            records.append({
                "game_name": division_name,
                "game_role_id": public_role.id,
                "member_role_id": division_role.id,
                "is_restrictive": is_restrictive,
            })
            msg = f"✅ Registered new legacy division **{division_name}**."

        save_legacy_division_records(interaction.guild.id, records)
        await self.update_sync_dashboard(interaction.guild)

        status_type = "🔒 Restrictive (Application Only)" if is_restrictive else "🔓 Open (Auto-Synced)"

        embed = discord.Embed(title="📜 Legacy Division Registered", color=discord.Color.blue())
        embed.add_field(name="Division Name", value=division_name, inline=False)
        embed.add_field(name="Public Role", value=public_role.mention, inline=True)
        embed.add_field(name="Division Role", value=division_role.mention, inline=True)
        embed.add_field(name="Access Mode", value=status_type, inline=False)

        await interaction.followup.send(content=msg, embed=embed, ephemeral=True)

    @app_commands.command(
        name="list_legacy_divisions",
        description="List all registered legacy divisions.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def list_legacy_divisions(self, interaction: discord.Interaction):
        records = load_legacy_division_records(interaction.guild.id)
        if not records:
            await interaction.response.send_message("❌ No legacy divisions are currently registered.", ephemeral=True)
            return

        embed = discord.Embed(title="📜 Registered Legacy Divisions", color=discord.Color.gold())
        for r in records:
            pub = interaction.guild.get_role(r.get("game_role_id"))
            div = interaction.guild.get_role(r.get("member_role_id"))
            mode = "🔒 Restrictive" if r.get("is_restrictive") else "🔓 Open"

            embed.add_field(
                name=f"🎮 {r.get('game_name')}",
                value=f"• **Public:** {pub.mention if pub else '`Unknown`'}\n"
                      f"• **Division:** {div.mention if div else '`Unknown`'}\n"
                      f"• **Status:** {mode}",
                inline=False,
            )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="add_legacy_casual",
        description="Register an existing legacy casual game into the reaction roles dashboard.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(
        game_name="The name of the casual game (Required)",
        casual_role="The existing role for this casual game (Required)",
        button_name="Custom button label for reaction role embed (Optional)",
    )
    async def add_legacy_casual(
        self,
        interaction: discord.Interaction,
        game_name: str,
        casual_role: discord.Role,
        button_name: str = None,
    ):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild

        casual_records = load_casual_records(guild.id)
        
        # Check if this role is already registered
        existing = next((c for c in casual_records if c.get("role_id") == casual_role.id), None)
        
        # Helper to format the name properly (capitalizes first letters, keeps acronyms)
        def format_game_name(text: str) -> str:
            if not text: return ""
            return " ".join([w if w.isupper() else w.capitalize() for w in text.strip().split()])

        clean_game = format_game_name(game_name)
        clean_button = format_game_name(button_name) if button_name else None

        if existing:
            existing["game_name"] = clean_game
            existing["button_name"] = clean_button
            msg = f"🔄 Updated existing legacy casual record for **{clean_game}**."
        else:
            casual_records.append({
                "game_name": clean_game,
                "button_name": clean_button,
                "role_id": casual_role.id,
                "thread_id": None,  # Explicitly None to tell the bot this has no private thread
                "is_casual": True,
            })
            msg = f"✅ Registered new legacy casual game **{clean_game}**."

        save_casual_records(guild.id, casual_records)

        # Force the Reaction Roles Dashboard to update instantly
        react_cog = self.bot.get_cog("ReactForRoles")
        if react_cog:
            await react_cog.update_react_embeds(guild)

        embed = discord.Embed(title="🕹️ Legacy Casual Game Registered", color=discord.Color.blurple())
        embed.add_field(name="Game Name", value=clean_game, inline=True)
        embed.add_field(name="Role", value=casual_role.mention, inline=True)
        if clean_button:
            embed.add_field(name="Button Name", value=clean_button, inline=False)
            
        embed.set_footer(text="Reaction roles dashboard has been updated automatically.")

        await interaction.followup.send(content=msg, embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(DivisionRoleSync(bot))