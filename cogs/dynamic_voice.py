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

# Day 1 Starter Pack. Deliberately using "europe" instead of "rotterdam" so you can trigger the 400 error!
DEFAULT_REGIONS = [
    "brazil", "hongkong", "india", "japan", "europe", 
    "singapore", "south-korea", "southafrica", "sydney", 
    "us-central", "us-east", "us-south", "us-west"
]

CONTROL_PANEL_DESC = (
    "**Available Controls:**\n"
    "🔒 **Lock / Unlock:** Restrict or allow other members to join your channel.\n"
    "✏️ **Rename:** Change the name of your voice channel.\n"
    "👥 **Set Limit:** Cap the maximum number of users (0 for unlimited, up to 99).\n"
    "🌍 **Region:** Change the server voice region to improve your ping.\n"
    "👑 **Transfer:** Pass ownership of this channel to another member inside it.\n"
    "🔇 **Local Mute:** Forcefully mute or unmute a specific user in your channel.\n"
    "🔕 **Toggle Ping:** Opt in or out of the bot pinging you when your channel is created.\n\n"
    "⚠️ **Mute Feature Rules:** Do not abuse the local mute feature. Muting without a valid reason "
    "is considered abuse and will result in the loss of this privilege. You may only mute/unmute a "
    "specific user once per 10 minutes."
)

def get_config_path(guild_id: int, filename: str) -> str:
    path = f"data/{guild_id}"
    os.makedirs(path, exist_ok=True)
    return f"{path}/{filename}"


def load_config(guild_id: int) -> dict:
    filepath = get_config_path(guild_id, "dynamic_voice_config.json")
    if os.path.exists(filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                pass
    return {}


def save_config(guild_id: int, data: dict):
    filepath = get_config_path(guild_id, "dynamic_voice_config.json")
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)


def load_rank_config(guild_id: int) -> dict:
    filepath = get_config_path(guild_id, "rank_system_config.json")
    if os.path.exists(filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                pass
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


def get_region_label(val: str) -> str:
    """Formats internal region tags into nice readable labels."""
    labels = {
        "rotterdam": "Rotterdam (Europe)",
        "hongkong": "Hong Kong",
        "south-korea": "South Korea",
        "southafrica": "South Africa",
        "europe": "Europe (Test Error)" # Deliberate trap to let you test the auto-updater
    }
    return labels.get(val, val.replace("-", " ").title())


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

    async def _get_vc_data(self, interaction: discord.Interaction) -> tuple[int | None, int | None, bool]:
        """Fetches the owner ID, index, and staff status. Returns (owner_id, index, is_staff)."""
        cfg = load_config(interaction.guild_id)
        channel_data = cfg.get("active_channels", {}).get(str(interaction.channel_id))

        if not channel_data:
            await interaction.response.send_message(
                "❌ This channel is no longer tracked as a dynamic voice channel.", ephemeral=True
            )
            return None, None, False

        owner_id = channel_data.get("owner_id")
        index = channel_data.get("index")

        # Check for Staff Roles
        rank_cfg = load_rank_config(interaction.guild_id)
        staff_ids = rank_cfg.get("staff_role_ids", [])
        
        is_staff = any(r.id in staff_ids for r in interaction.user.roles)
        is_admin = interaction.user.guild_permissions.administrator
        is_owner = interaction.user.id == owner_id

        if not (is_owner or is_staff or is_admin):
            await interaction.response.send_message(
                "❌ Only the channel owner or server Staff can use these controls!", ephemeral=True
            )
            return None, None, False

        return owner_id, index, (is_staff or is_admin)

    @discord.ui.button(label="Lock / Unlock", style=discord.ButtonStyle.secondary, emoji="🔒", custom_id="dvc_lock", row=0)
    async def toggle_lock(self, interaction: discord.Interaction, button: discord.ui.Button):
        owner_id, index, is_staff = await self._get_vc_data(interaction)
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
        owner_id, index, is_staff = await self._get_vc_data(interaction)
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
        owner_id, index, is_staff = await self._get_vc_data(interaction)
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
        owner_id, index, is_staff = await self._get_vc_data(interaction)
        if not owner_id: return

        guild_cfg = load_config(interaction.guild.id)
        valid_regions = guild_cfg.get("valid_voice_regions", DEFAULT_REGIONS)

        options = [
            discord.SelectOption(label="Automatic", value="auto", description="Best region automatically selected")
        ]

        for region in valid_regions[:24]:
            options.append(discord.SelectOption(label=get_region_label(region), value=region))

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
            region_val = None if val == "auto" else val
            try:
                await interaction.channel.edit(rtc_region=region_val)
                display_name = "Automatic" if val == "auto" else get_region_label(val)
                await select_interaction.edit_original_response(content=f"✅ Voice region successfully set to **{display_name}**.", view=None)
            except discord.HTTPException as e:
                if e.status == 400 and "rtc_region" in str(e) and "Value must be one of" in str(e):
                    match = re.search(r"Value must be one of \((.*?)\)", str(e))
                    if match:
                        raw_list = match.group(1).replace("'", "").replace(" ", "")
                        new_regions = raw_list.split(",")
                        
                        g_cfg = load_config(interaction.guild.id)
                        g_cfg["valid_voice_regions"] = new_regions
                        save_config(interaction.guild.id, g_cfg)
                        
                        logger.info(f"[DynamicVoice] Extracted and updated valid voice regions from API error: {new_regions}")
                        await select_interaction.edit_original_response(
                            content="❌ That region is currently unavailable. The region list has been automatically refreshed behind the scenes—please click the Region button and try again!", 
                            view=None
                        )
                        asyncio.create_task(cleanup())
                        return
                        
                await select_interaction.edit_original_response(content=f"❌ Failed to set region: {e}", view=None)
            
            asyncio.create_task(cleanup())

        select.callback = select_callback
        view = AutoDeleteView(interaction, timeout=30.0)
        view.add_item(select)
        await interaction.response.send_message("Select a new voice region:", view=view, ephemeral=True)

    @discord.ui.button(label="Transfer", style=discord.ButtonStyle.primary, emoji="👑", custom_id="dvc_transfer", row=1)
    async def transfer_ownership(self, interaction: discord.Interaction, button: discord.ui.Button):
        owner_id, index, is_staff = await self._get_vc_data(interaction)
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
            await select_interaction.response.edit_message(content="⏳ Processing transfer...", view=None)
            
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

            if old_owner:
                old_overwrite = channel.overwrites_for(old_owner)
                old_overwrite.manage_channels = None
                old_overwrite.manage_permissions = None
                old_overwrite.move_members = None
                old_overwrite.mute_members = None
                await channel.set_permissions(old_owner, overwrite=old_overwrite)

            new_overwrite = channel.overwrites_for(new_owner)
            new_overwrite.view_channel = True
            new_overwrite.connect = True
            new_overwrite.speak = True
            new_overwrite.manage_channels = True
            new_overwrite.manage_permissions = True
            new_overwrite.move_members = True
            new_overwrite.mute_members = True
            await channel.set_permissions(new_owner, overwrite=new_overwrite)

            cfg = load_config(guild.id)
            template = cfg.get("channel_name_format", "#{index}-{username}'s-Channel")

            expected_old_name = format_channel_name(template, index, old_owner) if old_owner else ""
            if channel.name == expected_old_name:
                new_channel_name = format_channel_name(template, index, new_owner)
                await channel.edit(name=new_channel_name)

            cfg["active_channels"][str(channel.id)]["owner_id"] = new_owner.id
            save_config(guild.id, cfg)

            embed = interaction.message.embeds[0]
            clean_name = get_clean_username(new_owner)
            embed.title = f"🎙️ {clean_name}'s Channel Controls"
            embed.description = f"Welcome {new_owner.mention}! You are the owner of this dynamic channel.\n\n{CONTROL_PANEL_DESC}"
            await interaction.message.edit(content=new_owner.mention, embed=embed)

            await select_interaction.edit_original_response(content=f"✅ Ownership transferred to {new_owner.mention}.")
            asyncio.create_task(cleanup())

        select.callback = select_callback
        view = AutoDeleteView(interaction, timeout=30.0)
        view.add_item(select)
        await interaction.response.send_message("Select a member to transfer ownership to (Staff can select themselves):", view=view, ephemeral=True)

    @discord.ui.button(label="Local Mute", style=discord.ButtonStyle.danger, emoji="🔇", custom_id="dvc_mute", row=1)
    async def local_mute(self, interaction: discord.Interaction, button: discord.ui.Button):
        owner_id, index, is_staff = await self._get_vc_data(interaction)
        if not owner_id: return

        guild = interaction.guild
        channel = interaction.channel

        cfg = load_config(guild.id)
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
            await select_interaction.response.edit_message(content="⏳ Processing mute toggle...", view=None)

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

            rank_cfg = load_rank_config(guild.id)
            staff_ids = rank_cfg.get("staff_role_ids", [])
            target_role_ids = [r.id for r in target.roles]
            
            if any(r_id in staff_ids for r_id in target_role_ids):
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
                try:
                    await target.send(
                        f"🔇 You have been **locally muted** in **{channel.name}** by {interaction.user.display_name}.\n\n"
                        f"You were disconnected to apply the mute. You may rejoin the channel, but you will remain muted. "
                        f"It is highly recommended that you find another public voice channel to join."
                    )
                except discord.HTTPException:
                    pass

                await channel.send(
                    f"🔇 {target.mention} has been **locally muted** by {interaction.user.mention} and disconnected to apply the change."
                )

                if target.voice and target.voice.channel == channel:
                    try:
                        await target.move_to(None, reason="Forcing local mute update")
                    except discord.HTTPException:
                        pass
                
                await select_interaction.edit_original_response(content=f"✅ Muted {target.mention} locally.")
            else:
                try:
                    await target.send(
                        f"🔊 You have been **unmuted** in **{channel.name}** by {interaction.user.display_name}. "
                        f"You were disconnected to apply the unmute, but you may now rejoin freely."
                    )
                except discord.HTTPException:
                    pass

                await channel.send(
                    f"🔊 {target.mention} has been **unmuted** by {interaction.user.mention} and disconnected to apply the change."
                )

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

    @discord.ui.button(label="Toggle Ping", style=discord.ButtonStyle.success, emoji="🔕", custom_id="dvc_ping", row=1)
    async def toggle_ping(self, interaction: discord.Interaction, button: discord.ui.Button):
        owner_id, index, is_staff = await self._get_vc_data(interaction)
        if not owner_id: return

        # Ensure Staff can't press this to mute the owner's pings for them
        if interaction.user.id != owner_id:
            await interaction.response.send_message(
                "❌ Only the actual channel owner can toggle their ping setting.", ephemeral=True
            )
            return

        cfg = load_config(interaction.guild.id)
        role_id = cfg.get("ping_muted_role_id")
        
        if not role_id:
            await interaction.response.send_message(
                "❌ The Ping Muted role hasn't been configured by an Admin yet! Have them run `/setup_voice_hub`.", ephemeral=True
            )
            return

        target_role = interaction.guild.get_role(role_id)
        if not target_role:
            await interaction.response.send_message(
                "❌ The configured Ping Muted role was deleted from the server.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)
        
        if target_role in interaction.user.roles:
            await interaction.user.remove_roles(target_role, reason="VC Ping Toggle via Panel")
            await interaction.followup.send("🔊 You will now be **pinged** when creating a new dynamic channel.", ephemeral=True)
        else:
            await interaction.user.add_roles(target_role, reason="VC Ping Toggle via Panel")
            await interaction.followup.send("🔇 You will **no longer be pinged** when creating a new dynamic channel.", ephemeral=True)


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
        
        for guild in self.bot.guilds:
            cfg = load_config(guild.id)
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
                save_config(guild.id, cfg)
                
        logger.info("[DynamicVoice] ✅ Startup orphaned channel sweep complete!")

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        """Monitors voice moves and handles channel creation & teardown."""
        if getattr(self.bot, "is_passive", False): return # 🛑 Passive Mode Check

        guild = member.guild
        cfg = load_config(guild.id)

        hub_ids = cfg.get("hub_channel_ids", [])
        active_channels = cfg.get("active_channels", {})
        name_template = cfg.get("channel_name_format", "#{index}-{username}'s-Channel")

        to_delete = []
        for ch_id_str in active_channels.keys():
            if not guild.get_channel(int(ch_id_str)):
                to_delete.append(ch_id_str)
        for ch_id_str in to_delete:
            del active_channels[ch_id_str]

        if after.channel and str(after.channel.id) in active_channels:
            overwrite = after.channel.overwrites_for(member)
            if overwrite.speak is False:
                await after.channel.send(
                    f"⚠️ {member.mention}, you are currently **locally muted** in this channel.\n"
                    f"You can ask the channel owner to unmute you, but it is highly recommended that you join a different public voice channel."
                )

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

                embed = discord.Embed(
                    title=f"🎙️ {clean_name}'s Channel Controls",
                    description=f"Welcome {member.mention}! You are the owner of this dynamic channel.\n\n{CONTROL_PANEL_DESC}",
                    color=discord.Color.blue(),
                )
                view = DynamicVoiceControlView()
                
                # Check if the user has opted out of the ping
                ping_role_id = cfg.get("ping_muted_role_id")
                is_ping_muted = ping_role_id and ping_role_id in [r.id for r in member.roles]
                
                # Format the message based on their preference
                message_content = f"Welcome to your channel, {member.display_name}!" if is_ping_muted else member.mention

                control_msg = await new_channel.send(content=message_content, embed=embed, view=view)

                active_channels[str(new_channel.id)] = {"index": index_counter, "owner_id": member.id, "control_msg_id": control_msg.id}
                cfg["active_channels"] = active_channels
                save_config(guild.id, cfg)

                await member.move_to(new_channel)

            except (discord.Forbidden, discord.HTTPException) as e:
                logger.error(f"[DynamicVoice] Failed to create voice channel for {member.display_name}: {e}")

        if before.channel and before.channel != after.channel and str(before.channel.id) in active_channels:
            left_channel = before.channel
            channel_data = active_channels[str(left_channel.id)]
            
            if len(left_channel.members) == 0:
                try:
                    del active_channels[str(left_channel.id)]
                    cfg["active_channels"] = active_channels
                    save_config(guild.id, cfg)

                    await left_channel.delete(reason="Dynamic Voice Channel empty - Auto teardown")
                    logger.info(f"[DynamicVoice] Deleted empty voice channel #{left_channel.name}.")
                except (discord.NotFound, discord.Forbidden, discord.HTTPException) as e:
                    logger.error(f"[DynamicVoice] Error deleting empty voice channel: {e}")
                    
            elif member.id == channel_data.get("owner_id"):
                eligible_members = [m for m in left_channel.members if not m.bot]
                if eligible_members:
                    new_owner = max(eligible_members, key=lambda m: m.top_role.position)
                    
                    try:
                        old_overwrite = left_channel.overwrites_for(member)
                        old_overwrite.manage_channels = None
                        old_overwrite.manage_permissions = None
                        old_overwrite.move_members = None
                        old_overwrite.mute_members = None
                        await left_channel.set_permissions(member, overwrite=old_overwrite)

                        new_overwrite = left_channel.overwrites_for(new_owner)
                        new_overwrite.view_channel = True
                        new_overwrite.connect = True
                        new_overwrite.speak = True
                        new_overwrite.manage_channels = True
                        new_overwrite.manage_permissions = True
                        new_overwrite.move_members = True
                        new_overwrite.mute_members = True
                        await left_channel.set_permissions(new_owner, overwrite=new_overwrite)

                        active_channels[str(left_channel.id)]["owner_id"] = new_owner.id
                        cfg["active_channels"] = active_channels
                        save_config(guild.id, cfg)

                        index = channel_data.get("index")
                        expected_old_name = format_channel_name(name_template, index, member)
                        if left_channel.name == expected_old_name:
                            new_channel_name = format_channel_name(name_template, index, new_owner)
                            await left_channel.edit(name=new_channel_name)

                        control_msg_id = channel_data.get("control_msg_id")
                        if control_msg_id:
                            try:
                                control_msg = await left_channel.fetch_message(control_msg_id)
                                if control_msg and control_msg.embeds:
                                    embed = control_msg.embeds[0]
                                    clean_name = get_clean_username(new_owner)
                                    embed.title = f"🎙️ {clean_name}'s Channel Controls"
                                    embed.description = f"Welcome {new_owner.mention}! You are the owner of this dynamic channel.\n\n{CONTROL_PANEL_DESC}"
                                    await control_msg.edit(content=new_owner.mention, embed=embed)
                            except discord.HTTPException as e:
                                logger.error(f"[DynamicVoice] Failed to update control panel on auto-transfer: {e}")

                        await left_channel.send(
                            f"👑 **Ownership Auto-Transferred!**\n"
                            f"{member.display_name} left the channel, so ownership has been automatically transferred to the highest-ranked member: {new_owner.mention}."
                        )
                    except discord.HTTPException as e:
                        logger.error(f"[DynamicVoice] Failed to auto-transfer ownership: {e}")


    @app_commands.command(
        name="setup_voice_hub",
        description="Creates or registers a Join-to-Create Voice Hub channel.",
    )
    @app_commands.checks.has_permissions(manage_channels=True)
    @app_commands.describe(
        existing_channel="Optional: Select an existing voice channel to convert into a Hub",
        mute_restricted_role="Optional: Role for users banned from using the Mute feature",
        ping_muted_role="Optional: Role for users who opted out of the bot ping on channel creation",
        channel_name_format="Optional: Name format (Use {index} & {username}). Default: #{index}-{username}'s-Channel"
    )
    async def setup_voice_hub(
        self, 
        interaction: discord.Interaction, 
        existing_channel: discord.VoiceChannel | None = None,
        mute_restricted_role: discord.Role | None = None,
        ping_muted_role: discord.Role | None = None,
        channel_name_format: str | None = None
    ):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild

        guild_cfg = load_config(guild.id)

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

        if ping_muted_role:
            guild_cfg["ping_muted_role_id"] = ping_muted_role.id

        fmt_to_save = channel_name_format.strip() if channel_name_format else "#{index}-{username}'s-Channel"
        guild_cfg["channel_name_format"] = fmt_to_save

        save_config(guild.id, guild_cfg)

        restricted_msg = f"\n• **Mute Restricted Role:** {mute_restricted_role.mention}" if mute_restricted_role else ""
        ping_role_msg = f"\n• **Ping Muted Role:** {ping_muted_role.mention}" if ping_muted_role else ""

        await interaction.followup.send(
            f"✅ **Voice Hub Active!**\n"
            f"• **Hub Channel:** {target_hub.mention}\n"
            f"• **Channel Name Template:** `{fmt_to_save}`"
            f"{restricted_msg}"
            f"{ping_role_msg}",
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(DynamicVoice(bot))