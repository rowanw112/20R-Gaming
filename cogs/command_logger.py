import logging
import discord
from discord.ext import commands

logger = logging.getLogger(__name__)


class CommandLogger(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def _format_options(self, options: list) -> str:
        """Formats slash command parameters into a clean string for the terminal."""
        if not options:
            return "None"
        formatted = []
        for opt in options:
            name = opt.get("name", "param")
            val = opt.get("value", "N/A")
            formatted.append(f"{name}:{val}")
        return ", ".join(formatted)

    @commands.Cog.listener()
    async def on_app_command_completion(
        self, interaction: discord.Interaction, command: discord.app_commands.Command
    ):
        """Prints successful slash command executions to the terminal."""
        user = interaction.user
        guild = interaction.guild.name if interaction.guild else "Direct Message"
        channel = interaction.channel.name if interaction.channel else "DM"

        options = interaction.data.get("options", []) if interaction.data else []
        params = self._format_options(options)

        print(
            f"[COMMAND] ✅ User: {user} ({user.id}) | "
            f"Guild: '{guild}' | Channel: #{channel} | "
            f"Command: /{command.name} | Parameters: [{params}]"
        )

    @commands.Cog.listener()
    async def on_app_command_error(
        self, interaction: discord.Interaction, error: discord.app_commands.AppCommandError
    ):
        """Prints failed slash command executions to the terminal."""
        user = interaction.user
        guild = interaction.guild.name if interaction.guild else "Direct Message"
        channel = interaction.channel.name if interaction.channel else "DM"
        cmd_name = interaction.command.name if interaction.command else "Unknown"

        options = interaction.data.get("options", []) if interaction.data else []
        params = self._format_options(options)

        print(
            f"[COMMAND] ❌ User: {user} ({user.id}) | "
            f"Guild: '{guild}' | Channel: #{channel} | "
            f"Command: /{cmd_name} | Parameters: [{params}] | Error: {error}"
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(CommandLogger(bot))