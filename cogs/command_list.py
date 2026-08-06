import asyncio
import logging
import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger(__name__)


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

    async def refresh_command_list_channel(
        self, guild: discord.Guild, channel: discord.TextChannel
    ):
        """In-place update of command documentation embeds without purging the channel."""
        # 1. Collect all slash commands
        all_commands: list[tuple[str, app_commands.Command]] = []

        for cmd in self.bot.tree.get_commands():
            if isinstance(cmd, app_commands.Group):
                for sub_cmd in cmd.commands:
                    all_commands.append((f"/{cmd.name} {sub_cmd.name}", sub_cmd))
            elif isinstance(cmd, app_commands.Command):
                all_commands.append((f"/{cmd.name}", cmd))

        all_commands.sort(key=lambda x: x[0])

        if not all_commands:
            return

        # 2. Build Embed Chunks (15 commands per embed page)
        chunk_size = 15
        embeds = []

        for i in range(0, len(all_commands), chunk_size):
            chunk = all_commands[i : i + chunk_size]

            embed = discord.Embed(
                title="🤖 Bot Command Directory & Permissions",
                description="List of all available slash commands and their access requirements.",
                color=discord.Color.blue(),
                timestamp=discord.utils.utcnow(),
            )

            for cmd_name, cmd_obj in chunk:
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

            embeds.append(embed)

        for idx, emb in enumerate(embeds):
            emb.set_footer(
                text=f"Page {idx + 1} of {len(embeds)} • {guild.name}"
            )

        # 3. Fetch existing bot messages (oldest first to preserve page order)
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
                # Edit existing message
                try:
                    await existing_messages[idx].edit(embed=embed)
                except (discord.NotFound, discord.HTTPException):
                    await channel.send(embed=embed)
            else:
                # Post new message if total pages increased
                await channel.send(embed=embed)

        # 5. Remove surplus messages if total pages decreased
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