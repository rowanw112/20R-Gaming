import asyncio
import json
import logging
import os
import discord
from discord import app_commands
from discord.ext import commands

from core.database import (
    load_division_records,
    load_casual_records,
    load_legacy_division_records,
)

logger = logging.getLogger(__name__)

LOGO_PATH = "data/images/20r_logo.png"


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


# -------------------------------------------------------------------------
# DYNAMIC ROLE TOGGLE BUTTON & VIEW
# -------------------------------------------------------------------------
class RoleToggleButton(discord.ui.Button):
    def __init__(
        self,
        label: str,
        role_id: int,
        emoji_str: str | None = None,
        style: discord.ButtonStyle = discord.ButtonStyle.secondary,
    ):
        custom_id = f"react_role_toggle_{role_id}"
        super().__init__(
            label=label[:80],
            style=style,
            custom_id=custom_id,
            emoji=emoji_str if emoji_str else None,
        )
        self.role_id = role_id

    async def callback(self, interaction: discord.Interaction):
        # Acknowledges button interaction silently without posting messages or popups
        await interaction.response.defer()
        
        guild = interaction.guild
        if not guild:
            return

        role = guild.get_role(self.role_id)
        if not role:
            return

        user = interaction.user
        if role in user.roles:
            try:
                await user.remove_roles(role, reason="React for Roles Button Toggle")
            except discord.HTTPException as e:
                logger.error(f"Failed to remove role {role.name}: {e}")
        else:
            try:
                await user.add_roles(role, reason="React for Roles Button Toggle")
            except discord.HTTPException as e:
                logger.error(f"Failed to assign role {role.name}: {e}")


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
        self.bot.add_view(DynamicRoleView())

    @commands.Cog.listener()
    async def on_ready(self):
        logger.info(
            "[ReactForRoles] 🔄 Refreshing Reaction Role Embeds across guilds..."
        )
        for guild in self.bot.guilds:
            await self.update_react_embeds(guild)

    async def update_react_embeds(self, guild: discord.Guild):
        """Scans hub divisions, legacy divisions, and casual games to update button embeds."""
        guild_cfg = load_json(guild.id)
        channel_id = guild_cfg.get("react_roles_channel_id")

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

        division_records = load_division_records(guild.id)
        legacy_records = load_legacy_division_records(guild.id)
        casual_records = load_casual_records(guild.id)

        divisions_list = []
        casuals_list = []
        processed_role_ids = set()

        def build_item_entry(info: dict):
            public_role_id = info.get("public_role_id") or info.get("game_role_id") or info.get("role_id")
            role = guild.get_role(public_role_id) if public_role_id else None
            if not role:
                return None

            game_name = info.get("game_name") or role.name
            button_name = info.get("button_name")

            # STRICT BUTTON LOGIC: Use button_name if set, otherwise game_name ONLY (short_name ignored)
            label = button_name if button_name else game_name

            # 1. Check if an explicit emoji override was saved in the database
            emoji_obj = info.get("emoji")

            # 2. If not, automatically grab the icon/emoji directly from the Discord role settings
            if not emoji_obj and role.display_icon:
                if isinstance(role.display_icon, str):
                    # It is a standard unicode emoji
                    emoji_obj = role.display_icon
                else:
                    # Discord converted the custom server emoji into an image Asset.
                    # We will do a smart search through the server's emojis to find the matching one!
                    clean_name = label.replace(" ", "").replace("-", "").lower()
                    for e in guild.emojis:
                        if e.name.lower() in clean_name or clean_name in e.name.lower():
                            emoji_obj = e
                            break

            return {
                "name": label,
                "role_id": role.id,
                "emoji": emoji_obj,
            }

        # 1. Process Active Hub Divisions
        if isinstance(division_records, list):
            for info in division_records:
                entry = build_item_entry(info)
                if entry and entry["role_id"] not in processed_role_ids:
                    divisions_list.append(entry)
                    processed_role_ids.add(entry["role_id"])

        # 2. Process Legacy Divisions
        if isinstance(legacy_records, list):
            for info in legacy_records:
                entry = build_item_entry(info)
                if entry and entry["role_id"] not in processed_role_ids:
                    divisions_list.append(entry)
                    processed_role_ids.add(entry["role_id"])

        # 3. Process Casual Games
        if isinstance(casual_records, list):
            for info in casual_records:
                entry = build_item_entry(info)
                if entry and entry["role_id"] not in processed_role_ids:
                    casuals_list.append(entry)
                    processed_role_ids.add(entry["role_id"])

        # Deploy Gaming Divisions Embeds
        div_messages = guild_cfg.get("react_div_message_ids", [])
        new_div_msg_ids = await self._deploy_section_embeds(
            guild=guild,
            channel=channel,
            existing_msg_ids=div_messages,
            items=divisions_list,
            title="🎮 Gaming Divisions",
            description="Click the corresponding button(s) below to gain full access to any of our main gaming divisions.",
            color=discord.Color.red(),
            button_style=discord.ButtonStyle.danger,
        )

        # Deploy Casual Games Embeds
        casual_messages = guild_cfg.get("react_casual_message_ids", [])
        new_casual_msg_ids = await self._deploy_section_embeds(
            guild=guild,
            channel=channel,
            existing_msg_ids=casual_messages,
            items=casuals_list,
            title="🕹️ Casual Games & Gaming Groups",
            description="These are games we are interested in expanding into full divisions. Click below to join their channels!",
            color=discord.Color.blurple(),
            button_style=discord.ButtonStyle.primary,
        )

        guild_cfg["react_div_message_ids"] = new_div_msg_ids
        guild_cfg["react_casual_message_ids"] = new_casual_msg_ids
        save_json(guild.id, guild_cfg)

    async def _deploy_section_embeds(
        self,
        guild: discord.Guild,
        channel: discord.TextChannel,
        existing_msg_ids: list[int],
        items: list[dict],
        title: str,
        description: str,
        color: discord.Color,
        button_style: discord.ButtonStyle,
    ) -> list[int]:
        chunked_items = [items[i : i + 25] for i in range(0, len(items), 25)]
        if not chunked_items:
            chunked_items = [[]]

        new_msg_ids = []

        for idx, chunk in enumerate(chunked_items):
            page_title = (
                f"{title} (Part {idx + 1})" if len(chunked_items) > 1 else title
            )
            embed = discord.Embed(
                title=page_title,
                description=description,
                color=color,
                timestamp=discord.utils.utcnow(),
            )

            logo_filename = "20r_logo.png"
            has_logo = os.path.exists(LOGO_PATH)

            if has_logo:
                embed.set_author(name="20R Gaming", icon_url=f"attachment://{logo_filename}")
            else:
                logger.warning(f"[ReactForRoles] ⚠️ Logo file not found at path: {os.path.abspath(LOGO_PATH)}")

            embed.set_footer(text="20R Reaction Roles System • Last Updated")

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

            msg_id = (
                existing_msg_ids[idx] if idx < len(existing_msg_ids) else None
            )
            posted_msg = None

            if msg_id:
                try:
                    posted_msg = await channel.fetch_message(msg_id)
                    if has_logo:
                        file = discord.File(LOGO_PATH, filename=logo_filename)
                        await posted_msg.edit(embed=embed, view=view, attachments=[file])
                    else:
                        await posted_msg.edit(embed=embed, view=view)
                except (discord.NotFound, discord.HTTPException):
                    posted_msg = None

            if not posted_msg:
                if has_logo:
                    file = discord.File(LOGO_PATH, filename=logo_filename)
                    posted_msg = await channel.send(file=file, embed=embed, view=view)
                else:
                    posted_msg = await channel.send(embed=embed, view=view)

                try:
                    await posted_msg.pin(reason="React for Roles Section")
                    await asyncio.sleep(0.5)
                    async for sys_msg in channel.history(limit=5):
                        if (
                            sys_msg.type == discord.MessageType.pins_add
                            and sys_msg.author == self.bot.user
                        ):
                            await sys_msg.delete()
                            break
                except (discord.Forbidden, discord.HTTPException):
                    pass

            new_msg_ids.append(posted_msg.id)

        if len(existing_msg_ids) > len(new_msg_ids):
            for old_id in existing_msg_ids[len(new_msg_ids) :]:
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
        description="Set the channel to maintain live Gaming Division & Casual reaction role button embeds.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def set_react_channel(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel | None = None,
    ):
        await interaction.response.defer(ephemeral=True)
        target_channel = channel or interaction.channel

        guild_cfg = load_json(interaction.guild_id)

        guild_cfg["react_roles_channel_id"] = target_channel.id
        guild_cfg["react_div_message_ids"] = []
        guild_cfg["react_casual_message_ids"] = []
        save_json(interaction.guild_id, guild_cfg)

        await self.update_react_embeds(interaction.guild)

        await interaction.followup.send(
            f"✅ React for Roles Dashboard set up in {target_channel.mention}!",
            ephemeral=True,
        )

    @app_commands.command(
        name="refresh_react_roles",
        description="Manually trigger an auto-update for all reaction role button embeds.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def refresh_react_roles(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await self.update_react_embeds(interaction.guild)
        await interaction.followup.send(
            "✅ Reaction Role embeds refreshed!", ephemeral=True
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(ReactForRoles(bot))