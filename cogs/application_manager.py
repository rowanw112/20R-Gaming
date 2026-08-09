import logging
import discord
from discord import app_commands
from discord.ext import commands, tasks

from core.database import (
    load_app_config,
    load_app_threads,
    save_app_config,
    save_app_threads,
)

logger = logging.getLogger(__name__)

BANNER_URL = "https://media.discordapp.net/attachments/617358398245175297/1535770704874573925/20r.png?ex=6a78f96d&is=6a77a7ed&hm=6255b39be423ec5febeecf8a37e467af88d1034c0e21dfdfb6f3a7d89de53797&=&format=webp&quality=lossless&width=1280&height=720"


def is_staff(interaction: discord.Interaction) -> bool:
    """Helper check to ensure the user interacting with review buttons is a staff member."""
    if not isinstance(interaction.user, discord.Member):
        return False

    if (
        interaction.user.guild_permissions.administrator
        or interaction.user.guild_permissions.manage_roles
    ):
        return True

    config = load_app_config().get(str(interaction.guild.id), {})
    grant_role_ids = config.get("member_role_ids", [])
    if not grant_role_ids and config.get("member_role_id"):
        grant_role_ids = [config.get("member_role_id")]

    user_role_ids = [r.id for r in interaction.user.roles]
    return any(rid in user_role_ids for rid in grant_role_ids)


# -------------------------------------------------------------------------
# MODALS
# -------------------------------------------------------------------------
class MemberApplicationModal(discord.ui.Modal, title="20R Member Application"):
    age = discord.ui.TextInput(
        label="Age",
        placeholder="e.g., 21",
        required=True,
        max_length=5,
    )
    steam = discord.ui.TextInput(
        label="Steam Profile URL / ID (Optional)",
        placeholder="https://steamcommunity.com/id/yourid (or leave blank)",
        required=False,
        max_length=100,
    )
    recruiter = discord.ui.TextInput(
        label="How did you hear about us? (Optional)",
        placeholder="e.g., Recruiter name, Reddit, Game server",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=200,
    )
    games = discord.ui.TextInput(
        label="Interested Games / Divisions (Optional)",
        placeholder="e.g., Wardogs, Rust, Squad, BF6, Rocket League",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=300,
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        member = interaction.user

        config = load_app_config().get(str(guild.id), {})
        open_channel_id = config.get("open_channel_id")

        if not open_channel_id:
            await interaction.followup.send(
                "❌ Application system is not properly configured for this server.",
                ephemeral=True,
            )
            return

        open_channel = guild.get_channel(open_channel_id)
        if not isinstance(open_channel, discord.TextChannel):
            await interaction.followup.send(
                "❌ Open applications channel missing or invalid.",
                ephemeral=True,
            )
            return

        age_val = self.age.value.strip()
        steam_val = self.steam.value.strip() or "N/A"
        recruiter_val = self.recruiter.value.strip() or "N/A"
        games_val = self.games.value.strip() or "N/A"

        created_timestamp = f"<t:{int(member.created_at.timestamp())}:R>"
        joined_timestamp = (
            f"<t:{int(member.joined_at.timestamp())}:R>"
            if member.joined_at
            else "Unknown"
        )

        embed = discord.Embed(
            title=f"📋 Member Application — {member.display_name}",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow(),
        )
        embed.set_thumbnail(url=member.display_avatar.url)

        embed.add_field(name="Applicant", value=member.mention, inline=True)
        embed.add_field(name="Account Created", value=created_timestamp, inline=True)
        embed.add_field(name="Joined Server", value=joined_timestamp, inline=True)
        embed.add_field(name="Age", value=age_val, inline=False)
        embed.add_field(name="Steam Profile", value=steam_val, inline=False)
        embed.add_field(name="Source / Recruiter", value=recruiter_val, inline=False)
        embed.add_field(name="Games Interested In", value=games_val, inline=False)
        embed.set_footer(text=f"User ID: {member.id} | Status: Pending Review")

        view = ApplicationReviewView(
            applicant_id=member.id,
            form_data={
                "age": age_val,
                "steam": steam_val,
                "recruiter": recruiter_val,
                "games": games_val,
                "username": str(member),
            },
        )
        await open_channel.send(embed=embed, view=view)

        try:
            dm_embed = discord.Embed(
                title="📥 Application Received — 20R Gaming",
                description=(
                    f"Hello {member.display_name}, your membership application for **20R Gaming** "
                    "has been successfully submitted!\n\n"
                    "Our recruiting team will review your application shortly. You will receive an update here once a decision is made."
                ),
                color=discord.Color.blue(),
            )
            await member.send(embed=dm_embed)
        except discord.HTTPException:
            pass

        await interaction.followup.send(
            "✅ **Application Submitted!** Our recruiting team will review it shortly.",
            ephemeral=True,
        )


class AskQuestionModal(discord.ui.Modal, title="Staff Question Prompt"):
    questions = discord.ui.TextInput(
        label="Enter Question(s) for Applicant",
        placeholder="e.g., Could you provide a working Steam profile link?",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=1000,
    )

    def __init__(self, review_view: "ApplicationReviewView"):
        super().__init__()
        self.review_view = review_view

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        message = interaction.message

        applicant_id, form_data = self.review_view._parse_message_data(message)
        member = guild.get_member(applicant_id)

        app_threads = load_app_threads()
        existing_thread_entry = next(
            (t for t in app_threads if t.get("user_id") == applicant_id), None
        )
        if existing_thread_entry:
            thread_id = existing_thread_entry.get("thread_id")
            thread = guild.get_thread(thread_id)
            if not thread:
                try:
                    thread = await guild.fetch_channel(thread_id)
                except (discord.NotFound, discord.HTTPException):
                    thread = None

            if isinstance(thread, discord.Thread) and not thread.archived:
                await interaction.followup.send(
                    f"💬 An active thread already exists for this application: {thread.mention}",
                    ephemeral=True,
                )
                return

        config = load_app_config().get(str(guild.id), {})
        panel_channel_id = config.get("panel_channel_id")

        target_channel = (
            guild.get_channel(panel_channel_id)
            if panel_channel_id
            else interaction.channel
        )
        if not isinstance(target_channel, discord.TextChannel):
            target_channel = interaction.channel

        thread_name = f"app-{member.display_name if member else applicant_id}"

        try:
            thread = await target_channel.create_thread(
                name=thread_name,
                auto_archive_duration=4320,
                type=discord.ChannelType.private_thread,
            )
        except (discord.Forbidden, discord.HTTPException):
            thread = await target_channel.create_thread(
                name=thread_name,
                auto_archive_duration=4320,
            )

        new_threads = [t for t in app_threads if t.get("user_id") != applicant_id]
        new_threads.append(
            {
                "user_id": applicant_id,
                "thread_id": thread.id,
                "parent_msg_id": message.id,
                "guild_id": guild.id,
                "form_data": form_data,
            }
        )
        save_app_threads(new_threads)

        thread_link_view = discord.ui.View(timeout=None)
        thread_link_view.add_item(
            discord.ui.Button(
                label="💬 Discussion Active (Join Thread)",
                url=thread.jump_url,
                style=discord.ButtonStyle.link,
            )
        )
        try:
            await message.edit(view=thread_link_view)
        except (discord.NotFound, discord.HTTPException):
            pass

        question_embed = discord.Embed(
            title="❓ Staff Question Regarding Application",
            description=f"**Message:**\n{self.questions.value}",
            color=discord.Color.gold(),
            timestamp=discord.utils.utcnow(),
        )
        question_embed.set_footer(
            text=f"Applicant: {form_data.get('username')} | User ID: {applicant_id}"
        )

        thread_review_view = ThreadReviewView(
            applicant_id=applicant_id, form_data=form_data, parent_msg_id=message.id
        )

        mentions_content = f"👋 {member.mention if member else f'<@{applicant_id}>'} | Staff: {interaction.user.mention}"

        await thread.send(
            content=mentions_content,
            embed=question_embed,
            view=thread_review_view,
        )

        if member:
            try:
                dm_embed = discord.Embed(
                    title="💬 Action Required: Application Questions",
                    description=(
                        f"Hello {member.display_name}, the staff team has a question regarding your **20R Gaming** membership application.\n\n"
                        f"**Questions:**\n> {self.questions.value}\n\n"
                        f"👉 **Please click here to respond in your private application thread:**\n{thread.jump_url}"
                    ),
                    color=discord.Color.gold(),
                )
                await member.send(embed=dm_embed)
            except discord.HTTPException:
                pass

        await interaction.followup.send(
            f"💬 Opened private thread in {target_channel.mention}: {thread.mention}",
            ephemeral=True,
        )


class DenyReasonModal(discord.ui.Modal, title="Deny Membership Application"):
    reason = discord.ui.TextInput(
        label="Reason for Rejection",
        placeholder="e.g., Does not meet minimum activity or age requirements.",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=500,
    )

    def __init__(self, review_view_or_tuple):
        super().__init__()
        self.target = review_view_or_tuple

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        if not is_staff(interaction):
            await interaction.followup.send(
                "❌ Only staff members can deny applications!", ephemeral=True
            )
            return

        guild = interaction.guild
        config = load_app_config().get(str(guild.id), {})

        if isinstance(self.target, ApplicationReviewView):
            applicant_id, form_data = self.target._parse_message_data(
                interaction.message
            )
            parent_msg = interaction.message
        else:
            applicant_id, form_data, parent_msg = self.target

        member = guild.get_member(applicant_id)

        if member:
            try:
                dm_embed = discord.Embed(
                    title="📋 20R Membership Application Update",
                    description=(
                        f"Hello {member.display_name}, thank you for applying for official **20R Membership**.\n\n"
                        f"At this time, your application for full membership status has been denied.\n\n"
                        f"**Reason Provided:**\n> {self.reason.value}\n\n"
                        "Please note that a denied membership application does **not** mean you are unwelcome here! "
                        "You are still more than welcome to hang out, jump into public voice channels, play games, and remain an active part of the 20R community as a visitor."
                    ),
                    color=discord.Color.gold(),
                )
                await member.send(embed=dm_embed)
            except discord.HTTPException:
                pass

        await interaction.followup.send(
            "❌ Application denied, applicant notified via DM, and record logged!",
            ephemeral=True,
        )

        denied_channel_id = config.get("denied_channel_id")
        await _archive_compressed_helper(
            interaction,
            parent_msg,
            applicant_id,
            form_data,
            denied_channel_id,
            "Denied Application",
            discord.Color.red(),
            reason_text=self.reason.value,
        )


# -------------------------------------------------------------------------
# SHARED ARCHIVE HELPER
# -------------------------------------------------------------------------
async def _archive_compressed_helper(
    interaction: discord.Interaction | None,
    parent_msg: discord.Message | None,
    applicant_id: int,
    form_data: dict,
    target_channel_id: int,
    status_label: str,
    color: discord.Color,
    reason_text: str | None = None,
    guild_override: discord.Guild | None = None,
):
    guild = interaction.guild if interaction else guild_override
    if not guild:
        return

    target_channel = (
        guild.get_channel(target_channel_id) if target_channel_id else None
    )

    app_threads = load_app_threads()
    target_entry = next(
        (t for t in app_threads if t.get("user_id") == applicant_id), None
    )

    thread_to_delete = None
    if target_entry:
        thread_id = target_entry.get("thread_id")
        thread_to_delete = guild.get_thread(thread_id)
        if not thread_to_delete:
            try:
                thread_to_delete = await guild.fetch_channel(thread_id)
            except (discord.NotFound, discord.HTTPException):
                thread_to_delete = None

        new_threads = [t for t in app_threads if t.get("user_id") != applicant_id]
        save_app_threads(new_threads)

    age = form_data.get("age", "N/A")
    steam = form_data.get("steam", "N/A")
    source = form_data.get("recruiter", "N/A")
    games = form_data.get("games", "N/A")

    reviewer_mention = (
        interaction.user.mention if interaction else "System (Auto-Expired)"
    )

    desc = (
        f"**Applicant:** <@{applicant_id}>\n"
        f"**Reviewer:** {reviewer_mention} • "
        f"**Age:** `{age}` • **Steam:** `{steam}` • "
        f"**Source:** `{source}` • **Games:** `{games}`"
    )
    if reason_text:
        desc += f"\n**Reason:** `{reason_text}`"

    compressed_embed = discord.Embed(
        title=f"📁 {status_label}: {form_data.get('username')} (`{applicant_id}`)",
        description=desc,
        color=color,
        timestamp=discord.utils.utcnow(),
    )
    compressed_embed.set_footer(text=f"User ID: {applicant_id}")

    if isinstance(target_channel, discord.TextChannel):
        await target_channel.send(embed=compressed_embed)

    if parent_msg:
        try:
            await parent_msg.delete()
        except (discord.NotFound, discord.HTTPException):
            pass

    if isinstance(thread_to_delete, discord.Thread):
        try:
            await thread_to_delete.delete()
        except (discord.NotFound, discord.Forbidden, discord.HTTPException) as e:
            logger.error(f"Failed to delete thread: {e}")

    if interaction and isinstance(interaction.channel, discord.Thread):
        try:
            await interaction.channel.delete()
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass


async def _process_approval_roles(guild: discord.Guild, applicant_id: int):
    config = load_app_config().get(str(guild.id), {})
    member = guild.get_member(applicant_id)
    if not member:
        logger.error(f"[AppManager] Member with ID {applicant_id} not found in guild.")
        return []

    bot_member = guild.me
    if not bot_member.guild_permissions.manage_roles:
        logger.error(f"[AppManager] CRITICAL: Bot lacks 'Manage Roles' permission in guild '{guild.name}'!")

    # Grant Roles
    grant_role_ids = config.get("member_role_ids", [])
    if not grant_role_ids and config.get("member_role_id"):
        grant_role_ids = [config.get("member_role_id")]

    granted_roles = [guild.get_role(rid) for rid in grant_role_ids if guild.get_role(rid)]
    
    valid_grant_roles = []
    for role in granted_roles:
        if role and role.position < bot_member.top_role.position:
            if role.managed:
                logger.error(f"[AppManager] Role '{role.name}' ({role.id}) is a Managed/Integration role and cannot be assigned.")
            else:
                valid_grant_roles.append(role)
        else:
            logger.warning(
                f"[AppManager] Role '{role.name if role else 'Unknown'}' (Pos: {role.position if role else 'N/A'}) "
                f"is higher than/equal to Bot Top Role '{bot_member.top_role.name}' (Pos: {bot_member.top_role.position})."
            )

    if valid_grant_roles:
        try:
            await member.add_roles(*valid_grant_roles, reason="Application Approved")
            logger.info(f"[AppManager] Successfully assigned roles {[r.name for r in valid_grant_roles]} to {member.display_name}.")
        except discord.HTTPException as e:
            logger.error(f"[AppManager] Failed to add roles {[r.name for r in valid_grant_roles]}: {e}")

    # Remove Roles
    remove_role_ids = config.get("remove_role_ids", [])
    remove_roles = [guild.get_role(rid) for rid in remove_role_ids if guild.get_role(rid)]
    
    valid_remove_roles = [
        r for r in remove_roles if r and r.position < bot_member.top_role.position and not r.managed
    ]

    if valid_remove_roles:
        try:
            await member.remove_roles(*valid_remove_roles, reason="Application Approved")
            logger.info(f"[AppManager] Successfully removed roles {[r.name for r in valid_remove_roles]} from {member.display_name}.")
        except discord.HTTPException as e:
            logger.error(f"[AppManager] Failed to remove roles {[r.name for r in valid_remove_roles]}: {e}")

    if valid_grant_roles:
        role_names = ", ".join([f"**{r.name}**" for r in valid_grant_roles])
        try:
            dm_embed = discord.Embed(
                title="🎉 Application Approved — Welcome to 20R!",
                description=(
                    f"Congratulations {member.display_name}! Your membership application for **20R Gaming** "
                    "has been **Approved**!\n\n"
                    f"You have been granted the following role(s): {role_names}. Head over to the server to check out your new division channels!"
                ),
                color=discord.Color.green(),
            )
            await member.send(embed=dm_embed)
        except discord.HTTPException:
            pass

    return valid_grant_roles


# -------------------------------------------------------------------------
# THREAD-SPECIFIC REVIEW VIEW
# -------------------------------------------------------------------------
class ThreadReviewView(discord.ui.View):
    def __init__(
        self,
        applicant_id: int | None = None,
        form_data: dict | None = None,
        parent_msg_id: int | None = None,
    ):
        super().__init__(timeout=None)
        self.applicant_id = applicant_id
        self.form_data = form_data or {}
        self.parent_msg_id = parent_msg_id

    async def _get_parent_message(
        self, interaction: discord.Interaction
    ) -> discord.Message | None:
        if self.parent_msg_id:
            guild = interaction.guild
            config = load_app_config().get(str(guild.id), {})
            open_channel_id = config.get("open_channel_id")
            if open_channel_id:
                open_channel = guild.get_channel(open_channel_id)
                if isinstance(open_channel, discord.TextChannel):
                    try:
                        return await open_channel.fetch_message(self.parent_msg_id)
                    except (discord.NotFound, discord.HTTPException):
                        pass
        return None

    @discord.ui.button(
        label="Approve Application",
        style=discord.ButtonStyle.success,
        custom_id="thread_app_approve",
    )
    async def approve(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await interaction.response.defer(ephemeral=True)

        if not is_staff(interaction):
            await interaction.followup.send(
                "❌ You do not have staff permissions to review applications!",
                ephemeral=True,
            )
            return

        guild = interaction.guild
        config = load_app_config().get(str(guild.id), {})

        parent_msg = await self._get_parent_message(interaction)

        await _process_approval_roles(guild, self.applicant_id)

        await interaction.followup.send(
            "✅ Application approved, roles updated, and thread deleted!",
            ephemeral=True,
        )

        approved_channel_id = config.get("approved_channel_id")
        await _archive_compressed_helper(
            interaction,
            parent_msg,
            self.applicant_id,
            self.form_data,
            approved_channel_id,
            "Approved Application",
            discord.Color.green(),
        )

    @discord.ui.button(
        label="Deny Application",
        style=discord.ButtonStyle.danger,
        custom_id="thread_app_deny",
    )
    async def deny(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if not is_staff(interaction):
            await interaction.response.send_message(
                "❌ You do not have staff permissions to review applications!",
                ephemeral=True,
            )
            return

        parent_msg = await self._get_parent_message(interaction)
        await interaction.response.send_modal(
            DenyReasonModal((self.applicant_id, self.form_data, parent_msg))
        )


# -------------------------------------------------------------------------
# PERSISTENT MAIN CHANNEL REVIEW VIEW
# -------------------------------------------------------------------------
class ApplicationReviewView(discord.ui.View):
    def __init__(self, applicant_id: int | None = None, form_data: dict | None = None):
        super().__init__(timeout=None)
        self.applicant_id = applicant_id
        self.form_data = form_data or {}

    def _parse_message_data(self, message: discord.Message) -> tuple[int, dict]:
        if self.applicant_id and self.form_data:
            return self.applicant_id, self.form_data

        applicant_id = 0
        form_data = {
            "age": "N/A",
            "steam": "N/A",
            "recruiter": "N/A",
            "games": "N/A",
            "username": "Unknown",
        }

        if message.embeds:
            embed = message.embeds[0]
            if embed.footer and embed.footer.text:
                try:
                    applicant_id = int(
                        embed.footer.text.split("|")[0]
                        .replace("User ID:", "")
                        .strip()
                    )
                except ValueError:
                    pass

            form_data["username"] = (
                embed.title.replace("📋 Member Application — ", "").strip()
                if embed.title
                else "Unknown"
            )

            for field in embed.fields:
                if field.name == "Age":
                    form_data["age"] = field.value
                elif field.name == "Steam Profile":
                    form_data["steam"] = field.value
                elif field.name == "Source / Recruiter":
                    form_data["recruiter"] = field.value
                elif field.name == "Games Interested In":
                    form_data["games"] = field.value

        return applicant_id, form_data

    @discord.ui.button(
        label="Approve", style=discord.ButtonStyle.success, custom_id="app_approve"
    )
    async def approve(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await interaction.response.defer(ephemeral=True)

        if not is_staff(interaction):
            await interaction.followup.send(
                "❌ You do not have staff permissions to review applications!",
                ephemeral=True,
            )
            return

        guild = interaction.guild
        config = load_app_config().get(str(guild.id), {})

        applicant_id, form_data = self._parse_message_data(interaction.message)

        await _process_approval_roles(guild, applicant_id)

        await interaction.followup.send(
            "✅ Application approved, roles updated, and logged!",
            ephemeral=True,
        )

        approved_channel_id = config.get("approved_channel_id")
        await _archive_compressed_helper(
            interaction,
            interaction.message,
            applicant_id,
            form_data,
            approved_channel_id,
            "Approved Application",
            discord.Color.green(),
        )

    @discord.ui.button(
        label="Ask Question (Open Thread)",
        style=discord.ButtonStyle.primary,
        custom_id="app_ask_question",
    )
    async def ask_question(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if not is_staff(interaction):
            await interaction.response.send_message(
                "❌ You do not have staff permissions to review applications!",
                ephemeral=True,
            )
            return

        applicant_id, _ = self._parse_message_data(interaction.message)

        app_threads = load_app_threads()
        existing_thread_entry = next(
            (t for t in app_threads if t.get("user_id") == applicant_id), None
        )
        if existing_thread_entry:
            thread_id = existing_thread_entry.get("thread_id")
            guild = interaction.guild
            thread = guild.get_thread(thread_id)
            if not thread:
                try:
                    thread = await guild.fetch_channel(thread_id)
                except (discord.NotFound, discord.HTTPException):
                    thread = None

            if isinstance(thread, discord.Thread) and not thread.archived:
                await interaction.response.send_message(
                    f"💬 An active thread already exists for this application: {thread.mention}",
                    ephemeral=True,
                )
                return

        await interaction.response.send_modal(AskQuestionModal(self))

    @discord.ui.button(
        label="Deny", style=discord.ButtonStyle.danger, custom_id="app_deny"
    )
    async def deny(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if not is_staff(interaction):
            await interaction.response.send_message(
                "❌ You do not have staff permissions to review applications!",
                ephemeral=True,
            )
            return

        await interaction.response.send_modal(DenyReasonModal(self))


# -------------------------------------------------------------------------
# PERSISTENT PANEL LAUNCHER
# -------------------------------------------------------------------------
class ApplicationPanelLauncher(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Apply for Membership",
        style=discord.ButtonStyle.success,
        emoji="📝",
        custom_id="launch_member_app",
    )
    async def launch_app(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        guild = interaction.guild
        member = interaction.user
        config = load_app_config().get(str(guild.id), {})

        grant_role_ids = config.get("member_role_ids", [])
        if not grant_role_ids and config.get("member_role_id"):
            grant_role_ids = [config.get("member_role_id")]

        if grant_role_ids:
            member_roles = [
                guild.get_role(rid) for rid in grant_role_ids if guild.get_role(rid)
            ]
            if any(role in member.roles for role in member_roles if role):
                await interaction.response.send_message(
                    "❌ You are already an official member of 20R!",
                    ephemeral=True,
                )
                return

        open_channel_id = config.get("open_channel_id")
        if open_channel_id:
            open_channel = guild.get_channel(open_channel_id)
            if isinstance(open_channel, discord.TextChannel):
                async for msg in open_channel.history(limit=100):
                    if msg.embeds:
                        footer = msg.embeds[0].footer.text or ""
                        if f"User ID: {member.id}" in footer:
                            await interaction.response.send_message(
                                "⚠️ You already have an active application pending review!",
                                ephemeral=True,
                            )
                            return

        await interaction.response.send_modal(MemberApplicationModal())


# -------------------------------------------------------------------------
# MANAGER COG
# -------------------------------------------------------------------------
class ApplicationManager(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.check_inactive_app_threads.start()

    def cog_unload(self):
        self.check_inactive_app_threads.cancel()

    async def cog_load(self):
        self.bot.add_view(ApplicationPanelLauncher())
        self.bot.add_view(ApplicationReviewView())
        self.bot.add_view(ThreadReviewView())

    @tasks.loop(minutes=5)
    async def check_inactive_app_threads(self):
        """Scans for threads archived due to inactivity and automatically denies/expires them."""
        app_threads = load_app_threads()
        if not app_threads:
            return

        for entry in list(app_threads):
            guild_id = entry.get("guild_id")
            thread_id = entry.get("thread_id")
            applicant_id = entry.get("user_id")
            parent_msg_id = entry.get("parent_msg_id")
            form_data = entry.get("form_data", {})

            guild = self.bot.get_guild(guild_id)
            if not guild:
                continue

            config = load_app_config().get(str(guild.id), {})
            denied_channel_id = config.get("denied_channel_id")
            open_channel_id = config.get("open_channel_id")

            thread = guild.get_thread(thread_id)
            if not thread:
                try:
                    thread = await guild.fetch_channel(thread_id)
                except (discord.NotFound, discord.HTTPException):
                    thread = None

            if isinstance(thread, discord.Thread) and thread.archived:
                member = guild.get_member(applicant_id)

                if member:
                    try:
                        dm_embed = discord.Embed(
                            title="⏱️ Membership Application Expired",
                            description=(
                                f"Hello {member.display_name}, your membership application for **20R Gaming** "
                                "has closed due to 3 days of inactivity.\n\n"
                                "If you are still interested in joining, you are welcome to submit a new application at any time!"
                            ),
                            color=discord.Color.gold(),
                        )
                        await member.send(embed=dm_embed)
                    except discord.HTTPException:
                        pass

                parent_msg = None
                if parent_msg_id and open_channel_id:
                    open_channel = guild.get_channel(open_channel_id)
                    if isinstance(open_channel, discord.TextChannel):
                        try:
                            parent_msg = await open_channel.fetch_message(parent_msg_id)
                        except (discord.NotFound, discord.HTTPException):
                            pass

                await _archive_compressed_helper(
                    interaction=None,
                    parent_msg=parent_msg,
                    applicant_id=applicant_id,
                    form_data=form_data,
                    target_channel_id=denied_channel_id,
                    status_label="Denied (Auto-Expired / Inactive)",
                    color=discord.Color.dark_red(),
                    reason_text="Application closed automatically due to 3 days of inactivity.",
                    guild_override=guild,
                )
                logger.info(f"[AppManager] Auto-expired inactive application thread for user ID {applicant_id}.")

    @check_inactive_app_threads.before_loop
    async def before_check_threads(self):
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_ready(self):
        all_configs = load_app_config()
        for guild_id, cfg in all_configs.items():
            panel_ch_id = cfg.get("panel_channel_id")
            panel_msg_id = cfg.get("panel_message_id")
            if panel_ch_id and panel_msg_id:
                channel = self.bot.get_channel(panel_ch_id)
                if isinstance(channel, discord.TextChannel):
                    try:
                        msg = await channel.fetch_message(panel_msg_id)
                        await msg.edit(view=ApplicationPanelLauncher())
                    except (discord.NotFound, discord.HTTPException):
                        pass

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.guild or message.author.bot:
            return

        app_threads = load_app_threads()
        target_entry = next(
            (t for t in app_threads if t.get("user_id") == message.author.id), None
        )

        if not target_entry:
            return

        thread_id = target_entry.get("thread_id")
        thread = self.bot.get_channel(thread_id)

        if not thread:
            try:
                thread = await self.bot.fetch_channel(thread_id)
            except (discord.NotFound, discord.HTTPException):
                new_threads = [
                    t for t in app_threads if t.get("user_id") != message.author.id
                ]
                save_app_threads(new_threads)
                return

        if isinstance(thread, discord.Thread):
            if thread.archived:
                new_threads = [
                    t for t in app_threads if t.get("user_id") != message.author.id
                ]
                save_app_threads(new_threads)
                return

            dm_embed = discord.Embed(
                title="⚠️ Please Reply in Your Application Thread",
                description=(
                    f"Hi {message.author.display_name}, please post your response directly in your private server thread here:\n\n"
                    f"👉 {thread.jump_url}"
                ),
                color=discord.Color.gold(),
            )
            await message.channel.send(embed=dm_embed)

    @app_commands.command(
        name="send_app_panel",
        description="Configure and post the Member Application Panel.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def send_app_panel(
        self,
        interaction: discord.Interaction,
        open_channel: discord.TextChannel,
        approved_channel: discord.TextChannel,
        denied_channel: discord.TextChannel,
        member_role_1: discord.Role,
        member_role_2: discord.Role | None = None,
        member_role_3: discord.Role | None = None,
        remove_role_1: discord.Role | None = None,
        remove_role_2: discord.Role | None = None,
        remove_role_3: discord.Role | None = None,
        panel_channel: discord.TextChannel | None = None,
    ):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        target_panel_channel = panel_channel or interaction.channel

        if not isinstance(target_panel_channel, discord.TextChannel):
            await interaction.followup.send(
                "❌ Target panel channel must be a valid text channel!",
                ephemeral=True,
            )
            return

        grant_roles = [r for r in [member_role_1, member_role_2, member_role_3] if r]
        grant_role_ids = [r.id for r in grant_roles]

        remove_roles = [r for r in [remove_role_1, remove_role_2, remove_role_3] if r]
        remove_role_ids = [r.id for r in remove_roles]

        embed = discord.Embed(
            title="🛡️ Join the 20R Gaming Community",
            description=(
                "Ready to take your place in 20R? Becoming an official member unlocks full community access, "
                "grants perks across all our game divisions, and connects you with a solid, active group of gamers.\n\n"
                "**✨ Why Become an Official Member?**\n"
                "• 🔓 **Full Division Access:** Gain entry to locked division channels, private strategy discussions, and rank-specific hubs.\n"
                "• 🏆 **Exclusive Events & Matchmaking:** Priority slots in community tournaments, internal scrims, and weekly division events.\n"
                "• 🤝 **A True Gaming Community:** Get recognized as an official part of the crew in a structured, welcoming, and supportive multi-gaming family.\n"
                "• 📈 **Growth & Leadership:** Opportunities to step into staff, event organizing, or competitive roster roles.\n\n"
                "---\n"
                "**📋 How to Apply:**\n"
                "Click the **Apply for Membership** button below to fill out a short application!"
            ),
            color=discord.Color.gold(),
        )
        embed.set_image(url=BANNER_URL)

        view = ApplicationPanelLauncher()
        posted_msg = await target_panel_channel.send(embed=embed, view=view)

        all_configs = load_app_config()
        all_configs[str(guild.id)] = {
            "panel_channel_id": target_panel_channel.id,
            "panel_message_id": posted_msg.id,
            "open_channel_id": open_channel.id,
            "approved_channel_id": approved_channel.id,
            "denied_channel_id": denied_channel.id,
            "member_role_ids": grant_role_ids,
            "remove_role_ids": remove_role_ids,
        }
        save_app_config(all_configs)

        grant_str = ", ".join([r.mention for r in grant_roles])
        remove_str = (
            ", ".join([r.mention for r in remove_roles]) if remove_roles else "None"
        )

        await interaction.followup.send(
            f"✅ **Application Panel Configured & Posted!**\n"
            f"• **Posted In:** {target_panel_channel.mention}\n"
            f"• **Open Applications Target:** {open_channel.mention}\n"
            f"• **Approved Logs Target:** {approved_channel.mention}\n"
            f"• **Denied Logs Target:** {denied_channel.mention}\n"
            f"• **Member Roles Granted:** {grant_str}\n"
            f"• **Roles Removed:** {remove_str}",
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(ApplicationManager(bot))