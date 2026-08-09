import asyncio
import logging
import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger(__name__)

# Explicit command-level category overrides
COMMAND_CATEGORY_OVERRIDES = {
    # 🛠️ General & Server Setup
    "setup_command_list": "🛠️ General & Server Setup",
    "setup_server_stats": "🛠️ General & Server Setup",
    "ping": "🛠️ General & Server Setup",
    "logs": "🛠️ General & Server Setup",
    "sync": "🛠️ General & Server Setup",
    "reload": "🛠️ General & Server Setup",
    
    # 🎭 Role Management
    "createroles": "🎭 Role Management",
    "createroles_in_category": "🎭 Role Management",
    "set_category_roles": "🎭 Role Management",

    # 📌 Thread Management & Auto-Sync
    "createthreads": "📌 Thread Management & Auto-Sync",
    "link_thread": "📌 Thread Management & Auto-Sync",
    "unlink_thread": "📌 Thread Management & Auto-Sync",
    "force_thread_sync": "📌 Thread Management & Auto-Sync",
    "set_sync_channel": "📌 Thread Management & Auto-Sync",
    "remove_sync_channel": "📌 Thread Management & Auto-Sync",

    # 🛡️ Division & Hub Management
    "createdivision": "🛡️ Division & Hub Management",
    "deletedivision": "🛡️ Division & Hub Management",
    "createdivision_hub": "🛡️ Division & Hub Management",
    "deletedivision_hub": "🛡️ Division & Hub Management",
    "set_hub_defaults": "🛡️ Division & Hub Management",
    "set_hub_dashboard_channel": "🛡️ Division & Hub Management",
}

# Default Cog -> Category mapping if a command isn't explicitly overridden above
COG_CATEGORY_MAP = {
    "ModalDivisionManager": "🛡️ Division & Hub Management",
    "ThreadSync": "📌 Thread Management & Auto-Sync",
    "ThreadKeeper": "📌 Thread Management & Auto-Sync",
    "RoleManager": "🎭 Role Management",
    "ServerStats": "🛠️ General & Server Setup",
    "CommandList": "🛠️ General & Server Setup",
    "AdminUtils": "🛠️ General & Server Setup",
    "Utility": "🛠️ General & Server Setup",
}

# Fixed order for displaying embed categories
CATEGORY_ORDER = [
    "🛡️ Division & Hub Management",
    "📌 Thread Management & Auto-Sync",
    "🎭 Role Management",
    "🛠️ General & Server Setup",
]


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
        # 1. Check explicit command name override
        clean_name = cmd_name.lstrip("/").split()[0]
        if clean_name in COMMAND_CATEGORY_OVERRIDES:
            return COMMAND_CATEGORY_OVERRIDES[clean_name]

        # 2. Check Cog class mapping
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
        # 1. Collect all registered commands
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

        # 2. Build organized Embeds following defined category order
        embeds = []
        ordered_categories = [cat for cat in CATEGORY_ORDER if cat in grouped_commands]
        # Include any extra unlisted categories at the end
        for cat in grouped_commands:
            if cat not in ordered_categories:
                ordered_categories.append(cat)

        total_categories = len(ordered_categories)

        for cat_idx, category_title in enumerate(ordered_categories):
            cmds = grouped_commands[category_title]
            cmds.sort(key=lambda x: x[0])  # Sort commands alphabetically within category

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

        # 3. Fetch existing bot messages (oldest first)
        existing_messages: list[discord.Message] = []
        try:
            async for msg in channel.history(limit=50, oldest_first=True):
                if msg.author == self.bot.user:
                    existing_messages.append(msg)
        except (discord.Forbidden, discord.HTTPException) as e:
            logger.warning(f"Failed to fetch message history in {channel.name}: {e}")

        # 4. In-Place Update Logic
        for idx, embed in enumerate(embeds):
            if idx < len(existing_messages):
                try:
                    await existing_messages[idx].edit(embed=embed)
                except (discord.NotFound, discord.HTTPException):
                    await channel.send(embed=embed)
            else:
                await channel.send(embed=embed)

        # 5. Remove surplus messages if total category embeds decreased
        if len(existing_messages) > len(embeds):
            for surplus_msg in existing_messages[len(embeds) :]:
                try:
                    await surplus_msg.delete()
                except (discord.NotFound, discord.HTTPException):
                    pass

    @commands.Cog.listener()
    async def on_ready(self):
        """Automatically refreshes command list channels across all servers on startup."""
        await self.bot.wait_until_ready()
        await asyncio.sleep(5)

        for guild in self.bot.guilds:
            channel = discord.utils.get(guild.text_channels, name="📜-command-list")
            if channel:
                try:
                    await self.refresh_command_list_channel(guild, channel)
                    logger.info(f"Auto-updated command list in {guild.name}")
                except Exception as e:
                    logger.warning(
                        f"Failed to auto-update command list in {guild.name}: {e}"
                    )

    @app_commands.command(
        name="setup_command_list",
        description="Creates or manually refreshes the command list channel.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_command_list(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild

        channel_name = "📜-command-list"
        channel = discord.utils.get(guild.text_channels, name=channel_name)

        if not channel:
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=False,
                ),
                guild.me: discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    embed_links=True,
                    manage_messages=True,
                ),
            }
            channel = await guild.create_text_channel(
                name=channel_name,
                overwrites=overwrites,
                reason="Command Documentation Channel Setup",
            )

        await self.refresh_command_list_channel(guild, channel)

        await interaction.followup.send(
            f"✅ Command list successfully updated in {channel.mention}!",
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(CommandList(bot))