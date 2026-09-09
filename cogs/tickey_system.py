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
    """Parses role mentions, IDs, or exact names into a list of valid role IDs."""
    if not input_str or not input_str.strip():
        return []
        
    valid_ids = []
    
    # 1. Extract any numbers (handles raw IDs and successful @mentions)
    raw_tokens = re.findall(r"\d+", input_str)
    for token in raw_tokens:
        role_id = int(token)
        if guild.get_role(role_id) and role_id not in valid_ids:
            valid_ids.append(role_id)
            
    # 2. Extract by exact name (if you just typed out the names separated by commas)
    # Example input: "Wardogs Admin, Squad Admin"
    possible_names = [name.strip().lower() for name in input_str.split(",")]
    for role in guild.roles:
        if role.name.lower() in possible_names and role.id not in valid_ids:
            valid_ids.append(role.id)
            
    return valid_ids

def build_panel_embed(system_name: str, thumbnail_url: str = None) -> discord.Embed:
    """Builds the aesthetically pleasing ticket panel embed."""
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
# TICKET TRANSCRIPT GENERATOR
# -------------------------------------------------------------------------
async def generate_transcript(thread: discord.Thread, owner: discord.Member | None) -> tuple[io.BytesIO, str]:
    """Fetches messages, returns a reusable memory buffer and timestamped filename in TXT format."""
    
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
    
    # Loop through the history and format it nicely
    async for message in thread.history(limit=None, oldest_first=True):
        timestamp = message.created_at.strftime("%Y-%m-%d %H:%M:%S")
        author_info = f"{message.author} ({message.author.id})"
        
        lines.append(f"[{timestamp}] {author_info}:")
        
        if message.clean_content:
            lines.append(f"  {message.clean_content}")
            
        for att in message.attachments:
            lines.append(f"  [Attachment: {att.url}]")
            
        lines.append("")  # Blank line between messages for readability

    # Compile into a single string and encode to bytes
    transcript_text = "\n".join(lines)
    buffer = io.BytesIO(transcript_text.encode('utf-8'))
    
    # Generate timestamped filename
    timestamp_str = discord.utils.utcnow().strftime("%Y-%m-%d_%H%M%S")
    filename = f"transcript_{thread.name}_{timestamp_str}.txt"
    
    return buffer, filename


# -------------------------------------------------------------------------
# TICKET MODALS
# -------------------------------------------------------------------------
class TicketModal(discord.ui.Modal):
    def __init__(self, title: str, category: str, system_name: str, support_role_ids: list[int], transcript_channel_id: int | None):
        super().__init__(title=title)
        self.category = category
        self.system_name = system_name
        self.support_role_ids = support_role_ids
        self.transcript_channel_id = transcript_channel_id

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        channel = interaction.channel
        guild = interaction.guild
        member = interaction.user
        
        if not isinstance(channel, discord.TextChannel):
            return await interaction.followup.send("❌ Tickets must be opened in a standard text channel.", ephemeral=True)

        clean_name = re.sub(r"^\[.*?\]\s*|^\(.*?\)\s*", "", member.display_name).strip()
        
        prefix_map = {
            "Report User": "Report",
            "Appeal a Ban": "Appeal",
            "Whitelisting": "Whitelist"
        }
        thread_prefix = prefix_map.get(self.category, "Ticket")
        thread_name = f"{thread_prefix}-{clean_name}"
        
        try:
            thread = await channel.create_thread(
                name=thread_name,
                type=discord.ChannelType.private_thread,
                invitable=False,
                auto_archive_duration=10080
            )
        except discord.HTTPException as e:
            return await interaction.followup.send(f"❌ Failed to create ticket thread: {e}", ephemeral=True)

        await thread.add_user(member)

        cfg = load_ticket_config(guild.id)
        if "active_tickets" not in cfg:
            cfg["active_tickets"] = {}
            
        cfg["active_tickets"][str(thread.id)] = {
            "owner_id": member.id,
            "support_role_ids": self.support_role_ids,
            "system_name": self.system_name,
            "transcript_channel_id": self.transcript_channel_id
        }
        save_ticket_config(guild.id, cfg)

        created_timestamp = f"<t:{int(member.created_at.timestamp())}:R>"
        joined_timestamp = f"<t:{int(member.joined_at.timestamp())}:R>" if getattr(member, 'joined_at', None) else "Unknown"

        embed = discord.Embed(
            title=f"🎫 {self.category} | {self.system_name}",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow()
        )
        embed.set_author(name=member.display_name, icon_url=member.display_avatar.url)
        embed.set_thumbnail(url=member.display_avatar.url)
        
        embed.add_field(name="Account Created", value=created_timestamp, inline=True)
        embed.add_field(name="Joined Server", value=joined_timestamp, inline=True)
        
        for item in self.children:
            if isinstance(item, discord.ui.TextInput):
                embed.add_field(name=item.label, value=item.value or "N/A", inline=False)

        support_mentions = " ".join([f"<@&{rid}>" for rid in self.support_role_ids]) if self.support_role_ids else "Support Staff"
        intro_content = f"👋 {member.mention} | {support_mentions}\n\n"
        
        if self.category == "Report User":
            intro_content += "**If you are reporting a player, let us know what is going on and share any video/screenshot evidence you have below.**"
        elif self.category == "Appeal a Ban":
            intro_content += "**A staff member will review your ban appeal shortly. Please ensure your SteamID is correct.**"
        elif self.category == "Whitelisting":
            intro_content += "**Please wait while an admin reviews your whitelist request and links your Discord.**"

        await thread.send(content=intro_content, embed=embed, view=TicketManagementView())
        await interaction.followup.send(f"✅ Ticket created! Click here to view it: {thread.mention}", ephemeral=True)


class ReportModal(TicketModal):
    def __init__(self, system_name: str, support_role_ids: list[int], transcript_channel_id: int | None):
        super().__init__(title="Report a Player", category="Report User", system_name=system_name, support_role_ids=support_role_ids, transcript_channel_id=transcript_channel_id)
        self.add_item(discord.ui.TextInput(label="Player Name / ID", placeholder="Who are you reporting?", required=True, max_length=100))
        self.add_item(discord.ui.TextInput(label="Reason for Report", placeholder="What rule was broken?", style=discord.TextStyle.paragraph, required=True, max_length=500))

class AppealModal(TicketModal):
    def __init__(self, system_name: str, support_role_ids: list[int], transcript_channel_id: int | None):
        super().__init__(title="Appeal a Ban", category="Appeal a Ban", system_name=system_name, support_role_ids=support_role_ids, transcript_channel_id=transcript_channel_id)
        self.add_item(discord.ui.TextInput(label="SteamID64", placeholder="Found at https://steamid.io/lookup", required=True, max_length=100))
        self.add_item(discord.ui.TextInput(label="Why were you banned?", style=discord.TextStyle.paragraph, required=True, max_length=300))
        self.add_item(discord.ui.TextInput(label="Why should you be unbanned?", style=discord.TextStyle.paragraph, required=True, max_length=500))

class WhitelistModal(TicketModal):
    def __init__(self, system_name: str, support_role_ids: list[int], transcript_channel_id: int | None):
        super().__init__(title="Whitelisting Request", category="Whitelisting", system_name=system_name, support_role_ids=support_role_ids, transcript_channel_id=transcript_channel_id)
        self.add_item(discord.ui.TextInput(label="SteamID64", placeholder="Found at https://steamid.io/lookup", required=True, max_length=100))
        self.add_item(discord.ui.TextInput(label="In-Game Name", required=True, max_length=100))


# -------------------------------------------------------------------------
# INTERACTIVE VIEWS
# -------------------------------------------------------------------------
class TicketPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.select(
        placeholder="Select a Ticket Option...",
        min_values=1,
        max_values=1,
        options=[
            discord.SelectOption(label="Make a report", description="Report another player", emoji="‼️", value="report"),
            discord.SelectOption(label="Appeal a ban", description="Appeal a server ban", emoji="🔨", value="appeal"),
            discord.SelectOption(label="Whitelisting", description="Request to be whitelisted", emoji="📩", value="whitelist")
        ],
        custom_id="dynamic_ticket_dropdown"
    )
    async def ticket_dropdown(self, interaction: discord.Interaction, select: discord.ui.Select):
        cfg = load_ticket_config(interaction.guild_id)
        panel_data = cfg.get("panels", {}).get(str(interaction.message.id))

        if not panel_data:
            return await interaction.response.send_message("❌ This panel is no longer actively tracked in the database.", ephemeral=True)

        system_name = panel_data.get("system_name", "Support")
        support_role_ids = panel_data.get("support_role_ids", [])
        transcript_channel_id = panel_data.get("transcript_channel_id")
        
        choice = select.values[0]
        if choice == "report":
            await interaction.response.send_modal(ReportModal(system_name, support_role_ids, transcript_channel_id))
        elif choice == "appeal":
            await interaction.response.send_modal(AppealModal(system_name, support_role_ids, transcript_channel_id))
        elif choice == "whitelist":
            await interaction.response.send_modal(WhitelistModal(system_name, support_role_ids, transcript_channel_id))


class TicketManagementView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    def _is_staff(self, interaction: discord.Interaction) -> bool:
        if interaction.user.guild_permissions.administrator: 
            return True
        cfg = load_ticket_config(interaction.guild_id)
        ticket_data = cfg.get("active_tickets", {}).get(str(interaction.channel_id))
        
        if ticket_data:
            support_ids = ticket_data.get("support_role_ids", [])
            user_roles = [r.id for r in interaction.user.roles]
            if any(rid in user_roles for rid in support_ids):
                return True
        return False

    @discord.ui.button(label="Claim", style=discord.ButtonStyle.primary, emoji="🎫", custom_id="ticket_claim")
    async def claim_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._is_staff(interaction):
            return await interaction.response.send_message("❌ Only authorized support staff can claim tickets.", ephemeral=True)
            
        embed = interaction.message.embeds[0] if interaction.message.embeds else discord.Embed(color=discord.Color.blue())
        embed.set_footer(text=f"Ticket Claimed by: {interaction.user.display_name}")
        
        button.disabled = True
        await interaction.response.edit_message(embed=embed, view=self)
        await interaction.channel.send(f"🛡️ **{interaction.user.mention} has claimed this ticket and will be assisting you shortly.**")

    @discord.ui.button(label="Close & Log", style=discord.ButtonStyle.secondary, emoji="🔒", custom_id="ticket_close")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._is_staff(interaction):
            return await interaction.response.send_message("❌ Only authorized support staff can close tickets.", ephemeral=True)
            
        await interaction.response.defer()
        thread = interaction.channel
        guild = interaction.guild
        
        if isinstance(thread, discord.Thread):
            cfg = load_ticket_config(guild.id)
            ticket_data = cfg.get("active_tickets", {}).get(str(thread.id), {})
            
            owner_id = ticket_data.get("owner_id")
            transcript_channel_id = ticket_data.get("transcript_channel_id")
            
            owner = guild.get_member(owner_id) if owner_id else None
            transcript_buffer, filename = await generate_transcript(thread, owner)
            
            for item in self.children:
                item.disabled = True
            await interaction.edit_original_response(view=self)
            
            transcript_buffer.seek(0)
            await thread.send(content="🔒 **This ticket is now closed.** Here is the transcript log for your records. The thread will archive shortly.", file=discord.File(transcript_buffer, filename))
            
            if transcript_channel_id:
                log_channel = guild.get_channel(transcript_channel_id)
                if log_channel:
                    owner_mention = f"<@{owner_id}>" if owner_id else "Unknown"
                    transcript_buffer.seek(0)
                    await log_channel.send(
                        content=f"📄 **Ticket Closed:** `{thread.name}`\n**Creator:** {owner_mention}\n**Closed By:** {interaction.user.mention}",
                        file=discord.File(transcript_buffer, filename)
                    )
            
            if owner:
                try:
                    transcript_buffer.seek(0)
                    await owner.send(
                        content=f"📄 Hello! Your recent ticket (**{thread.name}**) has been closed. Attached is a copy of your transcript for your records.", 
                        file=discord.File(transcript_buffer, filename)
                    )
                except discord.HTTPException:
                    pass
            
            if str(thread.id) in cfg.get("active_tickets", {}):
                del cfg["active_tickets"][str(thread.id)]
                save_ticket_config(guild.id, cfg)
            
            try:
                await thread.edit(name=f"[Closed] {thread.name}", archived=True, auto_archive_duration=10080, locked=True, reason="Ticket Closed via Button")
            except discord.HTTPException as e:
                logger.error(f"Failed to archive thread: {e}")

    @discord.ui.button(label="Delete", style=discord.ButtonStyle.danger, emoji="🗑️", custom_id="ticket_delete")
    async def delete_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._is_staff(interaction):
            return await interaction.response.send_message("❌ Only authorized support staff can delete tickets.", ephemeral=True)
            
        await interaction.response.send_message("🗑️ **Generating transcript and deleting ticket in 5 seconds...**")
        
        thread = interaction.channel
        guild = interaction.guild
        
        if isinstance(thread, discord.Thread):
            cfg = load_ticket_config(guild.id)
            ticket_data = cfg.get("active_tickets", {}).get(str(thread.id), {})
            
            owner_id = ticket_data.get("owner_id")
            transcript_channel_id = ticket_data.get("transcript_channel_id")
            
            # 1. Generate the transcript before deleting
            owner = guild.get_member(owner_id) if owner_id else None
            transcript_buffer, filename = await generate_transcript(thread, owner)
            
            # 2. Send the transcript to the log channel
            if transcript_channel_id:
                log_channel = guild.get_channel(transcript_channel_id)
                if log_channel:
                    owner_mention = f"<@{owner_id}>" if owner_id else "Unknown"
                    transcript_buffer.seek(0)
                    await log_channel.send(
                        content=f"🗑️ **Ticket Deleted:** `{thread.name}`\n**Creator:** {owner_mention}\n**Deleted By:** {interaction.user.mention}",
                        file=discord.File(transcript_buffer, filename)
                    )
            
            # 3. Clean up the database
            if str(thread.id) in cfg.get("active_tickets", {}):
                del cfg["active_tickets"][str(thread.id)]
                save_ticket_config(guild.id, cfg)
            
            # 4. Wait 5 seconds to let the user see the deletion message, then delete the thread
            await discord.utils.sleep_until(discord.utils.utcnow() + datetime.timedelta(seconds=5))
            try:
                await thread.delete()
            except discord.HTTPException:
                pass


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
        """Auto-refreshes all existing ticket panels to match the latest code/embed design."""
        if getattr(self.bot, "is_passive", False): return
        
        for guild in self.bot.guilds:
            cfg = load_ticket_config(guild.id)
            panels = cfg.get("panels", {})
            updated = False
            
            for message_id_str, panel_data in list(panels.items()):
                channel_id = panel_data.get("channel_id")
                if not channel_id:
                    continue  # Skip old panels that don't have a channel ID yet
                    
                channel = guild.get_channel(channel_id)
                if isinstance(channel, discord.TextChannel):
                    try:
                        msg = await channel.fetch_message(int(message_id_str))
                        system_name = panel_data.get("system_name", "Support")
                        current_thumbnail = msg.embeds[0].thumbnail.url if (msg.embeds and msg.embeds[0].thumbnail) else None
                        
                        new_embed = build_panel_embed(system_name, current_thumbnail)
                        await msg.edit(embed=new_embed, view=TicketPanelView())
                    except discord.NotFound:
                        del panels[message_id_str]
                        updated = True
                    except discord.HTTPException as e:
                        logger.error(f"Failed to refresh ticket panel {message_id_str}: {e}")
            
            if updated:
                cfg["panels"] = panels
                save_ticket_config(guild.id, cfg)
        
    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        """Auto-close active tickets if the creator leaves the server."""
        if getattr(self.bot, "is_passive", False): return
        
        cfg = load_ticket_config(member.guild.id)
        active_tickets = cfg.get("active_tickets", {})
        tickets_to_close = []
        
        for thread_id_str, ticket_data in active_tickets.items():
            if ticket_data.get("owner_id") == member.id:
                tickets_to_close.append((thread_id_str, ticket_data))
                
        if not tickets_to_close:
            return
            
        for thread_id_str, ticket_data in tickets_to_close:
            thread = member.guild.get_thread(int(thread_id_str))
            if not thread:
                del cfg["active_tickets"][thread_id_str]
                continue
                
            transcript_channel_id = ticket_data.get("transcript_channel_id")
            
            await thread.send(f"⚠️ **{member.display_name} has left the server. Auto-closing this ticket...**")
            
            transcript_buffer, filename = await generate_transcript(thread, member)
            
            transcript_buffer.seek(0)
            await thread.send(
                content="🔒 **This ticket was automatically closed because the user left the server.**",
                file=discord.File(transcript_buffer, filename)
            )
            
            if transcript_channel_id:
                log_channel = member.guild.get_channel(transcript_channel_id)
                if log_channel:
                    transcript_buffer.seek(0)
                    await log_channel.send(
                        content=f"📄 **Ticket Auto-Closed (User Left):** `{thread.name}`\n**Creator:** <@{member.id}>\n**System:** {ticket_data.get('system_name', 'Support')}",
                        file=discord.File(transcript_buffer, filename)
                    )
            
            del cfg["active_tickets"][thread_id_str]
            
            try:
                await thread.edit(name=f"[Closed] {thread.name}", archived=True, auto_archive_duration=10080, locked=True, reason="User left the server")
            except discord.HTTPException:
                pass
                
            await asyncio.sleep(1.0)
                
        save_ticket_config(member.guild.id, cfg)

    @app_commands.command(name="send_ticket_panel", description="Spawns a dynamic thread-based ticketing panel.")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(
        system_name="The name of the system (e.g., Wardogs, Squad, General Support)",
        support_roles="List of roles allowed to manage these tickets (mention them or use IDs)",
        transcript_channel="The channel where closed ticket transcripts will be dumped",
        thumbnail_url="Optional image URL to display in the top right of the embed"
    )
    async def send_ticket_panel(
        self, 
        interaction: discord.Interaction, 
        system_name: str, 
        support_roles: str, 
        transcript_channel: discord.TextChannel,
        thumbnail_url: str = None
    ):
        await interaction.response.defer(ephemeral=True)
        channel = interaction.channel
        
        if not isinstance(channel, discord.TextChannel):
            return await interaction.followup.send("❌ Ticket panels can only be placed in Text Channels.", ephemeral=True)

        parsed_role_ids = parse_role_ids(interaction.guild, support_roles)
        if not parsed_role_ids:
            return await interaction.followup.send("❌ No valid roles were found. Please mention the roles or provide their IDs.", ephemeral=True)

        embed = build_panel_embed(system_name, thumbnail_url)
        view = TicketPanelView()
        posted_msg = await channel.send(embed=embed, view=view)
        
        cfg = load_ticket_config(interaction.guild_id)
        if "panels" not in cfg:
            cfg["panels"] = {}
            
        cfg["panels"][str(posted_msg.id)] = {
            "system_name": system_name,
            "support_role_ids": parsed_role_ids,
            "transcript_channel_id": transcript_channel.id,
            "channel_id": channel.id  # Now saving the channel ID for auto-reloading
        }
        save_ticket_config(interaction.guild_id, cfg)
        
        await interaction.followup.send(
            f"✅ **{system_name}** ticket panel deployed! Transcripts will be sent to {transcript_channel.mention}.", 
            ephemeral=True
        )

    @app_commands.command(name="edit_ticket_panel", description="Edit the settings of an existing ticket panel.")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(
        message_id="The ID of the panel message you want to edit",
        system_name="New system name (leave blank to keep current)",
        support_roles="New support roles (leave blank to keep current)",
        transcript_channel="New transcript channel (leave blank to keep current)",
        thumbnail_url="New thumbnail URL (leave blank to keep current)"
    )
    async def edit_ticket_panel(
        self, 
        interaction: discord.Interaction, 
        message_id: str,
        system_name: str = None, 
        support_roles: str = None, 
        transcript_channel: discord.TextChannel = None,
        thumbnail_url: str = None
    ):
        await interaction.response.defer(ephemeral=True)
        channel = interaction.channel
        
        cfg = load_ticket_config(interaction.guild_id)
        panel_data = cfg.get("panels", {}).get(message_id)

        if not panel_data:
            return await interaction.followup.send("❌ Could not find a ticket panel with that ID in the database.", ephemeral=True)

        try:
            msg = await channel.fetch_message(int(message_id))
        except (discord.NotFound, discord.HTTPException):
            return await interaction.followup.send("❌ Could not find the message. Make sure you run this command in the same channel as the panel.", ephemeral=True)

        old_system_name = panel_data.get("system_name", "Support")
        final_system_name = system_name if system_name else old_system_name
        
        parsed_role_ids = None
        if support_roles:
            parsed_role_ids = parse_role_ids(interaction.guild, support_roles)
            if not parsed_role_ids:
                return await interaction.followup.send("❌ Invalid roles provided.", ephemeral=True)
            panel_data["support_role_ids"] = parsed_role_ids
            
        if transcript_channel:
            panel_data["transcript_channel_id"] = transcript_channel.id

        panel_data["system_name"] = final_system_name
        panel_data["channel_id"] = channel.id  # Retroactively inject channel_id into old panels
        cfg["panels"][message_id] = panel_data

        for thread_id, ticket_data in cfg.get("active_tickets", {}).items():
            if ticket_data.get("system_name") == old_system_name:
                ticket_data["system_name"] = final_system_name
                if parsed_role_ids:
                    ticket_data["support_role_ids"] = parsed_role_ids
                if transcript_channel:
                    ticket_data["transcript_channel_id"] = transcript_channel.id

        save_ticket_config(interaction.guild_id, cfg)

        current_thumbnail = msg.embeds[0].thumbnail.url if (msg.embeds and msg.embeds[0].thumbnail) else None
        final_thumbnail = thumbnail_url if thumbnail_url else current_thumbnail
        
        new_embed = build_panel_embed(final_system_name, final_thumbnail)
        await msg.edit(embed=new_embed, view=TicketPanelView())

        await interaction.followup.send("✅ Ticket panel successfully updated, and all active tickets have been retroactively synced!", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(TicketSystem(bot))