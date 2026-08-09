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
)

logger = logging.getLogger(__name__)

COLOR_DIVISION_STAFF = discord.Color(0xE67E22)
COLOR_STAFF = discord.Color(0xF1C40F)
COLOR_MEMBER = discord.Color(0xAD1457)


# -------------------------------------------------------------------------
# TEARDOWN CONFIRMATION VIEW
# -------------------------------------------------------------------------
class ConfirmModalDeleteView(discord.ui.View):
    def __init__(
        self,
        threads_to_delete: list[discord.Thread],
        channels_to_delete: list[discord.TextChannel],
        roles_to_delete: list[discord.Role],
        member_role_id: int,
        user: discord.User,
    ):
        super().__init__(timeout=60)
        self.threads_to_delete = threads_to_delete
        self.channels_to_delete = channels_to_delete
        self.roles_to_delete = roles_to_delete
        self.member_role_id = member_role_id
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

        await interaction.response.defer(ephemeral=True)

        deleted_threads = 0
        deleted_channels = 0
        deleted_roles = 0

        # 1. Delete Threads & remove database mappings
        mappings = load_thread_mappings()
        mapped_thread_ids = {t.id for t in self.threads_to_delete}

        for thread in self.threads_to_delete:
            try:
                await thread.delete(
                    reason=f"Modal Division Teardown by {self.user}"
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

        # 2. Delete Text Channels
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
                    reason=f"Modal Division Teardown by {self.user}"
                )
                deleted_roles += 1
            except discord.HTTPException as e:
                logger.error(f"Failed to delete role {role.name}: {e}")

        # 4. Remove entry from division_records.json
        records = load_division_records()
        new_records = [
            r for r in records if r.get("member_role_id") != self.member_role_id
        ]
        save_division_records(new_records)

        # Refresh dashboards if cogs loaded
        thread_sync_cog = interaction.client.get_cog("ThreadSync")
        if thread_sync_cog:
            await thread_sync_cog.update_dashboard(interaction.guild)

        await interaction.followup.send(
            f"✅ **Division Deleted**\n"
            f"• **Threads Removed:** `{deleted_threads}`\n"
            f"• **Channels Removed:** `{deleted_channels}`\n"
            f"• **Roles Removed:** `{deleted_roles}`",
            ephemeral=True,
        )
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await interaction.response.edit_message(
            content="❌ Teardown canceled.", view=None
        )
        self.stop()


# -------------------------------------------------------------------------
# DIVISION MANAGER COG
# -------------------------------------------------------------------------
class ModalDivisionManager(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        """Automatically refreshes the Hub Dashboard embed whenever the bot starts up."""
        for guild in self.bot.guilds:
            await self.update_dashboard(guild)

    async def update_dashboard(self, guild: discord.Guild):
        """Builds and edits the live-updating embed displaying default hub setup."""
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
            title="⚙️ Division Setup — Default Hub Configuration",
            color=discord.Color.gold(),
            timestamp=discord.utils.utcnow(),
        )

        embed.add_field(
            name="📖 How It Works",
            value=(
                "When creating a division with `/createdivision_hub`, any unselected channel/category "
                "options will automatically fall back to these defaults.\n\n"
                "• **Update Defaults:** `/set_hub_defaults`\n"
                "• **Set Dashboard Channel:** `/set_hub_dashboard_channel`"
            ),
            inline=False,
        )

        def fmt_chan(c_id):
            if not c_id:
                return "❌ *Not Set*"
            ch = guild.get_channel(int(c_id))
            return ch.mention if ch else f"`ID: {c_id}` *(Not found)*"

        embed.add_field(
            name="📍 Default Hub Destinations",
            value=(
                f"• **Chat Hub Thread Target:** {fmt_chan(defaults.get('chat_hub_id'))}\n"
                f"• **Clips Hub Thread Target:** {fmt_chan(defaults.get('clips_hub_id'))}\n"
                f"• **Staff Hub Thread Target:** {fmt_chan(defaults.get('staff_hub_id'))}\n"
                f"• **Info Channel Category:** {fmt_chan(defaults.get('info_category_id'))}\n"
                f"• **News/Announcements Category:** {fmt_chan(defaults.get('news_category_id'))}"
            ),
            inline=False,
        )

        embed.set_footer(text="Auto-updates live when defaults are changed")

        try:
            if message_id:
                try:
                    msg = await channel.fetch_message(message_id)
                    await msg.edit(embed=embed)
                    return
                except discord.NotFound:
                    pass

            msg = await channel.send(embed=embed)
            try:
                await msg.pin(reason="Live Hub Defaults Dashboard")
            except (discord.Forbidden, discord.HTTPException):
                pass

            dash_config["channel_id"] = channel.id
            dash_config["message_id"] = msg.id
            save_hub_dashboard_config(dash_config)

        except (discord.Forbidden, discord.HTTPException) as e:
            logger.error(f"❌ Error updating Hub Dashboard in #{channel.name}: {e}")

    async def _adjust_category_permissions(
        self, channel: discord.TextChannel, roles: list[discord.Role]
    ):
        """Helper: Checks if target channel is restricted, and modifies Category permissions instead of breaking sync."""
        category = channel.category
        if not category:
            return

        everyone_overwrite = channel.overwrites_for(channel.guild.default_role)
        if everyone_overwrite.view_channel is False:
            for role in roles:
                current_cat_overwrite = category.overwrites_for(role)
                current_cat_overwrite.view_channel = True
                await category.set_permissions(
                    role,
                    overwrite=current_cat_overwrite,
                    reason="Granting category view access for division hub thread",
                )

    # -------------------------------------------------------------------------
    # COMMANDS
    # -------------------------------------------------------------------------
    @app_commands.command(
        name="set_hub_defaults",
        description="Set default channels/categories for division creation.",
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
    ):
        defaults = load_hub_defaults()

        if chat_hub:
            defaults["chat_hub_id"] = chat_hub.id
        if clips_hub:
            defaults["clips_hub_id"] = clips_hub.id
        if staff_hub:
            defaults["staff_hub_id"] = staff_hub.id
        if info_category:
            defaults["info_category_id"] = info_category.id
        if news_category:
            defaults["news_category_id"] = news_category.id

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
        name="createdivision_hub",
        description="Create a division utilizing private hub threads and dedicated info channels.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(
        game_name="Full game name (e.g. 'World of Warcraft')",
        short_name="Short abbreviation (Optional)",
        chat_hub="Override default chat hub channel",
        clips_hub="Override default clips hub channel",
        staff_hub="Override default staff hub channel",
        info_category="Override default Info category",
        news_category="Override default News category",
    )
    async def create_division_hub(
        self,
        interaction: discord.Interaction,
        game_name: str,
        short_name: str = None,
        chat_hub: discord.TextChannel = None,
        clips_hub: discord.TextChannel = None,
        staff_hub: discord.TextChannel = None,
        info_category: discord.CategoryChannel = None,
        news_category: discord.CategoryChannel = None,
    ):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        if not guild:
            return

        defaults = load_hub_defaults()

        # Resolve Targets
        target_chat_hub = chat_hub or (
            guild.get_channel(defaults.get("chat_hub_id"))
            if defaults.get("chat_hub_id")
            else None
        )
        target_clips_hub = clips_hub or (
            guild.get_channel(defaults.get("clips_hub_id"))
            if defaults.get("clips_hub_id")
            else None
        )
        target_staff_hub = staff_hub or (
            guild.get_channel(defaults.get("staff_hub_id"))
            if defaults.get("staff_hub_id")
            else None
        )
        target_info_cat = info_category or (
            guild.get_channel(defaults.get("info_category_id"))
            if defaults.get("info_category_id")
            else None
        )
        target_news_cat = news_category or (
            guild.get_channel(defaults.get("news_category_id"))
            if defaults.get("news_category_id")
            else None
        )

        missing = []
        if not target_chat_hub:
            missing.append("Chat Hub Channel")
        if not target_clips_hub:
            missing.append("Clips Hub Channel")
        if not target_staff_hub:
            missing.append("Staff Hub Channel")
        if not target_info_cat:
            missing.append("Info Category")
        if not target_news_cat:
            missing.append("News Category")

        if missing:
            await interaction.followup.send(
                f"❌ **Missing Configuration Target(s):** {', '.join(missing)}\n"
                f"Please specify them in the command or set default fallbacks using `/set_hub_defaults`.",
                ephemeral=True,
            )
            return

        clean_game = game_name.strip()
        clean_short = short_name.strip() if short_name else clean_game
        slug_short = clean_short.lower().replace(" ", "-")

        try:
            # 1. Create Roles
            div_staff_role = await guild.create_role(
                name=f"{clean_short} Division Staff",
                color=COLOR_DIVISION_STAFF,
                mentionable=True,
            )
            staff_role = await guild.create_role(
                name=f"{clean_short} Staff",
                color=COLOR_STAFF,
                mentionable=True,
            )
            member_role = await guild.create_role(
                name=f"{clean_short} Division",
                color=COLOR_MEMBER,
                mentionable=True,
            )

            # 2. Adjust Category Permissions
            await self._adjust_category_permissions(
                target_staff_hub, [div_staff_role, staff_role]
            )

            # 3. Create Dedicated Channels
            read_only_overwrites = {
                guild.default_role: discord.PermissionOverwrite(
                    view_channel=True, send_messages=False
                ),
                member_role: discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=False,
                    add_reactions=True,
                ),
                staff_role: discord.PermissionOverwrite(
                    view_channel=True, send_messages=True
                ),
                div_staff_role: discord.PermissionOverwrite(
                    view_channel=True, send_messages=True
                ),
            }

            info_chan = await guild.create_text_channel(
                name=f"{slug_short}-info",
                category=target_info_cat,
                overwrites=read_only_overwrites,
            )
            announcements_chan = await guild.create_text_channel(
                name=f"{slug_short}-announcements",
                category=target_news_cat,
                overwrites=read_only_overwrites,
            )

            # 4. Create Private Threads & Save DB Mappings
            mappings = load_thread_mappings()

            chat_thread = await target_chat_hub.create_thread(
                name=f"{slug_short}-chat",
                type=discord.ChannelType.private_thread,
                invitable=False,
            )
            mappings.append(
                {
                    "role_id": member_role.id,
                    "thread_id": chat_thread.id,
                    "created_by": interaction.user.id,
                }
            )

            clips_thread = await target_clips_hub.create_thread(
                name=f"{slug_short}-clips",
                type=discord.ChannelType.private_thread,
                invitable=False,
            )
            mappings.append(
                {
                    "role_id": member_role.id,
                    "thread_id": clips_thread.id,
                    "created_by": interaction.user.id,
                }
            )

            staff_thread = await target_staff_hub.create_thread(
                name=f"{slug_short}-staff",
                type=discord.ChannelType.private_thread,
                invitable=False,
            )
            mappings.append(
                {
                    "role_id": div_staff_role.id,
                    "thread_id": staff_thread.id,
                    "created_by": interaction.user.id,
                }
            )
            mappings.append(
                {
                    "role_id": staff_role.id,
                    "thread_id": staff_thread.id,
                    "created_by": interaction.user.id,
                }
            )

            save_thread_mappings(mappings)

            # 5. SAVE COMPLETE DIVISION RECORD
            records = load_division_records()
            records.append(
                {
                    "game_name": clean_game,
                    "short_name": clean_short,
                    "member_role_id": member_role.id,
                    "staff_role_id": staff_role.id,
                    "div_staff_role_id": div_staff_role.id,
                    "info_channel_id": info_chan.id,
                    "news_channel_id": announcements_chan.id,
                    "thread_ids": [
                        chat_thread.id,
                        clips_thread.id,
                        staff_thread.id,
                    ],
                }
            )
            save_division_records(records)

            # Trigger ThreadSync dashboard update
            thread_sync_cog = self.bot.get_cog("ThreadSync")
            if thread_sync_cog:
                await thread_sync_cog.update_dashboard(guild)

            embed = discord.Embed(
                title=f"✅ New Division Created: {clean_game}",
                color=discord.Color.green(),
            )
            embed.add_field(
                name="Roles Created",
                value=(
                    f"• {div_staff_role.mention}\n"
                    f"• {staff_role.mention}\n"
                    f"• {member_role.mention}"
                ),
                inline=False,
            )
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
            await interaction.followup.send(
                f"❌ Creation failed: `{e}`", ephemeral=True
            )

    @app_commands.command(
        name="deletedivision_hub",
        description="Delete a division's hub threads, channels, and associated roles.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def delete_division_hub(
        self,
        interaction: discord.Interaction,
        member_role: discord.Role,
        info_channel: discord.TextChannel = None,
        announcements_channel: discord.TextChannel = None,
    ):
        """Looks up division record by member_role_id and builds comprehensive teardown list."""
        guild = interaction.guild
        records = load_division_records()

        target_record = None
        for r in records:
            if r.get("member_role_id") == member_role.id:
                target_record = r
                break

        threads_to_delete = []
        channels_to_delete = []
        roles_to_delete = [member_role]

        if target_record:
            # Load Threads from JSON Record
            for t_id in target_record.get("thread_ids", []):
                t = guild.get_thread(t_id)
                if t:
                    threads_to_delete.append(t)

            # Load Text Channels from JSON Record (or fallback to options)
            info_id = target_record.get("info_channel_id")
            news_id = target_record.get("news_channel_id")

            if info_id:
                c = guild.get_channel(info_id)
                if c:
                    channels_to_delete.append(c)
            elif info_channel:
                channels_to_delete.append(info_channel)

            if news_id:
                c = guild.get_channel(news_id)
                if c:
                    channels_to_delete.append(c)
            elif announcements_channel:
                channels_to_delete.append(announcements_channel)

            # Load Staff Roles from JSON Record
            s_id = target_record.get("staff_role_id")
            ds_id = target_record.get("div_staff_role_id")
            if s_id:
                r = guild.get_role(s_id)
                if r:
                    roles_to_delete.append(r)
            if ds_id:
                r = guild.get_role(ds_id)
                if r:
                    roles_to_delete.append(r)

        else:
            # Fallback for legacy divisions created before JSON records existed
            mappings = load_thread_mappings()
            target_thread_ids = {
                m.get("thread_id")
                for m in mappings
                if m.get("role_id") == member_role.id
            }
            for t_id in target_thread_ids:
                thread = guild.get_thread(t_id)
                if thread:
                    threads_to_delete.append(thread)

            if info_channel:
                channels_to_delete.append(info_channel)
            if announcements_channel:
                channels_to_delete.append(announcements_channel)

            base_name = member_role.name.replace(" Division", "")
            for r_name in (f"{base_name} Division Staff", f"{base_name} Staff"):
                r = discord.utils.get(guild.roles, name=r_name)
                if r:
                    roles_to_delete.append(r)

        # Deduplicate lists
        threads_to_delete = list({t.id: t for t in threads_to_delete}.values())
        channels_to_delete = list({c.id: c for c in channels_to_delete}.values())
        roles_to_delete = list({r.id: r for r in roles_to_delete}.values())

        view = ConfirmModalDeleteView(
            threads_to_delete=threads_to_delete,
            channels_to_delete=channels_to_delete,
            roles_to_delete=roles_to_delete,
            member_role_id=member_role.id,
            user=interaction.user,
        )

        threads_fmt = (
            "\n".join([f"• 🔒 {t.mention}" for t in threads_to_delete])
            or "• *None found*"
        )
        chans_fmt = (
            "\n".join([f"• {c.mention}" for c in channels_to_delete])
            or "• *None found*"
        )
        roles_fmt = "\n".join([f"• {r.mention}" for r in roles_to_delete])

        await interaction.response.send_message(
            f"⚠️ **Confirm Division Teardown**\n\n"
            f"**Threads to delete:**\n{threads_fmt}\n\n"
            f"**Channels to delete:**\n{chans_fmt}\n\n"
            f"**Roles to delete:**\n{roles_fmt}",
            view=view,
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(ModalDivisionManager(bot))