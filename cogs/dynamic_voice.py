import asyncio
import json
import logging
import os
import re
import time
import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger(__name__)

CONFIG_FILE = "data/dynamic_voice_config.json"
RANK_CONFIG_FILE = "data/rank_system_config.json"


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


def load_rank_config() -> dict:
    if not os.path.exists(RANK_CONFIG_FILE):
        return {}
    with open(RANK_CONFIG_FILE, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}


def get_clean_username(member: discord.Member) -> str:
    """Strips nickname tags like [R1] or [Mod] to retrieve the clean username."""
    clean = re.sub(r"^\[.*?\]\s*|^\(.*?\)\s*", "", member.display_name).strip()
    return clean or member.name


def format_channel_name(template: str, index: int, member: discord.Member) -> str:
    """Formats the channel name template using {index} and {username} placeholders."""
    clean_name = get_clean_username(member)
    formatted = template.replace("{index}", str(index)).replace("{username}", clean_name)
    return formatted[:100]  # Discord channel name limit is 100 chars


# -------------------------------------------------------------------------
# UI HELPERS
# -------------------------------------------------------------------------
class AutoDeleteView(discord.ui.View):
    """A View that automatically deletes its original interaction response on timeout."""
    def __init__(self, interaction: discord.Interaction, timeout: float = 30.0):
        super().__init__(timeout=timeout)
        self.interaction = interaction

    async def on_timeout(self):
        try:
            await self.interaction.delete_original_response()
        except discord.HTTPException:
            pass


# -------------------------------------------------------------------------
# PERSISTENT CHANNEL CONTROL PANEL VIEW
# -------------------------------------------------------------------------
class DynamicVoiceControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def _get_vc_data(self, interaction: discord.Interaction) -> tuple[int | None, int | None]:
        """Fetches the owner ID and index from config. Returns (owner_id, index)."""
        configs = load_config()
        cfg = configs.get(str(interaction.guild_id), {})
        channel_data = cfg.get("active_channels", {}).get(str(interaction.channel_id))

        if not channel_data:
            await interaction.response.send_message(
                "❌ This channel is no longer tracked as a dynamic voice channel.", ephemeral=True
            )
            return None, None

        owner_id = channel_data.get("owner_id")
        index = channel_data.get("index")

        if interaction.user.id != owner_id and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "❌ Only the channel owner can use these controls!", ephemeral=True
            )
            return None, None

        return owner_id, index

    @discord.ui.button(label="Lock / Unlock", style=discord.ButtonStyle.secondary, emoji="🔒", custom_id="dvc_lock", row=0)
    async def toggle_lock(self, interaction: discord.Interaction, button: discord.ui.Button):
        owner_id, index = await self._get_vc_data(interaction)
        if not owner_id: return

        await interaction.response.defer(ephemeral=True)
        channel = interaction.channel

        current = channel.overwrites_for(interaction.guild.default_role)
        is_locked = current.connect is False

        current.connect = None if is_locked else False
        await channel.set_permissions(interaction.guild.default_role, overwrite=current)

        status = "🔓 **Unlocked**" if is_locked else "🔒 **Locked**"
        await interaction.followup.send(f"Channel is now {status} for everyone.", ephemeral=True)

    @discord.ui.button(label="Rename", style=discord.ButtonStyle.secondary, emoji="✏️", custom_id="dvc_rename", row=0)
    async def rename_channel(self, interaction: discord.Interaction, button: discord.ui.Button):
        owner_id, index = await self._get_vc_data(interaction)
        if not owner_id: return

        channel = interaction.channel
        modal = discord.ui.Modal(title="Rename Voice Channel")
        new_name_input = discord.ui.TextInput(
            label="New Channel Name",
            placeholder="e.g. Strategy Room",
            default=channel.name,
            required=True,
            max_length=32
        )
        modal.add_item(new_name_input)

        async def modal_submit(modal_interaction: discord.Interaction):
            await modal_interaction.response.defer(ephemeral=True)
            new_name = new_name_input.value.strip()
            await channel.edit(name=new_name)
            await modal_interaction.followup.send(f"✅ Channel renamed to **{new_name}**!", ephemeral=True)

        modal.on_submit = modal_submit
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Set Limit", style=discord.ButtonStyle.secondary, emoji="👥", custom_id="dvc_limit", row=0)
    async def set_limit(self, interaction: discord.Interaction, button: discord.ui.Button):
        owner_id, index = await self._get_vc_data(interaction)
        if not owner_id: return

        channel = interaction.channel
        modal = discord.ui.Modal(title="Set User Limit")
        limit_input = discord.ui.TextInput(
            label="User Limit (0 for unlimited, max 99)",
            placeholder="e.g., 5",
            default=str(channel.user_limit),
            required=True,
            max_length=2
        )
        modal.add_item(limit_input)

        async def modal_submit(modal_interaction: discord.Interaction):
            await modal_interaction.response.defer(ephemeral=True)
            val = limit_input.value.strip()
            if not val.isdigit() or not (0 <= int(val) <= 99):
                await modal_interaction.followup.send("❌ Please enter a valid number between 0 and 99.", ephemeral=True)
                return
            
            await channel.edit(user_limit=int(val))
            limit_msg = f"**{val} users**" if int(val) > 0 else "**Unlimited**"
            await modal_interaction.followup.send(f"✅ Channel user limit set to {limit_msg}.", ephemeral=True)

        modal.on_submit = modal_submit
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Region", style=discord.ButtonStyle.secondary, emoji="🌍", custom_id="dvc_region", row=0)
    async def set_region(self, interaction: discord.Interaction, button: discord.ui.Button):
        owner_id, index = await self._get_vc_data(interaction)
        if not owner_id: return

        options = [
            discord.SelectOption(label="Automatic", value="auto", description="Best region automatically selected"),
            discord.SelectOption(label="US East", value="us-east"),
            discord.SelectOption(label="US Central", value="us-central"),
            discord.SelectOption(label="US West", value="us-west"),
            discord.SelectOption(label="US South", value="us-south"),
            discord.SelectOption(label="Europe", value="europe"),
            discord.SelectOption(label="Sydney", value="sydney"),
            discord.SelectOption(label="Brazil", value="brazil"),
            discord.SelectOption(label="Japan", value="japan"),
            discord.SelectOption(label="Singapore", value="singapore"),
        ]
        select = discord.ui.Select(placeholder="Select a voice region...", options=options)

        async def select_callback(select_interaction: discord.Interaction):
            await select_interaction.response.edit_message(content="⏳ Updating voice region...", view=None)

            async def cleanup():
                await asyncio.sleep(30)
                try:
                    await select_interaction.delete_original_response()
                except discord.HTTPException:
                    pass

            val = select.values[0]
            region = None if val == "auto" else val
            try:
                await interaction.channel.edit(rtc_region=region)
                await select_interaction.edit_original_response(content=f"✅ Voice region successfully set to **{val.title()}**.", view=None)
            except Exception as e:
                await select_interaction.edit_original_response(content=f"❌ Failed to set region: {e}", view=None)
            
            asyncio.create_task(cleanup())

        select.callback = select_callback
        view = AutoDeleteView(interaction, timeout=30.0)
        view.add_item(select)
        await interaction.response.send_message("Select a new voice region:", view=view, ephemeral=True)

    @discord.ui.button(label="Transfer", style=discord.ButtonStyle.primary, emoji="👑", custom_id="dvc_transfer", row=1)
    async def transfer_ownership(self, interaction: discord.Interaction, button: discord.ui.Button):
        owner_id, index = await self._get_vc_data(interaction)
        if not owner_id: return

        channel = interaction.channel
        guild = interaction.guild

        members_in_channel = [m for m in channel.members if m.id != owner_id and not m.bot]
        if not members_in_channel:
            await interaction.response.send_message("❌ No other eligible users are in the channel to transfer to.", ephemeral=True)
            return

        options = [
            discord.SelectOption(label=m.display_name[:100], value=str(m.id))
            for m in members_in_channel[:25]
        ]
        select = discord.ui.Select(placeholder="Select new channel owner...", options=options)

        async def select_callback(select_interaction: discord.Interaction):
            # Edit the dropdown message so the user knows it's processing, and remove the menu view
            await select_interaction.response.edit_message(content="⏳ Processing transfer...", view=None)
            
            # 30-Second Auto-Delete Task for Ephemeral Followups
            async def cleanup():
                await asyncio.sleep(30)
                try:
                    await select_interaction.delete_original_response()
                except discord.HTTPException:
                    pass

            new_owner_id = int(select.values[0])
            new_owner = guild.get_member(new_owner_id)
            old_owner = guild.get_member(owner_id)

            if not new_owner:
                await select_interaction.edit_original_response(content="❌ User no longer found.")
                asyncio.create_task(cleanup())
                return

            # Strip old owner's management permissions
            if old_owner:
                old_overwrite = channel.overwrites_for(old_owner)
                old_overwrite.manage_channels = None
                old_overwrite.manage_permissions = None
                old_overwrite.move_members = None
                old_overwrite.mute_members = None
                await channel.set_permissions(old_owner, overwrite=old_overwrite)

            # Grant new owner management permissions
            new_overwrite = channel.overwrites_for(new_owner)
            new_overwrite.view_channel = True
            new_overwrite.connect = True
            new_overwrite.speak = True
            new_overwrite.manage_channels = True
            new_overwrite.manage_permissions = True
            new_overwrite.move_members = True
            new_overwrite.mute_members = True
            await channel.set_permissions(new_owner, overwrite=new_overwrite)

            configs = load_config()
            cfg = configs.get(str(guild.id), {})
            template = cfg.get("channel_name_format", "#{index}-{username}'s-Channel")

            # Smart Rename: Only change if it matches the generated default template for the old owner
            expected_old_name = format_channel_name(template, index, old_owner) if old_owner else ""
            if channel.name == expected_old_name:
                new_channel_name = format_channel_name(template, index, new_owner)
                await channel.edit(name=new_channel_name)

            # Save new owner to config
            cfg["active_channels"][str(channel.id)]["owner_id"] = new_owner.id
            configs[str(guild.id)] = cfg
            save_config(configs)

            # Update Control Panel Embed
            embed = interaction.message.embeds[0]
            clean_name = get_clean_username(new_owner)
            embed.title = f"🎙️ {clean_name}'s Channel Controls"
            embed.description = (
                f"Welcome {new_owner.mention}! You are the owner of this dynamic channel.\n\n"
                "**Available Controls:**\n"
                "🔒 Lock/Unlock • ✏️ Rename • 👥 Set Limit • 🌍 Region • 👑 Transfer • 🔇 Local Mute\n\n"
                "⚠️ **Mute Feature Rules:** Do not abuse the local mute feature. Muting without a valid reason "
                "is considered abuse and will result in the loss of this privilege. You may only mute/unmute a "
                "specific user once per 10 minutes. *(Note: Muting/Unmuting a user will automatically disconnect them to apply the change).* "
            )
            await interaction.message.edit(content=new_owner.mention, embed=embed)

            await select_interaction.edit_original_response(content=f"✅ Ownership transferred to {new_owner.mention}.")
            asyncio.create_task(cleanup())

        select.callback = select_callback
        view = AutoDeleteView(interaction, timeout=30.0)
        view.add_item(select)
        await interaction.response.send_message("Select a member to transfer ownership to:", view=view, ephemeral=True)

    @discord.ui.button(label="Local Mute", style=discord.ButtonStyle.danger, emoji="🔇", custom_id="dvc_mute", row=1)
    async def local_mute(self, interaction: discord.Interaction, button: discord.ui.Button):
        owner_id, index = await self._get_vc_data(interaction)
        if not owner_id: return

        guild = interaction.guild
        channel = interaction.channel

        configs = load_config()
        cfg = configs.get(str(guild.id), {})
        restricted_role_id = cfg.get("mute_restricted_role_id")
        
        if restricted_role_id and restricted_role_id in [r.id for r in interaction.user.roles]:
            await interaction.response.send_message(
                "❌ You have had your muting privileges revoked due to prior abuse.", ephemeral=True
            )
            return

        members_in_channel = [m for m in channel.members if m.id != owner_id and not m.bot]
        if not members_in_channel:
            await interaction.response.send_message("❌ No other users are currently in your voice channel.", ephemeral=True)
            return

        options = [
            discord.SelectOption(label=m.display_name[:100], value=str(m.id))
            for m in members_in_channel[:25]
        ]
        select = discord.ui.Select(placeholder="Select user to Mute/Unmute locally...", options=options)

        async def select_callback(select_interaction: discord.Interaction):
            # Edit the dropdown message so the user knows it's processing, and remove the menu view
            await select_interaction.response.edit_message(content="⏳ Processing mute toggle...", view=None)

            # 30-Second Auto-Delete Task for Ephemeral Followups
            async def cleanup():
                await asyncio.sleep(30)
                try:
                    await select_interaction.delete_original_response()
                except discord.HTTPException:
                    pass

            target_id = int(select.values[0])
            target = guild.get_member(target_id)

            if not target:
                await select_interaction.edit_original_response(content="❌ User no longer found.")
                asyncio.create_task(cleanup())
                return

            # Check Staff Protection
            rank_cfg = load_rank_config().get(str(guild.id), {})
            staff_ids = rank_cfg.get("staff_role_ids", [])
            target_role_ids = [r.id for r in target.roles]
            
            if any(r_id in staff_ids for r_id in target_role_ids):
                # Send DM instead of pinging the text channel
                try:
                    await target.send(
                        f"⚠️ **Security Notice:** {interaction.user.display_name} attempted to locally mute you in **{channel.name}**, "
                        f"but you are protected as a Staff member."
                    )
                except discord.HTTPException:
                    pass

                await select_interaction.edit_original_response(content="❌ You cannot mute a staff member.")
                asyncio.create_task(cleanup())
                return

            overwrite = channel.overwrites_for(target)
            is_muted = overwrite.speak is False

            now = time.time()
            action_type = "unmute" if is_muted else "mute"
            cooldown_key = (owner_id, target.id, action_type)

            cog = interaction.client.get_cog("DynamicVoice")
            last_used = cog.mute_cooldowns.get(cooldown_key, 0) if cog else 0

            if now - last_used < 600:
                time_left = int((600 - (now - last_used)) / 60) + 1
                await select_interaction.edit_original_response(
                    content=(
                        f"⏳ **Rate Limit:** You can only {action_type} this user once every 10 minutes. "
                        f"Please wait ~{time_left} more minute(s)."
                    )
                )
                asyncio.create_task(cleanup())
                return

            if cog:
                cog.mute_cooldowns[cooldown_key] = now

            overwrite.speak = None if is_muted else False
            await channel.set_permissions(target, overwrite=overwrite)

            if not is_muted:
                # Send polite but direct DM notification
                try:
                    await target.send(
                        f"🔇 You have been **locally muted** in **{channel.name}** by {interaction.user.display_name}.\n\n"
                        f"You were disconnected to apply the mute. You may rejoin the channel, but you will remain muted. "
                        f"It is highly recommended that you find another public voice channel to join."
                    )
                except discord.HTTPException:
                    pass

                # Public channel notification
                await channel.send(
                    f"🔇 {target.mention} has been **locally muted** by {interaction.user.mention} and disconnected to apply the change."
                )

                # Disconnect the user to force the Discord client to update its voice state permissions
                if target.voice and target.voice.channel == channel:
                    try:
                        await target.move_to(None, reason="Forcing local mute update")
                    except discord.HTTPException:
                        pass
                
                await select_interaction.edit_original_response(content=f"✅ Muted {target.mention} locally.")
            else:
                # Send DM instead of pinging the text channel
                try:
                    await target.send(
                        f"🔊 You have been **unmuted** in **{channel.name}** by {interaction.user.display_name}. "
                        f"You were disconnected to apply the unmute, but you may now rejoin freely."
                    )
                except discord.HTTPException:
                    pass

                # Public channel notification
                await channel.send(
                    f"🔊 {target.mention} has been **unmuted** by {interaction.user.mention} and disconnected to apply the change."
                )

                # Disconnect the user to force the Discord client to update its voice state permissions
                if target.voice and target.voice.channel == channel:
                    try:
                        await target.move_to(None, reason="Forcing local unmute update")
                    except discord.HTTPException:
                        pass
                
                await select_interaction.edit_original_response(content=f"✅ Unmuted {target.mention}.")
            
            asyncio.create_task(cleanup())

        select.callback = select_callback
        view = AutoDeleteView(interaction, timeout=30.0)
        view.add_item(select)
        await interaction.response.send_message("Select a member to toggle local channel mute:", view=view, ephemeral=True)


# -------------------------------------------------------------------------
# DYNAMIC VOICE COG
# -------------------------------------------------------------------------
class DynamicVoice(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.mute_cooldowns: dict[tuple[int, int, str], float] = {}

    async def cog_load(self):
        """Registers the persistent UI View to handle bot restarts."""
        self.bot.add_view(DynamicVoiceControlView())

    @commands.Cog.listener()
    async def on_ready(self):
        """Scans for and cleans up empty dynamic voice channels that were orphaned while the bot was offline."""
        logger.info("[DynamicVoice] 🔄 Running startup orphaned channel sweep...")
        configs = load_config()
        
        for guild in self.bot.guilds:
            cfg = configs.get(str(guild.id), {})
            active_channels = cfg.get("active_channels", {})
            
            if not active_channels:
                continue
                
            to_delete_from_config = []
            
            for ch_id_str, val in list(active_channels.items()):
                if isinstance(val, int):
                    channel = guild.get_channel(int(ch_id_str))
                    if channel:
                        owner_id = None
                        for target, ov in channel.overwrites.items():
                            if isinstance(target, discord.Member) and ov.manage_channels:
                                owner_id = target.id
                                break
                        if owner_id:
                            active_channels[ch_id_str] = {"index": val, "owner_id": owner_id}
                        else:
                            to_delete_from_config.append(ch_id_str)
                    else:
                        to_delete_from_config.append(ch_id_str)

            for ch_id_str in list(active_channels.keys()):
                if ch_id_str in to_delete_from_config:
                    continue
                    
                channel = guild.get_channel(int(ch_id_str))
                
                if not channel:
                    to_delete_from_config.append(ch_id_str)
                    continue
                    
                if isinstance(channel, discord.VoiceChannel) and len(channel.members) == 0:
                    try:
                        await channel.delete(reason="Dynamic Voice Channel empty - Startup sweep")
                        to_delete_from_config.append(ch_id_str)
                        logger.info(f"[DynamicVoice] Swept orphaned empty voice channel #{channel.name}.")
                        await asyncio.sleep(0.5) 
                    except (discord.NotFound, discord.Forbidden, discord.HTTPException) as e:
                        logger.error(f"[DynamicVoice] Error sweeping empty voice channel {channel.name}: {e}")
                        
            if to_delete_from_config:
                for ch_id_str in to_delete_from_config:
                    if ch_id_str in active_channels:
                        del active_channels[ch_id_str]
                cfg["active_channels"] = active_channels
                configs[str(guild.id)] = cfg
                save_config(configs)
                
        logger.info("[DynamicVoice] ✅ Startup orphaned channel sweep complete!")

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        """Monitors voice moves and handles channel creation & teardown."""
        guild = member.guild
        configs = load_config()
        cfg = configs.get(str(guild.id), {})

        hub_ids = cfg.get("hub_channel_ids", [])
        active_channels = cfg.get("active_channels", {})
        name_template = cfg.get("channel_name_format", "#{index}-{username}'s-Channel")

        to_delete = []
        for ch_id_str in active_channels.keys():
            if not guild.get_channel(int(ch_id_str)):
                to_delete.append(ch_id_str)
        for ch_id_str in to_delete:
            del active_channels[ch_id_str]

        # 1. NOTIFY IF USER REJOINED A CHANNEL WHILE MUTED
        if after.channel and str(after.channel.id) in active_channels:
            overwrite = after.channel.overwrites_for(member)
            if overwrite.speak is False:
                await after.channel.send(
                    f"⚠️ {member.mention}, you are currently **locally muted** in this channel.\n"
                    f"You can ask the channel owner to unmute you, but it is highly recommended that you join a different public voice channel."
                )

        # 2. USER JOINED A VOICE HUB (CREATE DYNAMIC CHANNEL)
        if after.channel and after.channel.id in hub_ids:
            hub_channel = after.channel

            used_indices = {data["index"] for data in active_channels.values() if isinstance(data, dict)}
            index_counter = 1
            while index_counter in used_indices:
                index_counter += 1

            clean_name = get_clean_username(member)
            channel_name = format_channel_name(name_template, index_counter, member)

            category = hub_channel.category
            overwrites = hub_channel.overwrites.copy()

            overwrites[member] = discord.PermissionOverwrite(
                view_channel=True,
                connect=True,
                speak=True,
                manage_channels=True,
                manage_permissions=True,
                move_members=True,
                mute_members=True,
            )

            try:
                new_channel = await guild.create_voice_channel(
                    name=channel_name,
                    category=category,
                    bitrate=hub_channel.bitrate,
                    user_limit=hub_channel.user_limit,
                    overwrites=overwrites,
                    reason=f"Dynamic Voice Channel created by {member.display_name}",
                )

                # Post control embed
                embed = discord.Embed(
                    title=f"🎙️ {clean_name}'s Channel Controls",
                    description=(
                        f"Welcome {member.mention}! You are the owner of this dynamic channel.\n\n"
                        "**Available Controls:**\n"
                        "🔒 Lock/Unlock • ✏️ Rename • 👥 Set Limit • 🌍 Region • 👑 Transfer • 🔇 Local Mute\n\n"
                        "⚠️ **Mute Feature Rules:** Do not abuse the local mute feature. Muting without a valid reason "
                        "is considered abuse and will result in the loss of this privilege. You may only mute/unmute a "
                        "specific user once per 10 minutes. *(Note: Muting/Unmuting a user will automatically disconnect them to apply the change).* "
                    ),
                    color=discord.Color.blue(),
                )
                view = DynamicVoiceControlView()
                control_msg = await new_channel.send(content=member.mention, embed=embed, view=view)

                active_channels[str(new_channel.id)] = {"index": index_counter, "owner_id": member.id, "control_msg_id": control_msg.id}
                cfg["active_channels"] = active_channels
                configs[str(guild.id)] = cfg
                save_config(configs)

                await member.move_to(new_channel)

            except (discord.Forbidden, discord.HTTPException) as e:
                logger.error(f"[DynamicVoice] Failed to create voice channel for {member.display_name}: {e}")

        # 3. USER LEFT A DYNAMIC VOICE CHANNEL (AUTO-TEARDOWN OR TRANSFER)
        if before.channel and str(before.channel.id) in active_channels:
            left_channel = before.channel
            channel_data = active_channels[str(left_channel.id)]
            
            if len(left_channel.members) == 0:
                try:
                    del active_channels[str(left_channel.id)]
                    cfg["active_channels"] = active_channels
                    configs[str(guild.id)] = cfg
                    save_config(configs)

                    await left_channel.delete(reason="Dynamic Voice Channel empty - Auto teardown")
                    logger.info(f"[DynamicVoice] Deleted empty voice channel #{left_channel.name}.")
                except (discord.NotFound, discord.Forbidden, discord.HTTPException) as e:
                    logger.error(f"[DynamicVoice] Error deleting empty voice channel: {e}")
                    
            # If the person who left was the owner, but people are still inside
            elif member.id == channel_data.get("owner_id"):
                eligible_members = [m for m in left_channel.members if not m.bot]
                if eligible_members:
                    # Pick the user with the highest top_role position
                    new_owner = max(eligible_members, key=lambda m: m.top_role.position)
                    
                    try:
                        # Strip old owner's permissions
                        old_overwrite = left_channel.overwrites_for(member)
                        old_overwrite.manage_channels = None
                        old_overwrite.manage_permissions = None
                        old_overwrite.move_members = None
                        old_overwrite.mute_members = None
                        await left_channel.set_permissions(member, overwrite=old_overwrite)

                        # Grant new owner's permissions
                        new_overwrite = left_channel.overwrites_for(new_owner)
                        new_overwrite.view_channel = True
                        new_overwrite.connect = True
                        new_overwrite.speak = True
                        new_overwrite.manage_channels = True
                        new_overwrite.manage_permissions = True
                        new_overwrite.move_members = True
                        new_overwrite.mute_members = True
                        await left_channel.set_permissions(new_owner, overwrite=new_overwrite)

                        # Update config
                        active_channels[str(left_channel.id)]["owner_id"] = new_owner.id
                        cfg["active_channels"] = active_channels
                        configs[str(guild.id)] = cfg
                        save_config(configs)

                        # Rename channel (only if it still matched the old owner's default template)
                        index = channel_data.get("index")
                        expected_old_name = format_channel_name(name_template, index, member)
                        if left_channel.name == expected_old_name:
                            new_channel_name = format_channel_name(name_template, index, new_owner)
                            await left_channel.edit(name=new_channel_name)

                        # Fetch and update the original control panel embed
                        control_msg_id = channel_data.get("control_msg_id")
                        if control_msg_id:
                            try:
                                control_msg = await left_channel.fetch_message(control_msg_id)
                                if control_msg and control_msg.embeds:
                                    embed = control_msg.embeds[0]
                                    clean_name = get_clean_username(new_owner)
                                    embed.title = f"🎙️ {clean_name}'s Channel Controls"
                                    embed.description = (
                                        f"Welcome {new_owner.mention}! You are the owner of this dynamic channel.\n\n"
                                        "**Available Controls:**\n"
                                        "🔒 Lock/Unlock • ✏️ Rename • 👥 Set Limit • 🌍 Region • 👑 Transfer • 🔇 Local Mute\n\n"
                                        "⚠️ **Mute Feature Rules:** Do not abuse the local mute feature. Muting without a valid reason "
                                        "is considered abuse and will result in the loss of this privilege. You may only mute/unmute a "
                                        "specific user once per 10 minutes. *(Note: Muting/Unmuting a user will automatically disconnect them to apply the change).* "
                                    )
                                    await control_msg.edit(content=new_owner.mention, embed=embed)
                            except discord.HTTPException as e:
                                logger.error(f"[DynamicVoice] Failed to update control panel on auto-transfer: {e}")

                        # Send announcement to the channel
                        await left_channel.send(
                            f"👑 **Ownership Auto-Transferred!**\n"
                            f"{member.display_name} left the channel, so ownership has been automatically transferred to the highest-ranked member: {new_owner.mention}."
                        )
                    except discord.HTTPException as e:
                        logger.error(f"[DynamicVoice] Failed to auto-transfer ownership: {e}")


    # -------------------------------------------------------------------------
    # COMMANDS
    # -------------------------------------------------------------------------
    @app_commands.command(
        name="setup_voice_hub",
        description="Creates or registers a Join-to-Create Voice Hub channel.",
    )
    @app_commands.checks.has_permissions(manage_channels=True)
    @app_commands.describe(
        existing_channel="Optional: Select an existing voice channel to convert into a Hub",
        mute_restricted_role="Optional: Role for users banned from using the Mute feature",
        channel_name_format="Optional: Name format (Use {index} & {username}). Default: #{index}-{username}'s-Channel"
    )
    async def setup_voice_hub(
        self, 
        interaction: discord.Interaction, 
        existing_channel: discord.VoiceChannel | None = None,
        mute_restricted_role: discord.Role | None = None,
        channel_name_format: str | None = None
    ):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild

        configs = load_config()
        guild_cfg = configs.get(str(guild.id), {"hub_channel_ids": [], "active_channels": {}})

        target_hub = existing_channel

        if not target_hub:
            try:
                target_hub = await guild.create_voice_channel(
                    name="➕ Join to Create VC",
                    reason=f"Voice Hub created by {interaction.user}",
                )
            except discord.HTTPException as e:
                await interaction.followup.send(f"❌ Failed to create voice channel: `{e}`", ephemeral=True)
                return

        if "hub_channel_ids" not in guild_cfg:
            guild_cfg["hub_channel_ids"] = []
            
        if target_hub.id not in guild_cfg["hub_channel_ids"]:
            guild_cfg["hub_channel_ids"].append(target_hub.id)

        if mute_restricted_role:
            guild_cfg["mute_restricted_role_id"] = mute_restricted_role.id

        fmt_to_save = channel_name_format.strip() if channel_name_format else "#{index}-{username}'s-Channel"
        guild_cfg["channel_name_format"] = fmt_to_save

        configs[str(guild.id)] = guild_cfg
        save_config(configs)

        restricted_msg = f"\n• **Mute Restricted Role:** {mute_restricted_role.mention}" if mute_restricted_role else ""

        await interaction.followup.send(
            f"✅ **Voice Hub Active!**\n"
            f"• **Hub Channel:** {target_hub.mention}\n"
            f"• **Channel Name Template:** `{fmt_to_save}`"
            f"{restricted_msg}",
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(DynamicVoice(bot))