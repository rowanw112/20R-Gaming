import logging
import os
import json
import io
import re
import datetime
import asyncio
import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger(__name__)

# -------------------------------------------------------------------------
# CONFIGURATION HELPERS
# -------------------------------------------------------------------------
def get_config_path(guild_id: int) -> str:
    path = f"data/{guild_id}"
    os.makedirs(path, exist_ok=True)
    return f"{path}/ticket_system_config.json"

def load_ticket_config(guild_id: int) -> dict:
    filepath = get_config_path(guild_id)
    if not os.path.exists(filepath):
        return {"panels": {}, "active_tickets": {}}
    with open(filepath, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {"panels": {}, "active_tickets": {}}

def save_ticket_config(guild_id: int, data: dict):
    filepath = get_config_path(guild_id)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

def parse_role_ids(guild: discord.Guild, input_str: str | None) -> list[int]:
    if not input_str or not input_str.strip(): return []
    valid_ids = []
    raw_tokens = re.findall(r"\d+", input_str)
    for token in raw_tokens:
        role_id = int(token)
        if guild.get_role(role_id) and role_id not in valid_ids:
            valid_ids.append(role_id)
    possible_names = [name.strip().lower() for name in input_str.split(",")]
    for role in guild.roles:
        if role.name.lower() in possible_names and role.id not in valid_ids:
            valid_ids.append(role.id)
    return valid_ids

def build_panel_embed(system_name: str, thumbnail_url: str = None) -> discord.Embed:
    embed = discord.Embed(
        title=f"🛡️ {system_name} Support & Tickets",
        description="Please select an option from the menu below to open a private ticket with our staff team. Abuse of the ticket system may result in a ban.",
        color=discord.Color.from_str("#2b2d31")
    )
    if thumbnail_url:
        embed.set_thumbnail(url=thumbnail_url)
    embed.add_field(name="‼️ Report a Player", value="-# Report rule-breaking, toxicity, or other misconduct.", inline=False)
    embed.add_field(name="🔨 Appeal a Ban", value=f"-# Talk to the admins and appeal a ban on the {system_name} server.", inline=False)
    embed.add_field(name="📩 Whitelisting", value="-# Request to be whitelisted for prioritized server access.", inline=False)
    return embed


# -------------------------------------------------------------------------
# TICKET TRANSCRIPT & ALERT HELPERS
# -------------------------------------------------------------------------
async def generate_transcript(thread: discord.Thread, owner: discord.Member | None) -> tuple[io.BytesIO, str]:
    lines = []
    lines.append(f"Ticket Name: {thread.name}")
    lines.append(f"Created At: {thread.created_at.strftime('%Y-%m-%d %H:%M:%S') if thread.created_at else 'Unknown'}")
    
    if owner:
        lines.append(f"Creator: {owner} (ID: {owner.id})")
        lines.append(f"Account Created: {owner.created_at.strftime('%Y-%m-%d %H:%M:%S') if owner.created_at else 'Unknown'}")
        lines.append(f"Server Joined: {owner.joined_at.strftime('%Y-%m-%d %H:%M:%S') if getattr(owner, 'joined_at', None) else 'Unknown'}")
    
    lines.append("\n" + "=" * 50)
    lines.append("TRANSCRIPT LOG")
    lines.append("=" * 50 + "\n")
    
    async for message in thread.history(limit=None, oldest_first=True):
        timestamp = message.created_at.strftime("%Y-%m-%d %H:%M:%S")
        lines.append(f"[{timestamp}] {message.author} ({message.author.id}):")
        if message.clean_content: lines.append(f"  {message.clean_content}")
        for att in message.attachments: lines.append(f"  [Attachment: {att.url}]")
        lines.append("")

    transcript_text = "\n".join(lines)
    buffer = io.BytesIO(transcript_text.encode('utf-8'))
    timestamp_str = discord.utils.utcnow().strftime("%Y-%m-%d_%H%M%S")
    return buffer, f"transcript_{thread.name}_{timestamp_str}.txt"

async def update_ticket_alert(guild: discord.Guild, ticket_data: dict, status: str, actor: discord.Member = None):
    """Updates the staff dashboard alert embed silently."""
    alert_msg_id = ticket_data.get("alert_message_id")
    loc_id = ticket_data.get("alert_location_id")
    if not alert_msg_id or not loc_id: return
    
    target = guild.get_channel(loc_id) or guild.get_thread(loc_id)
    if not target: return
    
    try:
        msg = await target.fetch_message(alert_msg_id)
        embed = msg.embeds[0]
        owner_id = ticket_data.get("owner_id")
        thread_id = ticket_data.get("thread_id")
        
        desc = f"**Creator:** <@{owner_id}>\n**Thread:** <#{thread_id}>\n"
        if status == "claimed":
            desc += f"**Status:** 🔵 Claimed by {actor.mention}"
            embed.color = discord.Color.blue()
        elif status == "closed":
            desc += f"**Status:** 🟢 Closed by {actor.mention}"
            embed.color = discord.Color.green()
        elif status == "deleted":
            desc += f"**Status:** 🔴 Deleted by {actor.mention}"
            embed.color = discord.Color.dark_grey()
        elif status == "abandoned":
            desc += f"**Status:** 🔴 Auto-Deleted (User Left Thread)"
            embed.color = discord.Color.dark_grey()
            
        embed.description = desc
        await msg.edit(embed=embed)
    except discord.HTTPException:
        pass


# -------------------------------------------------------------------------
# TICKET MODALS
# -------------------------------------------------------------------------
class TicketModal(discord.ui.Modal):
    def __init__(self, title: str, category: str, system_name: str, support_role_ids: list[int], transcript_channel_id: int | None, alert_channel_id: int | None):
        super().__init__(title=title)
        self.category = category
        self.system_name = system_name
        self.support_role_ids = support_role_ids
        self.transcript_channel_id = transcript_channel_id
        self.alert_channel_id = alert_channel_id

    async def on_submit(self, interaction: discord.Interaction):
        guild = interaction.guild
        member = interaction.user
        
        cfg = load_ticket_config(guild.id)
        active_tickets = cfg.get("active_tickets", {})
        
        # 1. Ticket Limit Check (Anti-Spam) - NOW CHECKS CATEGORY
        for tid, tdata in active_tickets.items():
            if (tdata.get("owner_id") == member.id and 
                tdata.get("system_name") == self.system_name and 
                tdata.get("category") == self.category):
                return await interaction.response.send_message(
                    f"❌ You already have an active **{self.category}** ticket open for {self.system_name}. Please wait until it is closed before opening another.", 
                    ephemeral=True
                )
                
        await interaction.response.defer(ephemeral=True)
        channel = interaction.channel
        
        if not isinstance(channel, discord.TextChannel):
            return await interaction.followup.send("❌ Tickets must be opened in a standard text channel.", ephemeral=True)

        clean_name = re.sub(r"^\[.*?\]\s*|^\(.*?\)\s*", "", member.display_name).strip()
        prefix_map = {"Report User": "Report", "Appeal a Ban": "Appeal", "Whitelisting": "Whitelist"}
        thread_name = f"{prefix_map.get(self.category, 'Ticket')}-{clean_name}"
        
        try:
            thread = await channel.create_thread(
                name=thread_name, type=discord.ChannelType.private_thread, invitable=False, auto_archive_duration=10080
            )
        except discord.HTTPException as e:
            return await interaction.followup.send(f"❌ Failed to create ticket thread: {e}", ephemeral=True)

        await thread.add_user(member)
        
        # 2. Setup Staff Alert Message
        alert_msg = None
        alert_location_id = None
        if self.alert_channel_id:
            alert_chan = guild.get_channel(self.alert_channel_id)
            if alert_chan and isinstance(alert_chan, discord.TextChannel):
                alert_target = alert_chan
                keyword = prefix_map.get(self.category, "").lower()
                found_thread = False
                
                # Automatically route into sub-threads if they exist in the alert channel
                for t in alert_chan.threads:
                    if keyword in t.name.lower():
                        alert_target = t
                        found_thread = True
                        break
                
                # Auto-create the thread if it wasn't found
                if not found_thread:
                    try:
                        alert_target = await alert_chan.create_thread(
                            name=f"{prefix_map.get(self.category, 'Tickets')} Alerts",
                            type=discord.ChannelType.public_thread
                        )
                    except discord.HTTPException:
                        pass # Fallback to the main channel if it fails
                        
                alert_embed = discord.Embed(
                    title=f"🎫 New Ticket | {self.system_name}",
                    description=f"**Creator:** {member.mention}\n**Thread:** {thread.mention}\n**Status:** 🟡 Unclaimed",
                    color=discord.Color.yellow()
                )
                for item in self.children:
                    if isinstance(item, discord.ui.TextInput):
                        alert_embed.add_field(name=item.label, value=item.value or "N/A", inline=False)
                        
                try:
                    alert_msg = await alert_target.send(embed=alert_embed, silent=True)
                    alert_location_id = alert_target.id
                except discord.HTTPException:
                    pass

        # 3. Save to Config
        cfg["active_tickets"][str(thread.id)] = {
            "thread_id": thread.id,
            "owner_id": member.id,
            "support_role_ids": self.support_role_ids,
            "system_name": self.system_name,
            "category": self.category, # Saves the ticket type for the anti-spam check
            "transcript_channel_id": self.transcript_channel_id,
            "alert_message_id": alert_msg.id if alert_msg else None,
            "alert_location_id": alert_location_id
        }
        save_ticket_config(guild.id, cfg)

        embed = discord.Embed(title=f"🎫 {self.category} | {self.system_name}", color=discord.Color.blue(), timestamp=discord.utils.utcnow())
        embed.set_author(name=member.display_name, icon_url=member.display_avatar.url)
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="Account Created", value=f"<t:{int(member.created_at.timestamp())}:R>", inline=True)
        if getattr(member, 'joined_at', None):
            embed.add_field(name="Joined Server", value=f"<t:{int(member.joined_at.timestamp())}:R>", inline=True)
        
        for item in self.children:
            if isinstance(item, discord.ui.TextInput):
                embed.add_field(name=item.label, value=item.value or "N/A", inline=False)

        support_mentions = " ".join([f"<@&{rid}>" for rid in self.support_role_ids]) if self.support_role_ids else "Support Staff"
        intro_content = f"👋 {member.mention} | {support_mentions}\n\n"
        
        if self.category == "Report User": intro_content += "**If you are reporting a player, let us know what is going on and share any video/screenshot evidence you have below.**"
        elif self.category == "Appeal a Ban": intro_content += "**A staff member will review your ban appeal shortly. Please ensure your SteamID is correct.**"
        elif self.category == "Whitelisting": intro_content += "**Please wait while an admin reviews your whitelist request and links your Discord.**"

        await thread.send(content=intro_content, embed=embed, view=TicketManagementView())
        await interaction.followup.send(f"✅ Ticket created! Click here to view it: {thread.mention}", ephemeral=True)


class ReportModal(TicketModal):
    def __init__(self, sys_name: str, support_ids: list[int], log_id: int | None, alert_id: int | None):
        super().__init__(title="Report a Player", category="Report User", system_name=sys_name, support_role_ids=support_ids, transcript_channel_id=log_id, alert_channel_id=alert_id)
        self.add_item(discord.ui.TextInput(label="Reported Player Name / ID", placeholder="Who are you reporting?", required=True, max_length=100))
        self.add_item(discord.ui.TextInput(label="Reason for Report", placeholder="What rule was broken?", style=discord.TextStyle.paragraph, required=True, max_length=500))

class AppealModal(TicketModal):
    def __init__(self, sys_name: str, support_ids: list[int], log_id: int | None, alert_id: int | None):
        super().__init__(title="Appeal a Ban", category="Appeal a Ban", system_name=sys_name, support_role_ids=support_ids, transcript_channel_id=log_id, alert_channel_id=alert_id)
        self.add_item(discord.ui.TextInput(label="SteamID64", placeholder="Found at https://steamid.io/lookup", required=True, max_length=100))
        self.add_item(discord.ui.TextInput(label="Why were you banned?", style=discord.TextStyle.paragraph, required=True, max_length=300))
        self.add_item(discord.ui.TextInput(label="Why should you be unbanned?", style=discord.TextStyle.paragraph, required=True, max_length=500))

class WhitelistModal(TicketModal):
    def __init__(self, sys_name: str, support_ids: list[int], log_id: int | None, alert_id: int | None):
        super().__init__(title="Whitelisting Request", category="Whitelisting", system_name=sys_name, support_role_ids=support_ids, transcript_channel_id=log_id, alert_channel_id=alert_id)
        self.add_item(discord.ui.TextInput(label="SteamID64", placeholder="Found at https://steamid.io/lookup", required=True, max_length=100))
        self.add_item(discord.ui.TextInput(label="In-Game Name", required=True, max_length=100))


# -------------------------------------------------------------------------
# INTERACTIVE VIEWS
# -------------------------------------------------------------------------
class TicketPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.select(
        placeholder="Select a Ticket Option...", min_values=1, max_values=1,
        options=[
            discord.SelectOption(label="Make a report", description="Report another player", emoji="‼️", value="report"),
            discord.SelectOption(label="Appeal a ban", description="Appeal a server ban", emoji="🔨", value="appeal"),
            discord.SelectOption(label="Whitelisting", description="Request to be whitelisted", emoji="📩", value="whitelist")
        ], custom_id="dynamic_ticket_dropdown"
    )
    async def ticket_dropdown(self, interaction: discord.Interaction, select: discord.ui.Select):
        cfg = load_ticket_config(interaction.guild_id)
        panel_data = cfg.get("panels", {}).get(str(interaction.message.id))
        if not panel_data: return await interaction.response.send_message("❌ This panel is no longer actively tracked in the database.", ephemeral=True)

        sys_name = panel_data.get("system_name", "Support")
        roles = panel_data.get("support_role_ids", [])
        log_chan = panel_data.get("transcript_channel_id")
        alert_chan = panel_data.get("alert_channel_id")
        
        choice = select.values[0]
        if choice == "report": await interaction.response.send_modal(ReportModal(sys_name, roles, log_chan, alert_chan))
        elif choice == "appeal": await interaction.response.send_modal(AppealModal(sys_name, roles, log_chan, alert_chan))
        elif choice == "whitelist": await interaction.response.send_modal(WhitelistModal(sys_name, roles, log_chan, alert_chan))


class TicketManagementView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    def _is_staff(self, interaction: discord.Interaction) -> bool:
        if interaction.user.guild_permissions.administrator: return True
        cfg = load_ticket_config(interaction.guild_id)
        ticket_data = cfg.get("active_tickets", {}).get(str(interaction.channel_id))
        if ticket_data:
            user_roles = [r.id for r in interaction.user.roles]
            return any(rid in user_roles for rid in ticket_data.get("support_role_ids", []))
        return False

    @discord.ui.button(label="Claim", style=discord.ButtonStyle.primary, emoji="🎫", custom_id="ticket_claim")
    async def claim_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._is_staff(interaction): return await interaction.response.send_message("❌ Only authorized support staff can claim tickets.", ephemeral=True)
            
        embed = interaction.message.embeds[0]
        embed.set_footer(text=f"Ticket Claimed by: {interaction.user.display_name}")
        button.disabled = True
        
        cfg = load_ticket_config(interaction.guild_id)
        ticket_data = cfg.get("active_tickets", {}).get(str(interaction.channel_id), {})
        
        await interaction.response.edit_message(embed=embed, view=self)
        await interaction.channel.send(f"🛡️ **{interaction.user.mention} has claimed this ticket and will be assisting you shortly.**")
        
        # Update Dashboard
        await update_ticket_alert(interaction.guild, ticket_data, "claimed", interaction.user)

    @discord.ui.button(label="Close & Log", style=discord.ButtonStyle.secondary, emoji="🔒", custom_id="ticket_close")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._is_staff(interaction): return await interaction.response.send_message("❌ Only authorized support staff can close tickets.", ephemeral=True)
            
        await interaction.response.defer()
        thread = interaction.channel
        guild = interaction.guild
        cfg = load_ticket_config(guild.id)
        ticket_data = cfg.get("active_tickets", {}).get(str(thread.id), {})
        
        owner_id = ticket_data.get("owner_id")
        transcript_channel_id = ticket_data.get("transcript_channel_id")
        
        owner = guild.get_member(owner_id) if owner_id else None
        transcript_buffer, filename = await generate_transcript(thread, owner)
        
        for item in self.children: item.disabled = True
        await interaction.edit_original_response(view=self)
        
        transcript_buffer.seek(0)
        await thread.send(content="🔒 **This ticket is now closed.** Here is the transcript log for your records. The thread will archive shortly.", file=discord.File(transcript_buffer, filename))
        
        if transcript_channel_id:
            log_channel = guild.get_channel(transcript_channel_id)
            if log_channel:
                transcript_buffer.seek(0)
                await log_channel.send(
                    content=f"📄 **Ticket Closed:** `{thread.name}`\n**Creator:** <@{owner_id}>\n**Closed By:** {interaction.user.mention}",
                    file=discord.File(transcript_buffer, filename)
                )
                
        await update_ticket_alert(guild, ticket_data, "closed", interaction.user)
        
        if str(thread.id) in cfg.get("active_tickets", {}):
            del cfg["active_tickets"][str(thread.id)]
            save_ticket_config(guild.id, cfg)
        
        try: await thread.edit(name=f"[Closed] {thread.name}", archived=True, auto_archive_duration=10080, locked=True, reason="Ticket Closed")
        except discord.HTTPException: pass

    @discord.ui.button(label="Delete", style=discord.ButtonStyle.danger, emoji="🗑️", custom_id="ticket_delete")
    async def delete_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._is_staff(interaction): return await interaction.response.send_message("❌ Only authorized support staff can delete tickets.", ephemeral=True)
            
        await interaction.response.send_message("🗑️ **Generating transcript and deleting ticket in 5 seconds...**")
        
        thread = interaction.channel
        guild = interaction.guild
        cfg = load_ticket_config(guild.id)
        ticket_data = cfg.get("active_tickets", {}).get(str(thread.id), {})
        
        owner_id = ticket_data.get("owner_id")
        transcript_channel_id = ticket_data.get("transcript_channel_id")
        owner = guild.get_member(owner_id) if owner_id else None
        
        transcript_buffer, filename = await generate_transcript(thread, owner)
        
        if transcript_channel_id:
            log_channel = guild.get_channel(transcript_channel_id)
            if log_channel:
                transcript_buffer.seek(0)
                await log_channel.send(
                    content=f"🗑️ **Ticket Deleted:** `{thread.name}`\n**Creator:** <@{owner_id}>\n**Deleted By:** {interaction.user.mention}",
                    file=discord.File(transcript_buffer, filename)
                )
                
        await update_ticket_alert(guild, ticket_data, "deleted", interaction.user)
        
        if str(thread.id) in cfg.get("active_tickets", {}):
            del cfg["active_tickets"][str(thread.id)]
            save_ticket_config(guild.id, cfg)
        
        await discord.utils.sleep_until(discord.utils.utcnow() + datetime.timedelta(seconds=5))
        try: await thread.delete()
        except discord.HTTPException: pass


# -------------------------------------------------------------------------
# COMMAND COG
# -------------------------------------------------------------------------
class TicketSystem(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.add_view(TicketPanelView())
        self.bot.add_view(TicketManagementView())
        
    @commands.Cog.listener()
    async def on_ready(self):
        if getattr(self.bot, "is_passive", False): return
        for guild in self.bot.guilds:
            cfg = load_ticket_config(guild.id)
            panels = cfg.get("panels", {})
            updated = False
            for message_id_str, panel_data in list(panels.items()):
                channel_id = panel_data.get("channel_id")
                if not channel_id: continue
                channel = guild.get_channel(channel_id)
                if isinstance(channel, discord.TextChannel):
                    try:
                        msg = await channel.fetch_message(int(message_id_str))
                        sys_name = panel_data.get("system_name", "Support")
                        thumb = panel_data.get("thumbnail_url")
                        await msg.edit(embed=build_panel_embed(sys_name, thumb), view=TicketPanelView())
                    except discord.NotFound:
                        del panels[message_id_str]
                        updated = True
                    except discord.HTTPException: pass
            if updated:
                cfg["panels"] = panels
                save_ticket_config(guild.id, cfg)
                
    @commands.Cog.listener()
    async def on_thread_member_remove(self, member: discord.ThreadMember):
        """Auto-deletes active tickets if the creator leaves the thread manually."""
        if getattr(self.bot, "is_passive", False): return
        
        thread = member.thread
        guild = thread.guild
        cfg = load_ticket_config(guild.id)
        
        ticket_data = cfg.get("active_tickets", {}).get(str(thread.id))
        if not ticket_data: return
            
        if ticket_data.get("owner_id") == member.id:
            owner_id = member.id
            transcript_channel_id = ticket_data.get("transcript_channel_id")
            owner = guild.get_member(owner_id)
            
            transcript_buffer, filename = await generate_transcript(thread, owner)
            
            if transcript_channel_id:
                log_channel = guild.get_channel(transcript_channel_id)
                if log_channel:
                    transcript_buffer.seek(0)
                    await log_channel.send(
                        content=f"🗑️ **Ticket Auto-Deleted (User Left Thread):** `{thread.name}`\n**Creator:** <@{owner_id}>",
                        file=discord.File(transcript_buffer, filename)
                    )
            
            await update_ticket_alert(guild, ticket_data, "abandoned")
            
            del cfg["active_tickets"][str(thread.id)]
            save_ticket_config(guild.id, cfg)
            
            try: await thread.delete()
            except discord.HTTPException: pass

    @app_commands.command(name="send_ticket_panel", description="Spawns a dynamic thread-based ticketing panel.")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(
        system_name="The name of the system (e.g., Wardogs, Squad, General Support)",
        support_roles="List of roles allowed to manage these tickets (mention them or use IDs)",
        transcript_channel="The channel where closed ticket transcripts will be dumped",
        alert_channel="Channel for silent staff alerts when tickets open",
        thumbnail_url="Optional image URL to display in the top right of the embed"
    )
    async def send_ticket_panel(self, interaction: discord.Interaction, system_name: str, support_roles: str, transcript_channel: discord.TextChannel, alert_channel: discord.TextChannel = None, thumbnail_url: str = None):
        await interaction.response.defer(ephemeral=True)
        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel): return await interaction.followup.send("❌ Ticket panels can only be placed in Text Channels.", ephemeral=True)

        parsed_role_ids = parse_role_ids(interaction.guild, support_roles)
        if not parsed_role_ids: return await interaction.followup.send("❌ No valid roles were found.", ephemeral=True)

        embed = build_panel_embed(system_name, thumbnail_url)
        posted_msg = await channel.send(embed=embed, view=TicketPanelView())
        
        cfg = load_ticket_config(interaction.guild_id)
        if "panels" not in cfg: cfg["panels"] = {}
        cfg["panels"][str(posted_msg.id)] = {
            "system_name": system_name,
            "support_role_ids": parsed_role_ids,
            "transcript_channel_id": transcript_channel.id,
            "alert_channel_id": alert_channel.id if alert_channel else None,
            "channel_id": channel.id,
            "thumbnail_url": thumbnail_url
        }
        save_ticket_config(interaction.guild_id, cfg)
        await interaction.followup.send(f"✅ **{system_name}** ticket panel deployed!", ephemeral=True)

    @app_commands.command(name="edit_ticket_panel", description="Edit the settings of an existing ticket panel.")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(
        message_id="The ID of the panel message you want to edit",
        system_name="New system name", support_roles="New support roles", transcript_channel="New transcript channel",
        alert_channel="New alert channel", thumbnail_url="New thumbnail URL"
    )
    async def edit_ticket_panel(self, interaction: discord.Interaction, message_id: str, system_name: str = None, support_roles: str = None, transcript_channel: discord.TextChannel = None, alert_channel: discord.TextChannel = None, thumbnail_url: str = None):
        await interaction.response.defer(ephemeral=True)
        channel = interaction.channel
        cfg = load_ticket_config(interaction.guild_id)
        panel_data = cfg.get("panels", {}).get(message_id)
        if not panel_data: return await interaction.followup.send("❌ Panel not found.", ephemeral=True)

        try: msg = await channel.fetch_message(int(message_id))
        except discord.NotFound: return await interaction.followup.send("❌ Message not found.", ephemeral=True)

        old_system = panel_data.get("system_name", "Support")
        final_system = system_name or old_system
        parsed_role_ids = parse_role_ids(interaction.guild, support_roles) if support_roles else None
        
        if parsed_role_ids: panel_data["support_role_ids"] = parsed_role_ids
        if transcript_channel: panel_data["transcript_channel_id"] = transcript_channel.id
        if alert_channel: panel_data["alert_channel_id"] = alert_channel.id
        panel_data["system_name"] = final_system
        panel_data["channel_id"] = channel.id
        final_thumb = thumbnail_url if thumbnail_url is not None else panel_data.get("thumbnail_url")
        panel_data["thumbnail_url"] = final_thumb
        cfg["panels"][message_id] = panel_data

        for tid, tdata in cfg.get("active_tickets", {}).items():
            if tdata.get("system_name") == old_system:
                tdata["system_name"] = final_system
                if parsed_role_ids: tdata["support_role_ids"] = parsed_role_ids
                if transcript_channel: tdata["transcript_channel_id"] = transcript_channel.id
                if alert_channel: tdata["alert_channel_id"] = alert_channel.id

        save_ticket_config(interaction.guild_id, cfg)
        await msg.edit(embed=build_panel_embed(final_system, final_thumb), view=TicketPanelView())
        await interaction.followup.send("✅ Panel successfully updated!", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(TicketSystem(bot))