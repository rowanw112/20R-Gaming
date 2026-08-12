import logging
import discord
from discord import app_commands
from discord.ext import commands

from core.database import (
    load_division_records,
    load_hub_dashboard_config,
    load_hub_defaults,
    load_thread_mappings,
    save_division_records,
    save_hub_dashboard_config,
    save_hub_defaults,
    save_thread_mappings,
    load_casual_records,
    save_casual_records,
    load_legacy_division_records,
    save_legacy_division_records,
)

logger = logging.getLogger(__name__)

COLOR_DIVISION_STAFF = discord.Color(0xE67E22)
COLOR_STAFF = discord.Color(0xF1C40F)
COLOR_MEMBER = discord.Color(0xAD1457)
COLOR_PUBLIC_GAME = discord.Color(0x2ECC71)


def format_game_name(text: str) -> str:
    """Capitalizes the first letter of words while preserving ALL CAPS acronyms (e.g. 'CSGO' -> 'CSGO', 'runescape' -> 'Runescape')."""
    if not text:
        return ""
    words = text.strip().split()
    formatted_words = []
    for word in words:
        if word.isupper():
            formatted_words.append(word)
        else:
            formatted_words.append(word.capitalize())
    return " ".join(formatted_words)


def resolve_channel_label(game_name: str, short_name: str | None) -> str:
    """Uses short_name for Channels & Threads ONLY if game_name exceeds 12 characters."""
    if short_name and len(game_name) > 12:
        return short_name
    return game_name


async def notify_long_name_suggestion(
    user: discord.User | discord.Member,
    game_name: str,
    target_role: discord.Role,
    has_button_name: bool,
    has_short_name: bool,
):
    """Sends a single consolidated DM notice if game_name exceeds 7 or 12 characters and missing overrides."""
    needs_button_warn = len(game_name) > 7 and not has_button_name
    needs_short_warn = len(game_name) > 12 and not has_short_name

    if needs_button_warn or needs_short_warn:
        try:
            embed = discord.Embed(
                title=f"⚠️ Name Formatting Notice: {game_name}",
                color=discord.Color.gold(),
                timestamp=discord.utils.utcnow(),
            )

            warnings = []
            suggestions = []

            if needs_button_warn:
                warnings.append("• **Button Text Notice (> 7 Chars):** The name may clip on reaction role dashboard buttons.")
                suggestions.append("Set a custom button label: `new_button_name:<YourButtonLabel>`")

            if needs_short_warn:
                warnings.append("• **Channel/Thread Notice (> 12 Chars):** Channel and thread names will be auto-truncated.")
                suggestions.append("Set a short name: `new_short_name:<YourShortName>`")

            embed.description = (
                f"The game name **{game_name}** (`{len(game_name)}` characters) exceeds formatting thresholds:\n\n"
                + "\n".join(warnings)
            )

            sug_text = "\n".join(suggestions)
            embed.add_field(
                name="💡 Recommended Action",
                value=f"Update settings using `/edit_hub_game target_role:{target_role.name}`:\n{sug_text}",
                inline=False,
            )
            embed.set_footer(text="20R Hub Division Management")
            await user.send(embed=embed)
        except (discord.Forbidden, discord.HTTPException) as e:
            logger.warning(f"Could not send DM to {user.display_name}: {e}")


class ConfirmModalDeleteView(discord.ui.View):
    def __init__(
        self,
        threads_to_delete: list[discord.Thread],
        channels_to_delete: list[discord.TextChannel],
        roles_to_delete: list[discord.Role],
        target_role_id: int,
        user: discord.User,
    ):
        super().__init__(timeout=60)
        self.threads_to_delete = threads_to_delete
        self.channels_to_delete = channels_to_delete
        self.roles_to_delete = roles_to_delete
        self.target_role_id = target_role_id
        self.user = user

    @discord.ui.button(label="Confirm Teardown", style=discord.ButtonStyle.danger)
    async def confirm(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if interaction.user.id != self.user.id:
            await interaction.response.send_message(
                "❌ Unauthorized.", ephemeral=True
            )
            return

        for item in self.children:
            item.disabled = True

        await interaction.response.defer(ephemeral=True)

        deleted_threads = 0
        deleted_channels = 0
        deleted_roles = 0

        mappings = load_thread_mappings()
        mapped_thread_ids = {t.id for t in self.threads_to_delete}

        # 1. Delete Threads
        for thread in self.threads_to_delete:
            try:
                await thread.delete(
                    reason=f"Modal Division/Casual Teardown by {self.user}"
                )
                deleted_threads += 1
            except discord.HTTPException as e:
                logger.error(f"Failed to delete thread {thread.name}: {e}")

        if mappings:
            new_mappings = [
                m
                for m in mappings
                if m.get("thread_id") not in mapped_thread_ids
            ]
            save_thread_mappings(new_mappings)

        # 2. Delete Dedicated Channels
        for channel in self.channels_to_delete:
            try:
                await channel.delete(
                    reason=f"Modal Division Teardown by {self.user}"
                )
                deleted_channels += 1
            except discord.HTTPException as e:
                logger.error(f"Failed to delete channel {channel.name}: {e}")

        # 3. Delete Roles
        for role in self.roles_to_delete:
            try:
                await role.delete(
                    reason=f"Modal Division/Casual Teardown by {self.user}"
                )
                deleted_roles += 1
            except discord.HTTPException as e:
                logger.error(f"Failed to delete role {role.name}: {e}")

        # 4. Clean Records
        role_ids_to_match = {r.id for r in self.roles_to_delete}
        role_ids_to_match.add(self.target_role_id)

        division_records = load_division_records()
        new_div_records = [
            r for r in division_records
            if r.get("member_role_id") not in role_ids_to_match
            and r.get("game_role_id") not in role_ids_to_match
        ]
        save_division_records(new_div_records)

        casual_records = load_casual_records()
        new_casual_records = [
            c for c in casual_records
            if c.get("role_id") not in role_ids_to_match
        ]
        save_casual_records(new_casual_records)

        thread_sync_cog = interaction.client.get_cog("ThreadSync")
        if thread_sync_cog:
            await thread_sync_cog.update_dashboard(interaction.guild)

        # Trigger Reaction Roles Embed Update
        react_cog = interaction.client.get_cog("ReactForRoles")
        if react_cog:
            await react_cog.update_react_embeds(interaction.guild)

        try:
            await interaction.edit_original_response(
                content=(
                    f"✅ **Teardown Complete**\n"
                    f"• **Threads Removed:** `{deleted_threads}`\n"
                    f"• **Channels Removed:** `{deleted_channels}`\n"
                    f"• **Roles Removed:** `{deleted_roles}`"
                ),
                view=None,
            )
        except discord.HTTPException as e:
            logger.error(f"Failed to update teardown response: {e}")

        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await interaction.response.edit_message(
            content="❌ Teardown canceled.", view=None
        )
        self.stop()


class ModalDivisionManager(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        logger.info("[ModalDivisionManager] 🔄 Refreshing Hub Dashboards on startup...")
        for guild in self.bot.guilds:
            try:
                await self.update_dashboard(guild)
            except Exception as e:
                logger.error(f"[ModalDivisionManager] Failed to update dashboard for '{guild.name}': {e}")
        logger.info("[ModalDivisionManager] ✅ Hub Dashboards refreshed!")

    async def update_dashboard(self, guild: discord.Guild):
        dash_config = load_hub_dashboard_config()
        channel_id = dash_config.get("channel_id")
        message_id = dash_config.get("message_id")

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

        defaults = load_hub_defaults()

        embed = discord.Embed(
            title="⚙️ Division Setup — Default Hub & Role Configuration",
            color=discord.Color.gold(),
            timestamp=discord.utils.utcnow(),
        )

        embed.add_field(
            name="📖 Purpose & Staff Commands",
            value=(
                "Unselected channels, categories, and role section anchors automatically fall back to these defaults.\n\n"
                "**⚙️ Configuration:**\n"
                "• `/set_hub_defaults` — Update default hub channels & role anchors.\n"
                "• `/set_hub_dashboard_channel` — Move this dashboard embed.\n\n"
                "**🎮 Creation & Management:**\n"
                "• `/create_casual_game` — Create a casual role & communication thread.\n"
                "• `/create_division_hub` — Create a full game division setup.\n"
                "• `/promote_to_division_hub` — Convert a casual game into a division.\n"
                "• `/edit_hub_game` — Update game name, short name, button name, or restrictions.\n"
                "• `/delete_division_hub` — Teardown casual game or division.\n"
                "• `/list_hub_divisions` — List all registered hub divisions."
            ),
            inline=False,
        )

        def fmt_chan(c_id):
            if not c_id:
                return "❌ *Not Set*"
            ch = guild.get_channel(int(c_id))
            return f"(`{ch.name}`): {ch.mention}" if ch else f"`ID: {c_id}` *(Not found)*"

        def fmt_role(r_id):
            if not r_id:
                return "❌ *Not Set*"
            r = guild.get_role(int(r_id))
            return f"(`{r.name}`): {r.mention}" if r else f"`ID: {r_id}` *(Not found)*"

        embed.add_field(
            name="📍 Default Hub Destinations",
            value=(
                f"• **Chat Hub Thread Target** {fmt_chan(defaults.get('chat_hub_id'))}\n"
                f"• **Clips Hub Thread Target** {fmt_chan(defaults.get('clips_hub_id'))}\n"
                f"• **Staff Hub Thread Target** {fmt_chan(defaults.get('staff_hub_id'))}\n"
                f"• **Info Channel Category** {fmt_chan(defaults.get('info_category_id'))}\n"
                f"• **Announcement Category** {fmt_chan(defaults.get('news_category_id'))}"
            ),
            inline=False,
        )

        embed.add_field(
            name="🏷️ Default Role Category Anchors",
            value=(
                f"• **Casual Roles Anchor** {fmt_role(defaults.get('casual_role_category_id'))}\n"
                f"• **Public Roles Anchor** {fmt_role(defaults.get('public_role_category_id'))}\n"
                f"• **Division Staff Anchor** {fmt_role(defaults.get('div_staff_role_category_id'))}\n"
                f"• **Game Staff Anchor** {fmt_role(defaults.get('game_staff_role_category_id'))}\n"
                f"• **Division Roles Anchor** {fmt_role(defaults.get('member_role_category_id'))}"
            ),
            inline=False,
        )

        embed.set_footer(text="Auto-updates live when defaults are changed")

        if message_id:
            try:
                msg = await channel.fetch_message(message_id)
                await msg.edit(embed=embed)
                return
            except (discord.NotFound, discord.HTTPException):
                pass

        try:
            posted_msg = await channel.send(embed=embed)
            try:
                await posted_msg.pin(reason="Live Hub Defaults Dashboard")
            except (discord.Forbidden, discord.HTTPException):
                pass

            dash_config["channel_id"] = channel.id
            dash_config["message_id"] = posted_msg.id
            save_hub_dashboard_config(dash_config)

        except (discord.Forbidden, discord.HTTPException) as e:
            logger.error(f"❌ Error posting Hub Dashboard in #{channel.name}: {e}")

    async def _anchor_roles_to_divider(
        self, guild: discord.Guild, divider_role: discord.Role, roles_to_place: list[discord.Role]
    ):
        if not divider_role or not roles_to_place:
            return

        try:
            all_roles = sorted(guild.roles, key=lambda r: r.position, reverse=True)
            filtered_roles = [r for r in all_roles if r not in roles_to_place]

            if divider_role not in filtered_roles:
                return

            pivot_index = filtered_roles.index(divider_role) + 1
            new_role_order = (
                filtered_roles[:pivot_index]
                + roles_to_place
                + filtered_roles[pivot_index:]
            )

            positions = {}
            total_count = len(new_role_order)
            for idx, r in enumerate(new_role_order):
                if not r.is_default():
                    positions[r] = total_count - idx

            await guild.edit_role_positions(positions=positions)

        except (discord.HTTPException, ValueError) as e:
            logger.error(f"Failed to anchor roles beneath {divider_role.name}: {e}")

    async def _grant_category_access(
        self, category: discord.CategoryChannel, roles: list[discord.Role]
    ):
        if not category:
            return

        everyone_overwrite = category.overwrites_for(category.guild.default_role)
        if everyone_overwrite.view_channel is False:
            for role in roles:
                current_overwrite = category.overwrites_for(role)
                current_overwrite.view_channel = True
                await category.set_permissions(
                    role,
                    overwrite=current_overwrite,
                    reason="Granting category view access for division roles",
                )

    async def _adjust_category_permissions(
        self, channel: discord.TextChannel, roles: list[discord.Role]
    ):
        if channel and channel.category:
            await self._grant_category_access(channel.category, roles)

    # -------------------------------------------------------------------------
    # COMMANDS
    # -------------------------------------------------------------------------
    @app_commands.command(
        name="set_hub_defaults",
        description="Set default channels, categories, and role placement anchors for division creation.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def set_hub_defaults(
        self,
        interaction: discord.Interaction,
        chat_hub: discord.TextChannel = None,
        clips_hub: discord.TextChannel = None,
        staff_hub: discord.TextChannel = None,
        info_category: discord.CategoryChannel = None,
        news_category: discord.CategoryChannel = None,
        casual_role_category: discord.Role = None,
        public_role_category: discord.Role = None,
        div_staff_role_category: discord.Role = None,
        game_staff_role_category: discord.Role = None,
        member_role_category: discord.Role = None,
    ):
        defaults = load_hub_defaults()

        if chat_hub is not None: defaults["chat_hub_id"] = chat_hub.id
        if clips_hub is not None: defaults["clips_hub_id"] = clips_hub.id
        if staff_hub is not None: defaults["staff_hub_id"] = staff_hub.id
        if info_category is not None: defaults["info_category_id"] = info_category.id
        if news_category is not None: defaults["news_category_id"] = news_category.id

        if casual_role_category is not None: defaults["casual_role_category_id"] = casual_role_category.id
        if public_role_category is not None: defaults["public_role_category_id"] = public_role_category.id
        if div_staff_role_category is not None: defaults["div_staff_role_category_id"] = div_staff_role_category.id
        if game_staff_role_category is not None: defaults["game_staff_role_category_id"] = game_staff_role_category.id
        if member_role_category is not None: defaults["member_role_category_id"] = member_role_category.id

        save_hub_defaults(defaults)
        await interaction.response.send_message(
            "✅ Default hub configurations updated!", ephemeral=True
        )
        await self.update_dashboard(interaction.guild)

    @app_commands.command(
        name="set_hub_dashboard_channel",
        description="Set the channel where the live Hub Configuration dashboard is displayed.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(
        channel="Channel for the dashboard (Defaults to current channel if left blank)"
    )
    async def set_hub_dashboard_channel(
        self, interaction: discord.Interaction, channel: discord.TextChannel = None
    ):
        await interaction.response.defer(ephemeral=True)

        target_channel = channel or interaction.channel

        if not isinstance(target_channel, discord.TextChannel):
            await interaction.followup.send(
                "❌ The dashboard can only be placed inside a standard text channel.",
                ephemeral=True,
            )
            return

        dash_config = load_hub_dashboard_config()
        old_channel_id = dash_config.get("channel_id")
        old_message_id = dash_config.get("message_id")

        if old_channel_id and old_message_id:
            try:
                old_channel = interaction.guild.get_channel(
                    old_channel_id
                ) or await interaction.guild.fetch_channel(old_channel_id)
                if isinstance(old_channel, discord.TextChannel):
                    old_msg = await old_channel.fetch_message(old_message_id)
                    await old_msg.delete()
            except (discord.NotFound, discord.HTTPException, discord.Forbidden):
                pass

        dash_config["channel_id"] = target_channel.id
        dash_config["message_id"] = None
        save_hub_dashboard_config(dash_config)
        await self.update_dashboard(interaction.guild)

        await interaction.followup.send(
            f"✅ Hub Configuration dashboard set to {target_channel.mention}!",
            ephemeral=True,
        )

    @app_commands.command(
        name="create_casual_game",
        description="Create a casual game role (anchored under Casual) and private chat thread in Chat Hub.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(
        game_name="Full default name for game, roles, threads & channels (Required)",
        short_name="Short name used for threads/channels if game_name > 12 chars (Optional)",
        button_name="Custom button label for reaction role embed (Optional)",
    )
    async def createcasual_game(
        self,
        interaction: discord.Interaction,
        game_name: str,
        short_name: str = None,
        button_name: str = None,
        chat_hub: discord.TextChannel = None,
        casual_role_category: discord.Role = None,
    ):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        defaults = load_hub_defaults()

        target_hub = chat_hub or (guild.get_channel(defaults.get("chat_hub_id")) if defaults.get("chat_hub_id") else None)
        target_anchor = casual_role_category or (guild.get_role(defaults.get("casual_role_category_id")) if defaults.get("casual_role_category_id") else None)

        if not target_hub:
            await interaction.followup.send("❌ Chat Hub channel is not set. Use `/set_hub_defaults`.", ephemeral=True)
            return

        clean_game = format_game_name(game_name)
        clean_short = format_game_name(short_name) if short_name else None
        clean_button = format_game_name(button_name) if button_name else None

        channel_label = resolve_channel_label(clean_game, clean_short)
        slug_short = channel_label.lower().replace(" ", "-")

        # 1. Create Casual Role with Full Game Name
        casual_role = await guild.create_role(name=clean_game, color=COLOR_PUBLIC_GAME, mentionable=True)

        # 2. Anchor Role under Casual divider
        if target_anchor:
            await self._anchor_roles_to_divider(guild, target_anchor, [casual_role])

        # 3. Adjust permissions & Create Thread in Chat Hub (appends -chat)
        await self._adjust_category_permissions(target_hub, [casual_role])
        chat_thread = await target_hub.create_thread(
            name=f"{slug_short}-chat",
            type=discord.ChannelType.private_thread,
            invitable=False,
        )

        # 4. Save Thread Mapping & Casual Record
        mappings = load_thread_mappings()
        mappings.append({"role_id": casual_role.id, "thread_id": chat_thread.id, "created_by": interaction.user.id})
        save_thread_mappings(mappings)

        casual_records = load_casual_records()
        casual_records.append({
            "game_name": clean_game,
            "short_name": clean_short,
            "button_name": clean_button,  # None unless explicitly provided
            "role_id": casual_role.id,
            "thread_id": chat_thread.id,
            "is_casual": True,
        })
        save_casual_records(casual_records)

        thread_sync_cog = self.bot.get_cog("ThreadSync")
        if thread_sync_cog:
            await thread_sync_cog.update_dashboard(guild)

        # Trigger Reaction Roles Embed Update
        react_cog = self.bot.get_cog("ReactForRoles")
        if react_cog:
            await react_cog.update_react_embeds(guild)

        # Send DM notice if formatting thresholds are exceeded
        await notify_long_name_suggestion(
            interaction.user,
            clean_game,
            casual_role,
            has_button_name=bool(clean_button),
            has_short_name=bool(clean_short),
        )

        embed = discord.Embed(title=f"🎮 Casual Game Created: {clean_game}", color=discord.Color.green())
        embed.add_field(name="Role Created", value=casual_role.mention, inline=False)
        embed.add_field(name="Communication Thread", value=f"🔒 {chat_thread.mention} *(in {target_hub.mention})*", inline=False)

        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(
        name="create_division_hub",
        description="Create a division utilizing private hub threads, channels, and anchored roles.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(
        game_name="Full default name for game, roles, threads & channels (Required)",
        short_name="Short name used for threads/channels if game_name > 12 chars (Optional)",
        button_name="Custom button label for reaction role embed (Optional)",
    )
    async def create_division_hub(
        self,
        interaction: discord.Interaction,
        game_name: str,
        short_name: str = None,
        button_name: str = None,
        is_restrictive: bool = False,
        chat_hub: discord.TextChannel = None,
        clips_hub: discord.TextChannel = None,
        staff_hub: discord.TextChannel = None,
        info_category: discord.CategoryChannel = None,
        news_category: discord.CategoryChannel = None,
        public_role_category: discord.Role = None,
        div_staff_role_category: discord.Role = None,
        game_staff_role_category: discord.Role = None,
        member_role_category: discord.Role = None,
    ):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        if not guild:
            return

        defaults = load_hub_defaults()

        target_chat_hub = chat_hub or (guild.get_channel(defaults.get("chat_hub_id")) if defaults.get("chat_hub_id") else None)
        target_clips_hub = clips_hub or (guild.get_channel(defaults.get("clips_hub_id")) if defaults.get("clips_hub_id") else None)
        target_staff_hub = staff_hub or (guild.get_channel(defaults.get("staff_hub_id")) if defaults.get("staff_hub_id") else None)
        target_info_cat = info_category or (guild.get_channel(defaults.get("info_category_id")) if defaults.get("info_category_id") else None)
        target_news_cat = news_category or (guild.get_channel(defaults.get("news_category_id")) if defaults.get("news_category_id") else None)

        target_pub_cat = public_role_category or (guild.get_role(defaults.get("public_role_category_id")) if defaults.get("public_role_category_id") else None)
        target_div_staff_cat = div_staff_role_category or (guild.get_role(defaults.get("div_staff_role_category_id")) if defaults.get("div_staff_role_category_id") else None)
        target_game_staff_cat = game_staff_role_category or (guild.get_role(defaults.get("game_staff_role_category_id")) if defaults.get("game_staff_role_category_id") else None)
        target_mem_cat = member_role_category or (guild.get_role(defaults.get("member_role_category_id")) if defaults.get("member_role_category_id") else None)

        missing = []
        if not target_chat_hub: missing.append("Chat Hub Channel")
        if not target_clips_hub: missing.append("Clips Hub Channel")
        if not target_staff_hub: missing.append("Staff Hub Channel")
        if not target_info_cat: missing.append("Info Category")
        if not target_news_cat: missing.append("News Category")

        if missing:
            await interaction.followup.send(
                f"❌ **Missing Target(s):** {', '.join(missing)}\nSpecify in command or set defaults via `/set_hub_defaults`.",
                ephemeral=True,
            )
            return

        clean_game = format_game_name(game_name)
        clean_short = format_game_name(short_name) if short_name else None
        clean_button = format_game_name(button_name) if button_name else None

        channel_label = resolve_channel_label(clean_game, clean_short)
        slug_short = channel_label.lower().replace(" ", "-")

        try:
            # 1. Create Roles using full game name
            game_role = await guild.create_role(name=clean_game, color=COLOR_PUBLIC_GAME, mentionable=True)
            div_staff_role = await guild.create_role(name=f"{clean_game} Division Staff", color=COLOR_DIVISION_STAFF, mentionable=True)
            staff_role = await guild.create_role(name=f"{clean_game} Staff", color=COLOR_STAFF, mentionable=True)
            member_role = await guild.create_role(name=f"{clean_game} Division", color=COLOR_MEMBER, mentionable=True)

            # 2. Anchor Roles Under Specified Category Dividers
            if target_pub_cat:
                await self._anchor_roles_to_divider(guild, target_pub_cat, [game_role])
            if target_div_staff_cat:
                await self._anchor_roles_to_divider(guild, target_div_staff_cat, [div_staff_role])
            if target_game_staff_cat:
                await self._anchor_roles_to_divider(guild, target_game_staff_cat, [staff_role])
            if target_mem_cat:
                await self._anchor_roles_to_divider(guild, target_mem_cat, [member_role])

            all_div_roles = [game_role, member_role, staff_role, div_staff_role]

            # 3. Category Access Overwrites
            await self._grant_category_access(target_info_cat, all_div_roles)
            await self._grant_category_access(target_news_cat, all_div_roles)
            await self._adjust_category_permissions(target_chat_hub, all_div_roles)
            await self._adjust_category_permissions(target_clips_hub, all_div_roles)
            await self._adjust_category_permissions(target_staff_hub, [div_staff_role, staff_role])

            # 4. Create Dedicated Text Channels
            channel_overwrites = {
                guild.default_role: discord.PermissionOverwrite(
                    view_channel=False,
                    mention_everyone=False,
                ),
                game_role: discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=False,
                    read_message_history=True,
                    add_reactions=True,
                    use_external_emojis=True,
                    mention_everyone=False,
                ),
                member_role: discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=False,
                    read_message_history=True,
                    add_reactions=True,
                    use_external_emojis=True,
                    mention_everyone=False,
                ),
                staff_role: discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    create_public_threads=True,
                    create_private_threads=True,
                    send_messages_in_threads=True,
                    attach_files=True,
                    add_reactions=True,
                    use_external_emojis=True,
                    embed_links=True,
                    manage_messages=True,
                    mention_everyone=True,
                    manage_threads=True,
                    use_application_commands=True,
                    create_polls=True,
                    use_embedded_activities=True,
                    use_external_stickers=True,
                ),
                div_staff_role: discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    create_public_threads=True,
                    create_private_threads=True,
                    send_messages_in_threads=True,
                    attach_files=True,
                    add_reactions=True,
                    use_external_emojis=True,
                    embed_links=True,
                    manage_messages=True,
                    mention_everyone=True,
                    manage_threads=True,
                    use_application_commands=True,
                    create_polls=True,
                    use_embedded_activities=True,
                    use_external_stickers=True,
                    manage_permissions=True,
                    manage_webhooks=True,
                    manage_channels=True,
                ),
            }

            info_chan = await guild.create_text_channel(name=f"{slug_short}-info", category=target_info_cat, overwrites=channel_overwrites)
            announcements_chan = await guild.create_text_channel(name=f"{slug_short}-announcements", category=target_news_cat, overwrites=channel_overwrites)

            # 5. Create Private Threads & Save DB Mappings
            mappings = load_thread_mappings()

            chat_thread = await target_chat_hub.create_thread(name=f"{slug_short}-chat", type=discord.ChannelType.private_thread, invitable=False)
            mappings.append({"role_id": game_role.id, "thread_id": chat_thread.id, "created_by": interaction.user.id})
            mappings.append({"role_id": member_role.id, "thread_id": chat_thread.id, "created_by": interaction.user.id})

            clips_thread = await target_clips_hub.create_thread(name=f"{slug_short}-clips", type=discord.ChannelType.private_thread, invitable=False)
            mappings.append({"role_id": game_role.id, "thread_id": clips_thread.id, "created_by": interaction.user.id})
            mappings.append({"role_id": member_role.id, "thread_id": clips_thread.id, "created_by": interaction.user.id})

            staff_thread = await target_staff_hub.create_thread(name=f"{slug_short}-staff", type=discord.ChannelType.private_thread, invitable=False)
            mappings.append({"role_id": div_staff_role.id, "thread_id": staff_thread.id, "created_by": interaction.user.id})
            mappings.append({"role_id": staff_role.id, "thread_id": staff_thread.id, "created_by": interaction.user.id})

            save_thread_mappings(mappings)

            # 6. Save Complete Division Record
            records = load_division_records()
            records.append({
                "game_name": clean_game,
                "short_name": clean_short,
                "button_name": clean_button,  # None unless explicitly provided
                "public_role_id": game_role.id,
                "game_role_id": game_role.id,
                "member_role_id": member_role.id,
                "staff_role_id": staff_role.id,
                "div_staff_role_id": div_staff_role.id,
                "info_channel_id": info_chan.id,
                "news_channel_id": announcements_chan.id,
                "thread_ids": [chat_thread.id, clips_thread.id, staff_thread.id],
                "is_restrictive": is_restrictive,
                "is_casual": False,
            })
            save_division_records(records)

            thread_sync_cog = self.bot.get_cog("ThreadSync")
            if thread_sync_cog:
                await thread_sync_cog.run_full_thread_audit(guild)
                await thread_sync_cog.update_dashboard(guild)

            # Trigger Reaction Roles Embed Update
            react_cog = self.bot.get_cog("ReactForRoles")
            if react_cog:
                await react_cog.update_react_embeds(guild)

            # DM Notice evaluation
            await notify_long_name_suggestion(
                interaction.user,
                clean_game,
                game_role,
                has_button_name=bool(clean_button),
                has_short_name=bool(clean_short),
            )

            status_type = "🔒 Restrictive (Application Only)" if is_restrictive else "🔓 Open (Auto-Synced)"

            embed = discord.Embed(
                title=f"✅ New Division Created: {clean_game}",
                color=discord.Color.green(),
            )
            embed.add_field(
                name="Roles Created",
                value=(
                    f"• {game_role.mention} *(Public Game Role)*\n"
                    f"• {member_role.mention}\n"
                    f"• {staff_role.mention}\n"
                    f"• {div_staff_role.mention}"
                ),
                inline=False,
            )
            embed.add_field(name="Access Mode", value=status_type, inline=False)
            embed.add_field(
                name="Dedicated Channels",
                value=f"• {info_chan.mention} *(in {target_info_cat.name})*\n• {announcements_chan.mention} *(in {target_news_cat.name})*",
                inline=False,
            )
            embed.add_field(
                name="Private Hub Threads (Auto-Synced)",
                value=(
                    f"• 🔒 {chat_thread.mention} *(in {target_chat_hub.mention})*\n"
                    f"• 🔒 {clips_thread.mention} *(in {target_clips_hub.mention})*\n"
                    f"• 🔒 {staff_thread.mention} *(in {target_staff_hub.mention})*"
                ),
                inline=False,
            )

            await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            logger.error(f"Error creating hub division: {e}")
            await interaction.followup.send(f"❌ Creation failed: `{e}`", ephemeral=True)

    @app_commands.command(
        name="promote_to_division_hub",
        description="Promote an existing casual game into a full division.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def promotetodivision_hub(
        self,
        interaction: discord.Interaction,
        casual_role: discord.Role,
        is_restrictive: bool = False,
        chat_hub: discord.TextChannel = None,
        clips_hub: discord.TextChannel = None,
        staff_hub: discord.TextChannel = None,
        info_category: discord.CategoryChannel = None,
        news_category: discord.CategoryChannel = None,
    ):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        defaults = load_hub_defaults()

        casual_records = load_casual_records()
        record = next((r for r in casual_records if r.get("role_id") == casual_role.id), None)

        clean_game = record["game_name"] if record else casual_role.name
        clean_short = record.get("short_name") if record else None
        clean_button = record.get("button_name") if record else None

        channel_label = resolve_channel_label(clean_game, clean_short)
        slug_short = channel_label.lower().replace(" ", "-")

        # Resolve Targets
        target_chat_hub = chat_hub or (guild.get_channel(defaults.get("chat_hub_id")) if defaults.get("chat_hub_id") else None)
        target_clips_hub = clips_hub or (guild.get_channel(defaults.get("clips_hub_id")) if defaults.get("clips_hub_id") else None)
        target_staff_hub = staff_hub or (guild.get_channel(defaults.get("staff_hub_id")) if defaults.get("staff_hub_id") else None)
        target_info_cat = info_category or (guild.get_channel(defaults.get("info_category_id")) if defaults.get("info_category_id") else None)
        target_news_cat = news_category or (guild.get_channel(defaults.get("news_category_id")) if defaults.get("news_category_id") else None)

        target_pub_cat = guild.get_role(defaults.get("public_role_category_id")) if defaults.get("public_role_category_id") else None
        target_div_staff_cat = guild.get_role(defaults.get("div_staff_role_category_id")) if defaults.get("div_staff_role_category_id") else None
        target_game_staff_cat = guild.get_role(defaults.get("game_staff_role_category_id")) if defaults.get("game_staff_role_category_id") else None
        target_mem_cat = guild.get_role(defaults.get("member_role_category_id")) if defaults.get("member_role_category_id") else None

        # 1. Convert casual role to public game role & create Division / Staff roles
        game_role = casual_role
        div_staff_role = await guild.create_role(name=f"{clean_game} Division Staff", color=COLOR_DIVISION_STAFF, mentionable=True)
        staff_role = await guild.create_role(name=f"{clean_game} Staff", color=COLOR_STAFF, mentionable=True)
        member_role = await guild.create_role(name=f"{clean_game} Division", color=COLOR_MEMBER, mentionable=True)

        # 2. Re-anchor all roles
        if target_pub_cat: await self._anchor_roles_to_divider(guild, target_pub_cat, [game_role])
        if target_div_staff_cat: await self._anchor_roles_to_divider(guild, target_div_staff_cat, [div_staff_role])
        if target_game_staff_cat: await self._anchor_roles_to_divider(guild, target_game_staff_cat, [staff_role])
        if target_mem_cat: await self._anchor_roles_to_divider(guild, target_mem_cat, [member_role])

        # 3. FAST AUTO-ASSIGN
        assigned_count = 0
        if not is_restrictive:
            for m in casual_role.members:
                if m.bot:
                    continue
                has_member_or_recruit = any(
                    "member" in r.name.lower() or "recruit" in r.name.lower()
                    for r in m.roles
                )
                if has_member_or_recruit:
                    try:
                        await m.add_roles(member_role, reason="Auto-assigned Division Role on Promotion")
                        assigned_count += 1
                    except discord.HTTPException as e:
                        logger.error(f"Failed to give {member_role.name} to {m.display_name}: {e}")

        all_div_roles = [game_role, member_role, staff_role, div_staff_role]

        # 4. Category Access & Dedicated Channels
        if target_chat_hub:
            await self._adjust_category_permissions(target_chat_hub, all_div_roles)
        if target_clips_hub:
            await self._adjust_category_permissions(target_clips_hub, all_div_roles)
        if target_staff_hub:
            await self._adjust_category_permissions(target_staff_hub, [div_staff_role, staff_role])

        channel_overwrites = {
            guild.default_role: discord.PermissionOverwrite(
                view_channel=False,
                mention_everyone=False,
            ),
            game_role: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=False,
                read_message_history=True,
                add_reactions=True,
                use_external_emojis=True,
                mention_everyone=False,
            ),
            member_role: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=False,
                read_message_history=True,
                add_reactions=True,
                use_external_emojis=True,
                mention_everyone=False,
            ),
            staff_role: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                create_public_threads=True,
                create_private_threads=True,
                send_messages_in_threads=True,
                attach_files=True,
                add_reactions=True,
                use_external_emojis=True,
                embed_links=True,
                manage_messages=True,
                mention_everyone=True,
                manage_threads=True,
                use_application_commands=True,
                create_polls=True,
                use_embedded_activities=True,
                use_external_stickers=True,
            ),
            div_staff_role: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                create_public_threads=True,
                create_private_threads=True,
                send_messages_in_threads=True,
                attach_files=True,
                add_reactions=True,
                use_external_emojis=True,
                embed_links=True,
                manage_messages=True,
                mention_everyone=True,
                manage_threads=True,
                use_application_commands=True,
                create_polls=True,
                use_embedded_activities=True,
                use_external_stickers=True,
                manage_permissions=True,
                manage_webhooks=True,
                manage_channels=True,
            ),
        }

        info_chan = await guild.create_text_channel(name=f"{slug_short}-info", category=target_info_cat, overwrites=channel_overwrites)
        announcements_chan = await guild.create_text_channel(name=f"{slug_short}-announcements", category=target_news_cat, overwrites=channel_overwrites)

        mappings = load_thread_mappings()
        thread_ids_created = []

        # 5. REUSE EXISTING CASUAL THREAD FOR CHAT
        chat_thread = None
        if record and record.get("thread_id"):
            chat_thread = guild.get_thread(record.get("thread_id"))
            if not chat_thread:
                try:
                    chat_thread = await guild.fetch_channel(record.get("thread_id"))
                except (discord.NotFound, discord.HTTPException):
                    pass

        if chat_thread and isinstance(chat_thread, discord.Thread):
            try:
                await chat_thread.edit(name=f"{slug_short}-chat", reason="Promoting casual game to division chat thread.")
            except discord.HTTPException:
                pass
            
            mappings.append({"role_id": member_role.id, "thread_id": chat_thread.id, "created_by": interaction.user.id})
            thread_ids_created.append(chat_thread.id)
        else:
            if target_chat_hub:
                chat_thread = await target_chat_hub.create_thread(name=f"{slug_short}-chat", type=discord.ChannelType.private_thread, invitable=False)
                mappings.append({"role_id": game_role.id, "thread_id": chat_thread.id, "created_by": interaction.user.id})
                mappings.append({"role_id": member_role.id, "thread_id": chat_thread.id, "created_by": interaction.user.id})
                thread_ids_created.append(chat_thread.id)

        # 6. Create Clips & Staff Threads
        if target_clips_hub:
            clips_thread = await target_clips_hub.create_thread(name=f"{slug_short}-clips", type=discord.ChannelType.private_thread, invitable=False)
            mappings.append({"role_id": game_role.id, "thread_id": clips_thread.id, "created_by": interaction.user.id})
            mappings.append({"role_id": member_role.id, "thread_id": clips_thread.id, "created_by": interaction.user.id})
            thread_ids_created.append(clips_thread.id)

        if target_staff_hub:
            staff_thread = await target_staff_hub.create_thread(name=f"{slug_short}-staff", type=discord.ChannelType.private_thread, invitable=False)
            mappings.append({"role_id": div_staff_role.id, "thread_id": staff_thread.id, "created_by": interaction.user.id})
            mappings.append({"role_id": staff_role.id, "thread_id": staff_thread.id, "created_by": interaction.user.id})
            thread_ids_created.append(staff_thread.id)

        save_thread_mappings(mappings)

        # 7. Clean up Casual JSON & Save Division Record
        if record:
            new_casual = [c for c in casual_records if c.get("role_id") != casual_role.id]
            save_casual_records(new_casual)

        records = load_division_records()
        records.append({
            "game_name": clean_game,
            "short_name": clean_short,
            "button_name": clean_button,
            "public_role_id": game_role.id,
            "game_role_id": game_role.id,
            "member_role_id": member_role.id,
            "staff_role_id": staff_role.id,
            "div_staff_role_id": div_staff_role.id,
            "info_channel_id": info_chan.id,
            "news_channel_id": announcements_chan.id,
            "thread_ids": thread_ids_created,
            "is_restrictive": is_restrictive,
            "is_casual": False,
        })
        save_division_records(records)

        # 8. FORCE IMMEDIATE AUDITS & DASHBOARD UPDATE
        thread_sync_cog = self.bot.get_cog("ThreadSync")
        if thread_sync_cog:
            await thread_sync_cog.run_full_thread_audit(guild)
            await thread_sync_cog.update_dashboard(guild)

        # Trigger Reaction Roles Embed Update
        react_cog = self.bot.get_cog("ReactForRoles")
        if react_cog:
            await react_cog.update_react_embeds(guild)

        status_type = "🔒 Restrictive (Application Only)" if is_restrictive else "🔓 Open (Auto-Synced)"

        embed = discord.Embed(title=f"🚀 Promoted to Division: {clean_game}", color=discord.Color.green())
        embed.add_field(
            name="Roles Updated / Created",
            value=f"• {game_role.mention} *(Retained & Synced as Public Role)*\n• {member_role.mention} *(Auto-assigned to {assigned_count} member(s))*\n• {staff_role.mention}\n• {div_staff_role.mention}",
            inline=False,
        )
        embed.add_field(name="Access Mode", value=status_type, inline=False)
        embed.add_field(name="Dedicated Channels", value=f"• {info_chan.mention}\n• {announcements_chan.mention}", inline=False)
        embed.add_field(name="Division Hub Threads", value=f"• Reused existing chat thread & created clips/staff threads.", inline=False)

        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(
        name="edit_hub_game",
        description="Update full game name, short name, button name, or restrictions for a Game.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(
        target_role="The Casual Role, Public Game Role, or Division Role of the game to edit",
        new_game_name="New full default name for the game (Optional)",
        new_short_name="New short name/abbreviation for threads & channels (Optional)",
        new_button_name="New custom button label for reaction role embeds (Optional)",
        is_restrictive="Set True for Restrictive (Application Only) or False for Open (Auto-Synced) (Optional)",
    )
    async def edit_hub_game(
        self,
        interaction: discord.Interaction,
        target_role: discord.Role,
        new_game_name: str | None = None,
        new_short_name: str | None = None,
        new_button_name: str | None = None,
        is_restrictive: bool | None = None,
    ):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild

        if new_game_name is None and new_short_name is None and new_button_name is None and is_restrictive is None:
            await interaction.followup.send(
                "❌ You must specify at least one setting to update.",
                ephemeral=True,
            )
            return

        div_records = load_division_records()
        casual_records = load_casual_records()

        updated = False
        game_label = ""
        changes_summary = []

        # 1. Search & Update Division Records
        for record in div_records:
            if target_role.id in (record.get("game_role_id"), record.get("public_role_id"), record.get("member_role_id")):
                if new_game_name:
                    record["game_name"] = format_game_name(new_game_name)
                    changes_summary.append(f"• **Full Name:** `{record['game_name']}`")
                if new_short_name:
                    record["short_name"] = format_game_name(new_short_name)
                    changes_summary.append(f"• **Short Name:** `{record['short_name']}`")
                if new_button_name:
                    record["button_name"] = format_game_name(new_button_name)
                    changes_summary.append(f"• **Custom Button Name:** `{record['button_name']}`")
                if is_restrictive is not None:
                    record["is_restrictive"] = is_restrictive
                    mode_str = "🔒 Restrictive (Application Only)" if is_restrictive else "🔓 Open (Auto-Synced)"
                    changes_summary.append(f"• **Access Mode:** `{mode_str}`")

                updated = True
                game_label = record.get("game_name", target_role.name)
                break

        if updated:
            save_division_records(div_records)

        # 2. Search & Update Casual Records
        if not updated:
            for record in casual_records:
                if record.get("role_id") == target_role.id:
                    if new_game_name:
                        record["game_name"] = format_game_name(new_game_name)
                        changes_summary.append(f"• **Full Name:** `{record['game_name']}`")
                    if new_short_name:
                        record["short_name"] = format_game_name(new_short_name)
                        changes_summary.append(f"• **Short Name:** `{record['short_name']}`")
                    if new_button_name:
                        record["button_name"] = format_game_name(new_button_name)
                        changes_summary.append(f"• **Custom Button Name:** `{record['button_name']}`")
                    if is_restrictive is not None:
                        changes_summary.append("• *Note: Casual games do not support restriction modes.*")

                    updated = True
                    game_label = record.get("game_name", target_role.name)
                    break

            if updated:
                save_casual_records(casual_records)

        # 3. Search & Update Legacy Records
        if not updated:
            legacy_records = load_legacy_division_records()
            for record in legacy_records:
                if target_role.id in (record.get("game_role_id"), record.get("public_role_id"), record.get("member_role_id")):
                    if new_game_name:
                        record["game_name"] = format_game_name(new_game_name)
                        changes_summary.append(f"• **Full Name:** `{record['game_name']}`")
                    if new_short_name:
                        record["short_name"] = format_game_name(new_short_name)
                        changes_summary.append(f"• **Short Name:** `{record['short_name']}`")
                    if new_button_name:
                        record["button_name"] = format_game_name(new_button_name)
                        changes_summary.append(f"• **Custom Button Name:** `{record['button_name']}`")

                    updated = True
                    game_label = record.get("game_name", target_role.name)
                    break

            if updated:
                save_legacy_division_records(legacy_records)

        if not updated:
            await interaction.followup.send(
                f"❌ Could not find a registered record matching {target_role.mention}.",
                ephemeral=True,
            )
            return

        # 4. Refresh Reaction Roles Embed & Division Dashboard
        react_cog = self.bot.get_cog("ReactForRoles")
        if react_cog:
            await react_cog.update_react_embeds(guild)

        thread_sync_cog = self.bot.get_cog("ThreadSync")
        if thread_sync_cog:
            await thread_sync_cog.update_dashboard(guild)

        summary_text = "\n".join(changes_summary)
        await interaction.followup.send(
            f"✅ **Updated Record for `{game_label}`!**\n\n"
            f"{summary_text}\n\n"
            f"Dashboards and reaction role buttons updated automatically.",
            ephemeral=True,
        )

    @app_commands.command(
        name="list_hub_divisions",
        description="List all registered Hub Divisions and their restriction status.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def list_hub_divisions(self, interaction: discord.Interaction):
        records = load_division_records()
        if not records:
            await interaction.response.send_message("❌ No Hub Divisions are currently registered.", ephemeral=True)
            return

        embed = discord.Embed(title="🛡️ Registered Hub Divisions", color=discord.Color.gold())
        for r in records:
            pub = interaction.guild.get_role(r.get("game_role_id"))
            div = interaction.guild.get_role(r.get("member_role_id"))
            mode = "🔒 Restrictive (Application Only)" if r.get("is_restrictive") else "🔓 Open (Auto-Synced)"

            embed.add_field(
                name=f"🎮 {r.get('game_name')}",
                value=(
                    f"• **Public Role:** {pub.mention if pub else '`Unknown`'}\n"
                    f"• **Division Role:** {div.mention if div else '`Unknown`'}\n"
                    f"• **Access Mode:** {mode}"
                ),
                inline=False,
            )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="delete_division_hub",
        description="Delete a division or casual game's threads, channels, and roles.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(
        target_role="Select the Casual Role, Public Game Role, or Division Role to delete"
    )
    async def delete_division_hub(
        self,
        interaction: discord.Interaction,
        target_role: discord.Role,
        info_channel: discord.TextChannel = None,
        announcements_channel: discord.TextChannel = None,
    ):
        guild = interaction.guild
        defaults = load_hub_defaults()
        div_records = load_division_records()
        casual_records = load_casual_records()
        mappings = load_thread_mappings()

        threads_to_delete = []
        channels_to_delete = []
        roles_to_delete = [target_role]

        # 1. Check Division Records
        target_div_record = next(
            (r for r in div_records if r.get("member_role_id") == target_role.id or r.get("game_role_id") == target_role.id),
            None
        )

        # 2. Check Casual Game Records
        target_casual_record = next(
            (c for c in casual_records if c.get("role_id") == target_role.id),
            None
        )

        if target_div_record:
            for t_id in target_div_record.get("thread_ids", []):
                t = guild.get_thread(t_id)
                if t: threads_to_delete.append(t)

            info_id = target_div_record.get("info_channel_id")
            news_id = target_div_record.get("news_channel_id")

            if info_id and guild.get_channel(info_id): channels_to_delete.append(guild.get_channel(info_id))
            elif info_channel: channels_to_delete.append(info_channel)

            if news_id and guild.get_channel(news_id): channels_to_delete.append(guild.get_channel(news_id))
            elif announcements_channel: channels_to_delete.append(announcements_channel)

            for rid_key in ("game_role_id", "member_role_id", "staff_role_id", "div_staff_role_id"):
                rid = target_div_record.get(rid_key)
                if rid and guild.get_role(rid):
                    roles_to_delete.append(guild.get_role(rid))

        elif target_casual_record:
            t_id = target_casual_record.get("thread_id")
            if t_id:
                t = guild.get_thread(t_id)
                if t: threads_to_delete.append(t)

        else:
            # Fallback Mapping Lookup
            target_thread_ids = {m.get("thread_id") for m in mappings if m.get("role_id") == target_role.id}
            for t_id in target_thread_ids:
                if t_id:
                    t = guild.get_thread(t_id)
                    if t: threads_to_delete.append(t)

            if info_channel: channels_to_delete.append(info_channel)
            if announcements_channel: channels_to_delete.append(announcements_channel)

            base_name = target_role.name.replace(" Division", "").strip()
            for r_name in (base_name, f"{base_name} Division", f"{base_name} Division Staff", f"{base_name} Staff"):
                r = discord.utils.get(guild.roles, name=r_name)
                if r: roles_to_delete.append(r)

        # 3. Fallback scan for orphaned threads
        clean_slug = target_role.name.replace(" Division", "").strip().lower().replace(" ", "-")
        hub_channel_ids = [
            defaults.get("chat_hub_id"),
            defaults.get("clips_hub_id"),
            defaults.get("staff_hub_id"),
        ]
        for c_id in hub_channel_ids:
            if not c_id:
                continue
            parent_chan = guild.get_channel(c_id)
            if isinstance(parent_chan, discord.TextChannel):
                for thread in parent_chan.threads:
                    if clean_slug in thread.name.lower():
                        threads_to_delete.append(thread)

        threads_to_delete = list({t.id: t for t in threads_to_delete}.values())
        channels_to_delete = list({c.id: c for c in channels_to_delete}.values())
        roles_to_delete = list({r.id: r for r in roles_to_delete}.values())

        view = ConfirmModalDeleteView(
            threads_to_delete=threads_to_delete,
            channels_to_delete=channels_to_delete,
            roles_to_delete=roles_to_delete,
            target_role_id=target_role.id,
            user=interaction.user,
        )

        threads_fmt = "\n".join([f"• 🔒 {t.mention}" for t in threads_to_delete]) or "• *None found*"
        chans_fmt = "\n".join([f"• {c.mention}" for c in channels_to_delete]) or "• *None found*"
        roles_fmt = "\n".join([f"• {r.mention}" for r in roles_to_delete])

        await interaction.response.send_message(
            f"⚠️ **Confirm Teardown**\n\n"
            f"**Threads to delete:**\n{threads_fmt}\n\n"
            f"**Channels to delete:**\n{chans_fmt}\n\n"
            f"**Roles to delete:**\n{roles_fmt}",
            view=view,
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(ModalDivisionManager(bot))