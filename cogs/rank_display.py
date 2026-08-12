import json
import logging
import os
import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger(__name__)

CONFIG_FILE = "data/rank_system_config.json"
LOGO_PATH = "data/images/20r_logo.png"


def load_config() -> dict:
    if not os.path.exists(CONFIG_FILE):
        return {}
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}


def save_config(data: dict):
    if "/" in CONFIG_FILE:
        os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)


class RankDisplay(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        """Refreshes all public rank info embeds across guilds on startup."""
        logger.info("[RankDisplay] 🔄 Refreshing public rank hierarchy embeds...")
        for guild in self.bot.guilds:
            try:
                await self.update_public_display(guild)
            except Exception as e:
                logger.error(f"[RankDisplay] Error updating public display for '{guild.name}': {e}")
        logger.info("[RankDisplay] ✅ Public rank hierarchy embeds refreshed!")

    async def update_public_display(self, guild: discord.Guild):
        """Generates and maintains the public member-facing Rank & Staff hierarchy embed."""
        configs = load_config()
        cfg = configs.get(str(guild.id), {})

        channel_id = cfg.get("public_display_channel_id")
        message_id = cfg.get("public_display_message_id")

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

        def clean_tag(tag: str | None) -> str:
            if not tag:
                return ""
            clean = tag.strip().strip("[]()")
            return f" `[{clean}]`" if clean else ""

        # 1. Staff Hierarchy
        staff_ids = cfg.get("staff_role_ids", [])
        staff_lines = []
        for idx, rid in enumerate(staff_ids):
            role = guild.get_role(rid)
            if role:
                pfx_str = clean_tag(prefixes.get(str(rid)))
                staff_lines.append(f"**{idx + 1}.** {role.mention}{pfx_str}")

        staff_formatted = "\n".join(staff_lines) if staff_lines else "*No staff roles configured.*"

        # 2. Rank Progression Hierarchy (Ranks I-VII + Recruit at bottom)
        rank_ids = cfg.get("rank_role_ids", [])
        rank_lines = []
        for idx, rid in enumerate(rank_ids):
            role = guild.get_role(rid)
            if role:
                pfx_str = clean_tag(prefixes.get(str(rid)))
                rank_lines.append(f"**{idx + 1}.** {role.mention}{pfx_str}")

        recruit_role = guild.get_role(cfg.get("recruit_role_id", 0))
        if recruit_role:
            rec_pfx = clean_tag(prefixes.get(str(recruit_role.id)))
            rank_lines.append(f"**{len(rank_lines) + 1}.** {recruit_role.mention}{rec_pfx} *(Our newest recruits!)*")

        ranks_formatted = "\n".join(rank_lines) if rank_lines else "*No rank progression roles configured.*"

        # 3. Community Membership & Guest Roles
        member_role = guild.get_role(cfg.get("member_role_id", 0))
        member_str = (
            f"{member_role.mention} — *Our core members, who wear our tag with pride and honor!*"
            if member_role
            else "*Not Set*"
        )

        basic_ids = cfg.get("basic_role_ids", [])
        visitor_ids = cfg.get("visitor_role_ids", [])
        combined_basic_ids = list(dict.fromkeys(basic_ids + visitor_ids))  # Preserves configured hierarchy order

        basic_roles = [guild.get_role(rid) for rid in combined_basic_ids if guild.get_role(rid)]

        # Determine presentation order (we want it Lowest -> Highest left to right)
        if not basic_ids:
            # Fallback if unconfigured
            def sort_guest_key(role: discord.Role) -> int:
                name = role.name.lower()
                if "stranger" in name: return 0
                if "visitor" in name: return 1
                if "friend" in name: return 2
                return 3
            basic_roles.sort(key=sort_guest_key)
        else:
            # Config saves Highest -> Lowest, so we reverse it to display Lowest -> Highest
            basic_roles.reverse()

        basic_formatted = []
        for r in basic_roles:
            pfx_str = clean_tag(prefixes.get(str(r.id)))
            basic_formatted.append(f"{r.mention}{pfx_str}")

        basic_str = ", ".join(basic_formatted) if basic_formatted else "*None Configured*"

        # Build Embed
        embed = discord.Embed(
            title="🎖️ 20R Server Ranks & Role Hierarchy",
            description=(
                "Welcome to the official 20R role structure overview! "
                "Below you can see our staff structure, rank progression path, and community access tiers."
            ),
            color=discord.Color.gold(),
            timestamp=discord.utils.utcnow(),
        )

        has_logo = os.path.exists(LOGO_PATH)
        logo_filename = "20r_logo.png"

        if has_logo:
            embed.set_author(name="20R Gaming System Overview", icon_url=f"attachment://{logo_filename}")

        embed.add_field(
            name="🛡️ Staff Hierarchy (Highest ➔ Lowest)",
            value=staff_formatted,
            inline=False,
        )

        embed.add_field(
            name="🏆 Rank Progression Hierarchy (Highest ➔ Lowest)",
            value=ranks_formatted,
            inline=False,
        )

        embed.add_field(
            name="🔰 Community Membership & Guest Roles",
            value=(
                f"• **Official Member Status:** {member_str}\n"
                f"• **Visitor & Guest Roles:** {basic_str}"
            ),
            inline=False,
        )

        embed.add_field(
            name="🏷️ Dynamic Nickname Tags",
            value=(
                "Our members wear their ranks and tags to shine on the battlefield and represent 20R with pride! "
                "Your role tag is automatically prepended to your server nickname as you progress through our ranks."
            ),
            inline=False,
        )

        embed.set_footer(text=f"20R Gaming • {guild.name} Hierarchy Overview")

        # Edit existing or post new message
        if message_id:
            try:
                msg = await channel.fetch_message(message_id)
                if has_logo:
                    file = discord.File(LOGO_PATH, filename=logo_filename)
                    await msg.edit(embed=embed, attachments=[file])
                else:
                    await msg.edit(embed=embed)
                return
            except (discord.NotFound, discord.HTTPException):
                pass

        try:
            if has_logo:
                file = discord.File(LOGO_PATH, filename=logo_filename)
                posted_msg = await channel.send(file=file, embed=embed)
            else:
                posted_msg = await channel.send(embed=embed)

            try:
                await posted_msg.pin(reason="Public Rank Hierarchy Display")
            except (discord.Forbidden, discord.HTTPException):
                pass

            cfg["public_display_channel_id"] = channel.id
            cfg["public_display_message_id"] = posted_msg.id
            configs[str(guild.id)] = cfg
            save_config(configs)

        except (discord.Forbidden, discord.HTTPException) as e:
            logger.error(f"❌ Error posting Public Rank Display in #{channel.name}: {e}")

    @app_commands.command(
        name="set_rank_display_channel",
        description="Set the public text channel to post and maintain the live Rank & Staff Hierarchy embed.",
    )
    @app_commands.checks.has_permissions(manage_roles=True)
    @app_commands.describe(
        channel="Select the public channel for the hierarchy embed (Defaults to current channel)"
    )
    async def set_rank_display_channel(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel | None = None,
    ):
        await interaction.response.defer(ephemeral=True)
        target_channel = channel or interaction.channel

        if not isinstance(target_channel, discord.TextChannel):
            await interaction.followup.send(
                "❌ Target channel must be a standard text channel!", ephemeral=True
            )
            return

        configs = load_config()
        guild_cfg = configs.get(str(interaction.guild_id), {})

        guild_cfg["public_display_channel_id"] = target_channel.id
        guild_cfg["public_display_message_id"] = None
        configs[str(interaction.guild_id)] = guild_cfg
        save_config(configs)

        await self.update_public_display(interaction.guild)

        await interaction.followup.send(
            f"✅ Public Rank & Staff Hierarchy display posted in {target_channel.mention}!",
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(RankDisplay(bot))