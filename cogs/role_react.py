import asyncio
import json
import logging
import os
import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger(__name__)

CONFIG_FILE = "data/rank_system_config.json"
DIVISIONS_FILE = "guild_categories.json"  # File where created divisions/casuals are stored


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


# -------------------------------------------------------------------------
# DYNAMIC ROLE TOGGLE BUTTON & VIEW
# -------------------------------------------------------------------------
class RoleToggleButton(discord.ui.Button):
    def __init__(self, label: str, role_id: int, emoji_str: str | None = None, style: discord.ButtonStyle = discord.ButtonStyle.secondary):
        custom_id = f"react_role_toggle_{role_id}"
        super().__init__(
            label=label[:80],  # Ensures label fits on Discord button
            style=style,
            custom_id=custom_id,
            emoji=emoji_str if emoji_str else None,
        )
        self.role_id = role_id

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        role = guild.get_role(self.role_id)

        if not role:
            await interaction.followup.send("❌ This role no longer exists on the server.", ephemeral=True)
            return

        user = interaction.user
        if role in user.roles:
            try:
                await user.remove_roles(role, reason="React for Roles Toggle")
                await interaction.followup.send(f"🔴 Removed role {role.mention}.", ephemeral=True)
            except discord.HTTPException as e:
                await interaction.followup.send(f"❌ Failed to remove role: {e}", ephemeral=True)
        else:
            try:
                await user.add_roles(role, reason="React for Roles Toggle")
                await interaction.followup.send(f"🟢 Granted role {role.mention}!", ephemeral=True)
            except discord.HTTPException as e:
                await interaction.followup.send(f"❌ Failed to assign role: {e}", ephemeral=True)


class DynamicRoleView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)


# -------------------------------------------------------------------------
# COG IMPLEMENTATION
# -------------------------------------------------------------------------
class ReactForRoles(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        # Register persistent buttons across restarts
        self.bot.add_view(DynamicRoleView())

    @commands.Cog.listener()
    async def on_ready(self):
        logger.info("[ReactForRoles] 🔄 Refreshing Reaction Role Embeds across guilds...")
        for guild in self.bot.guilds:
            await self.update_react_embeds(guild)

    async def update_react_embeds(self, guild: discord.Guild):
        """Scans created divisions and casual games and posts/updates paginated role embeds."""
        configs = load_json(CONFIG_FILE)
        guild_cfg = configs.get(str(guild.id), {})
        channel_id = guild_cfg.get("react_roles_channel_id")

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

        divisions_data = load_json(DIVISIONS_FILE).get(str(guild.id), {})
        
        # Collect Divisions & Casuals
        divisions_list = []
        casuals_list = []

        for key, info in divisions_data.items():
            is_casual = info.get("is_casual", False)
            # Public Role for Divisions / Assigned Role for Casuals
            public_role_id = info.get("public_role_id") or info.get("role_id")
            
            # Label priority: short_name -> division_name
            name = info.get("short_name") or info.get("name") or key
            emoji = info.get("emoji")

            if public_role_id and guild.get_role(public_role_id):
                item = {
                    "name": name,
                    "role_id": public_role_id,
                    "emoji": emoji,
                }
                if is_casual:
                    casuals_list.append(item)
                else:
                    divisions_list.append(item)

        # -----------------------------------------------------------------
        # BUILD DIVISIONS EMBEDS & VIEWS (Paginated by 25 buttons max)
        # -----------------------------------------------------------------
        div_messages = guild_cfg.get("react_div_message_ids", [])
        new_div_msg_ids = await self._deploy_section_embeds(
            guild=guild,
            channel=channel,
            existing_msg_ids=div_messages,
            items=divisions_list,
            title="🎮 Gaming Divisions",
            description="Click the corresponding button(s) below to gain full access to any of our main gaming divisions.",
            color=discord.Color.red(),
            button_style=discord.ButtonStyle.danger
        )

        # -----------------------------------------------------------------
        # BUILD CASUAL GAMES EMBEDS & VIEWS (Paginated by 25 buttons max)
        # -----------------------------------------------------------------
        casual_messages = guild_cfg.get("react_casual_message_ids", [])
        new_casual_msg_ids = await self._deploy_section_embeds(
            guild=guild,
            channel=channel,
            existing_msg_ids=casual_messages,
            items=casuals_list,
            title="🕹️ Casual Games & Gaming Groups",
            description="These are games we are interested in expanding into full divisions. Click below to join their channels!",
            color=discord.Color.blurple(),
            button_style=discord.ButtonStyle.primary
        )

        # Save active message IDs
        guild_cfg["react_div_message_ids"] = new_div_msg_ids
        guild_cfg["react_casual_message_ids"] = new_casual_msg_ids
        configs[str(guild.id)] = guild_cfg
        save_json(CONFIG_FILE, configs)

    async def _deploy_section_embeds(
        self,
        guild: discord.Guild,
        channel: discord.TextChannel,
        existing_msg_ids: list[int],
        items: list[dict],
        title: str,
        description: str,
        color: discord.Color,
        button_style: discord.ButtonStyle
    ) -> list[int]:
        """Handles chunking items into blocks of 25 buttons and editing/posting embeds."""
        chunked_items = [items[i:i + 25] for i in range(0, len(items), 25)]
        if not chunked_items:
            chunked_items = [[]]

        new_msg_ids = []

        for idx, chunk in enumerate(chunked_items):
            page_title = f"{title} (Part {idx + 1})" if len(chunked_items) > 1 else title
            embed = discord.Embed(
                title=page_title,
                description=description,
                color=color,
            )
            embed.set_footer(text="20R Reaction Roles System")

            view = DynamicRoleView()
            for item in chunk:
                view.add_item(
                    RoleToggleButton(
                        label=item["name"],
                        role_id=item["role_id"],
                        emoji_str=item["emoji"],
                        style=button_style,
                    )
                )

            # Edit existing message or post a new one
            msg_id = existing_msg_ids[idx] if idx < len(existing_msg_ids) else None
            posted_msg = None

            if msg_id:
                try:
                    posted_msg = await channel.fetch_message(msg_id)
                    await posted_msg.edit(embed=embed, view=view)
                except (discord.NotFound, discord.HTTPException):
                    posted_msg = None

            if not posted_msg:
                posted_msg = await channel.send(embed=embed, view=view)
                try:
                    await posted_msg.pin(reason="React for Roles Section")
                    # Delete the Discord "pinned a message" notification
                    await asyncio.sleep(0.5)
                    async for sys_msg in channel.history(limit=5):
                        if sys_msg.type == discord.MessageType.pins_add and sys_msg.author == self.bot.user:
                            await sys_msg.delete()
                            break
                except (discord.Forbidden, discord.HTTPException):
                    pass

            new_msg_ids.append(posted_msg.id)

        # Clean up leftover messages if total pages decreased
        if len(existing_msg_ids) > len(new_msg_ids):
            for old_id in existing_msg_ids[len(new_msg_ids):]:
                try:
                    old_msg = await channel.fetch_message(old_id)
                    await old_msg.delete()
                except (discord.NotFound, discord.HTTPException):
                    pass

        return new_msg_ids

    # -------------------------------------------------------------------------
    # SLASH COMMANDS
    # -------------------------------------------------------------------------
    @app_commands.command(
        name="set_react_channel",
        description="Set the channel to maintain live Gaming Division & Casual reaction role embeds.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def set_react_channel(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel | None = None,
    ):
        await interaction.response.defer(ephemeral=True)
        target_channel = channel or interaction.channel

        configs = load_json(CONFIG_FILE)
        guild_cfg = configs.get(str(interaction.guild_id), {})

        guild_cfg["react_roles_channel_id"] = target_channel.id
        guild_cfg["react_div_message_ids"] = []
        guild_cfg["react_casual_message_ids"] = []
        configs[str(interaction.guild_id)] = guild_cfg
        save_json(CONFIG_FILE, configs)

        await self.update_react_embeds(interaction.guild)

        await interaction.followup.send(
            f"✅ React for Roles Dashboard set up in {target_channel.mention}!", ephemeral=True
        )

    @app_commands.command(
        name="refresh_react_roles",
        description="Manually trigger an auto-update for all reaction role embeds.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def refresh_react_roles(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await self.update_react_embeds(interaction.guild)
        await interaction.followup.send("✅ Reaction Role embeds refreshed!", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(ReactForRoles(bot))