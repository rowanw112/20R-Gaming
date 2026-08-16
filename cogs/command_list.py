import asyncio
import json
import logging
import os
import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger(__name__)

# Explicit command-level category overrides
COMMAND_CATEGORY_OVERRIDES = {
    # 🛠️ General & Server Setup
    "setup_command_list": "🛠️ General & Server Setup",
    "setup_server_stats": "🛠️ General & Server Setup",
    "setup_bait": "🛠️ General & Server Setup",
    "update_bait_embed": "🛠️ General & Server Setup",
    "logs": "🛠️ General & Server Setup",
    "clear": "🛠️ General & Server Setup",
    
    # 🎭 Role Management
    "create_roles": "🎭 Role Management",
    "sync_category_roles": "🎭 Role Management",
    "setup_rank_roles": "🎭 Role Management",
    "set_rank_dashboard": "🎭 Role Management",
    "force_rank_audit": "🎭 Role Management",
    "update_roles": "🎭 Role Management",
    "update_names": "🎭 Role Management",
    "restrict_mentions": "🎭 Role Management",
    "set_react_channel": "🎭 Role Management",
    "refresh_react_roles": "🎭 Role Management",

    # 📌 Thread Management & Auto-Sync
    "create_threads": "📌 Thread Management & Auto-Sync",
    "link_thread": "📌 Thread Management & Auto-Sync",
    "unlink_thread": "📌 Thread Management & Auto-Sync",
    "toggle_thread_keep_alive": "📌 Thread Management & Auto-Sync",
    "test_thread_bump": "📌 Thread Management & Auto-Sync",

    # 🛡️ Division & Hub Management
    "create_division": "🛡️ Division & Hub Management",
    "delete_division": "🛡️ Division & Hub Management",
    "create_casual_game": "🛡️ Division & Hub Management",
    "create_division_hub": "🛡️ Division & Hub Management",
    "promote_to_division_hub": "🛡️ Division & Hub Management",
    "edit_hub_game": "🛡️ Division & Hub Management",
    "delete_division_hub": "🛡️ Division & Hub Management",
    "list_hub_divisions": "🛡️ Division & Hub Management",
    "set_hub_defaults": "🛡️ Division & Hub Management",
    "set_hub_dashboard_channel": "🛡️ Division & Hub Management",
    "set_role_sync_log_channel": "🛡️ Division & Hub Management",
    "add_legacy_division": "🛡️ Division & Hub Management",
    "list_legacy_divisions": "🛡️ Division & Hub Management",
    "send_app_panel": "🛡️ Division & Hub Management",
}

# Default Cog -> Category mapping fallback
COG_CATEGORY_MAP = {
    "ModalDivisionManager": "🛡️ Division & Hub Management",
    "DivisionManager": "🛡️ Division & Hub Management",
    "DivisionRoleSync": "🛡️ Division & Hub Management",
    "ApplicationManager": "🛡️ Division & Hub Management",
    "ThreadCreator": "📌 Thread Management & Auto-Sync",
    "ThreadSync": "📌 Thread Management & Auto-Sync",
    "ThreadKeeper": "📌 Thread Management & Auto-Sync",
    "RoleManager": "🎭 Role Management",
    "RoleCreator": "🎭 Role Management",
    "CategoryRoleSync": "🎭 Role Management",
    "ReactForRoles": "🎭 Role Management",
    "AdminUtils": "🛠️ General & Server Setup",
    "BotTrap": "🛠️ General & Server Setup",
    "ServerStats": "🛠️ General & Server Setup",
    "CommandList": "🛠️ General & Server Setup",
    "CommandLogger": "🛠️ General & Server Setup",
}

# Fixed order for displaying embed categories
CATEGORY_ORDER = [
    "🛡️ Division & Hub Management",
    "📌 Thread Management & Auto-Sync",
    "🎭 Role Management",
    "🛠️ General & Server Setup",
]


def get_config_path(guild_id: int) -> str:
    path = f"data/{guild_id}"
    os.makedirs(path, exist_ok=True)
    return f"{path}/command_list_config.json"


def load_config(guild_id: int) -> dict:
    filepath = get_config_path(guild_id)
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_config(guild_id: int, data: dict):
    filepath = get_config_path(guild_id)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)


def get_required_permissions(cmd: app_commands.Command) -> str:
    """Inspects command checks and default permissions to list required permissions."""
    req_perms = []

    if cmd.default_permissions:
        for perm, value in cmd.default_permissions:
            if value:
                req_perms.append(perm.replace("_", " ").title())

    for check in cmd.checks:
        if hasattr(check, "__closure__") and check.__closure__:
            for cell in check.__closure__:
                contents = cell.cell_contents
                if isinstance(contents, dict):
                    for perm, val in contents.items():
                        if val and isinstance(perm, str):
                            req_perms.append(perm.replace("_", " ").title())

    if not req_perms:
        return "None (Everyone)"

    unique_perms = sorted(list(set(req_perms)))
    return ", ".join(unique_perms)


class CommandList(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def _determine_category(self, cmd_name: str, cmd_obj: app_commands.Command) -> str:
        """Determines the appropriate category for a command based on name or cog class."""
        clean_name = cmd_name.lstrip("/").split()[0]
        if clean_name in COMMAND_CATEGORY_OVERRIDES:
            return COMMAND_CATEGORY_OVERRIDES[clean_name]

        cog_name = (
            cmd_obj.binding.__class__.__name__
            if getattr(cmd_obj, "binding", None)
            else "General Commands"
        )
        return COG_CATEGORY_MAP.get(cog_name, "🛠️ General & Server Setup")

    async def refresh_command_list_channel(
        self, guild: discord.Guild, channel: discord.TextChannel
    ):
        """In-place update of command documentation embeds organized into streamlined categories."""
        raw_cmds = self.bot.tree.get_commands() + self.bot.tree.get_commands(guild=guild)
        unique_cmds = list({cmd.name: cmd for cmd in raw_cmds}.values())

        grouped_commands: dict[str, list[tuple[str, app_commands.Command]]] = {}

        for cmd in unique_cmds:
            if isinstance(cmd, app_commands.Group):
                for sub_cmd in cmd.commands:
                    full_name = f"/{cmd.name} {sub_cmd.name}"
                    cat = self._determine_category(full_name, sub_cmd)
                    grouped_commands.setdefault(cat, []).append((full_name, sub_cmd))
            elif isinstance(cmd, app_commands.Command):
                full_name = f"/{cmd.name}"
                cat = self._determine_category(full_name, cmd)
                grouped_commands.setdefault(cat, []).append((full_name, cmd))

        if not grouped_commands:
            return

        embeds = []
        ordered_categories = [cat for cat in CATEGORY_ORDER if cat in grouped_commands]
        for cat in grouped_commands:
            if cat not in ordered_categories:
                ordered_categories.append(cat)

        total_categories = len(ordered_categories)

        for cat_idx, category_title in enumerate(ordered_categories):
            cmds = grouped_commands[category_title]
            cmds.sort(key=lambda x: x[0])

            embed = discord.Embed(
                title=f"{category_title}",
                description=f"Commands and permissions under **{category_title}**.",
                color=discord.Color.blue(),
                timestamp=discord.utils.utcnow(),
            )

            for cmd_name, cmd_obj in cmds:
                perms_str = get_required_permissions(cmd_obj)
                desc = cmd_obj.description or "No description provided."

                field_value = (
                    f"**Description:** {desc}\n"
                    f"🔒 **Required Permission:** `{perms_str}`"
                )

                embed.add_field(
                    name=f"`{cmd_name}`",
                    value=field_value,
                    inline=False,
                )

            embed.set_footer(
                text=f"Category {cat_idx + 1} of {total_categories} • {guild.name}"
            )
            embeds.append(embed)

        existing_messages: list[discord.Message] = []
        try:
            async for msg in channel.history(limit=50, oldest_first=True):
                if msg.author == self.bot.user:
                    existing_messages.append(msg)
        except (discord.Forbidden, discord.HTTPException) as e:
            logger.warning(f"Failed to fetch message history in {channel.name}: {e}")

        for idx, embed in enumerate(embeds):
            if idx < len(existing_messages):
                try:
                    await existing_messages[idx].edit(embed=embed)
                except (discord.NotFound, discord.HTTPException):
                    await channel.send(embed=embed)
            else:
                await channel.send(embed=embed)

        if len(existing_messages) > len(embeds):
            for surplus_msg in existing_messages[len(embeds) :]:
                try:
                    await surplus_msg.delete()
                except (discord.NotFound, discord.HTTPException):
                    pass

    @commands.Cog.listener()
    async def on_ready(self):
        """Automatically refreshes command list channels across all configured servers on startup."""
        await self.bot.wait_until_ready()
        await asyncio.sleep(5)

        for guild in self.bot.guilds:
            cfg = load_config(guild.id)
            channel_id = cfg.get("channel_id")
            
            if channel_id:
                channel = guild.get_channel(channel_id)
                if isinstance(channel, discord.TextChannel):
                    try:
                        await self.refresh_command_list_channel(guild, channel)
                        logger.info(f"Auto-updated command list in {guild.name}")
                    except Exception as e:
                        logger.warning(
                            f"Failed to auto-update command list in {guild.name}: {e}"
                        )

    @app_commands.command(
        name="setup_command_list",
        description="Registers a channel to host the automatically updating command documentation.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(channel="The text channel to post the command list in (Defaults to current channel)")
    async def setup_command_list(self, interaction: discord.Interaction, channel: discord.TextChannel = None):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild

        target_channel = channel or interaction.channel
        
        if not isinstance(target_channel, discord.TextChannel):
            await interaction.followup.send(
                "❌ The command list must be placed in a standard text channel.",
                ephemeral=True,
            )
            return
            
        cfg = load_config(guild.id)
        cfg["channel_id"] = target_channel.id
        save_config(guild.id, cfg)

        await self.refresh_command_list_channel(guild, target_channel)

        await interaction.followup.send(
            f"✅ Command list successfully assigned and updated in {target_channel.mention}!",
            ephemeral=True,
        )

async def setup(bot: commands.Bot):
    await bot.add_cog(CommandList(bot))