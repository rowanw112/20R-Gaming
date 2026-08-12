import logging
import os
import json
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
RANK_CONFIG_FILE = "data/rank_system_config.json"


def load_rank_config() -> dict:
    if not os.path.exists(RANK_CONFIG_FILE):
        return {}
    with open(RANK_CONFIG_FILE, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}


def is_staff(interaction: discord.Interaction) -> bool:
    """Helper check to ensure the user interacting with review buttons is a staff member or operator."""
    if not isinstance(interaction.user, discord.Member):
        return False

    if (
        interaction.user.guild_permissions.administrator
        or interaction.user.guild_permissions.manage_roles
    ):
        return True

    app_cfg = load_app_config().get(str(interaction.guild.id), {})
    op_role_id = app_cfg.get("application_operator_role_id")
    if op_role_id and op_role_id in [r.id for r in interaction.user.roles]:
        return True

    rank_cfg = load_rank_config().get(str(interaction.guild.id), {})
    staff_ids = rank_cfg.get("staff_role_ids", [])
    user_role_ids = [r.id for r in interaction.user.roles]
    return any(rid in user_role_ids for rid in staff_ids)


def build_panel_embed() -> discord.Embed:
    """Central embed builder for the application panel."""
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
    return embed


async def ensure_operator_threads(guild: discord.Guild, panel_channel: discord.TextChannel) -> dict:
    """Ensures private operator threads exist inside the main channel."""
    all_configs = load_app_config()
    cfg = all_configs.get(str(guild.id), {})

    thread_keys = {
        "open_thread_id": "🔒 open-applications",
        "approved_thread_id": "🔒 approved-applications",
        "denied_thread_id": "🔒 denied-applications",
    }

    updated = False
    for key, name in thread_keys.items():
        thread_id = cfg.get(key)
        thread = guild.get_thread(thread_id) if thread_id else None

        if not thread:
            try:
                thread = await panel_channel.create_thread(
                    name=name,
                    type=discord.ChannelType.private_thread,
                    invitable=False,
                )
                cfg[key] = thread.id
                updated = True
            except (discord.Forbidden, discord.HTTPException) as e:
                logger.error(f"Failed to create operator thread '{name}': {e}")

    if updated:
        all_configs[str(guild.id)] = cfg
        save_app_config(all_configs)

    return cfg


# -------------------------------------------------------------------------
# MODALS
# -------------------------------------------------------------------------
class MemberApplicationModal(discord.ui.Modal, title="20R Member Application"):
    age_18 = discord.ui.TextInput(
        label="Are you 18 or older?",
        placeholder="Type Yes or No",
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
        open_thread_id = config.get("open_thread_id")
        op_role_id = config.get("application_operator_role_id")

        open_thread = guild.get_thread(open_thread_id) if open_thread_id else None

        if not open_thread:
            await interaction.followup.send(
                "❌ Open applications thread is missing. Please run `/send_app_panel`.",
                ephemeral=True,
            )
            return

        age_val = self.age_18.value.strip().capitalize()
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
        embed.add_field(name="18 or Older?", value=age_val, inline=False)
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

        content = None
        if op_role_id:
            op_role = guild.get_role(op_role_id)
            if op_role:
                content = f"{op_role.mention} New application submitted!"

        await open_thread.send(content=content, embed=embed, view=view)

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
            if thread and not thread.archived:
                await interaction.followup.send(
                    f"💬 An active thread already exists for this application: {thread.mention}",
                    ephemeral=True,
                )
                return

        config = load_app_config().get(str(guild.id), {})
        panel_channel_id = config.get("panel_channel_id")
        target_channel = guild.get_channel(panel_channel_id) if panel_channel_id else interaction.channel

        if not isinstance(target_channel, discord.TextChannel):
            target_channel = interaction.channel

        thread_name = f"app-{member.display_name if member else applicant_id}"

        try:
            # Try 3-day archive duration (Requires Boost Level 1/2 depending on server age)
            thread = await target_channel.create_thread(
                name=thread_name,
                auto_archive_duration=4320,
                type=discord.ChannelType.private_thread,
                invitable=False,
            )
        except discord.HTTPException:
            # Fallback to standard 24-hour duration if the server lacks the required boost level
            thread = await target_channel.create_thread(
                name=thread_name,
                auto_archive_duration=1440,
                type=discord.ChannelType.private_thread,
                invitable=False,
            )

        if member:
            try:
                await thread.add_user(member)
            except discord.HTTPException:
                pass

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

        denied_thread_id = config.get("denied_thread_id")
        await _archive_compressed_helper(
            interaction,
            parent_msg,
            applicant_id,
            form_data,
            denied_thread_id,
            "Denied Application",
            discord.Color.red(),
            reason_text=self.reason.value,
        )


# -------------------------------------------------------------------------
# SHARED ARCHIVE HELPER
# -------------------------------------------------------------------------
async def _archive_compressed_helper(
    interaction: discord.Interaction | None,
    parent_msg: discord.Message | int | None,
    applicant_id: int,
    form_data: dict,
    target_thread_id: int,
    status_label: str,
    color: discord.Color,
    reason_text: str | None = None,
    guild_override: discord.Guild | None = None,
):
    guild = interaction.guild if interaction else guild_override
    if not guild:
        return

    config = load_app_config().get(str(guild.id), {})
    target_thread = (
        guild.get_thread(target_thread_id) if target_thread_id else None
    )

    app_threads = load_app_threads()
    target_entry = next(
        (t for t in app_threads if t.get("user_id") == applicant_id), None
    )

    thread_to_delete = None
    parent_msg_id = None
    parent_msg_obj = None

    if isinstance(parent_msg, discord.Message):
        parent_msg_obj = parent_msg
        parent_msg_id = parent_msg.id
    elif isinstance(parent_msg, int):
        parent_msg_id = parent_msg

    if target_entry:
        thread_id = target_entry.get("thread_id")
        if not parent_msg_id:
            parent_msg_id = target_entry.get("parent_msg_id")
        thread_to_delete = guild.get_thread(thread_id)

        new_threads = [t for t in app_threads if t.get("user_id") != applicant_id]
        save_app_threads(new_threads)

    # Resolve and fetch parent_msg in open-applications if not already a Message object
    if not parent_msg_obj and parent_msg_id:
        open_thread_id = config.get("open_thread_id")
        if open_thread_id:
            open_thread = guild.get_thread(open_thread_id)
            if not open_thread:
                try:
                    open_thread = await guild.fetch_channel(open_thread_id)
                except (discord.NotFound, discord.HTTPException):
                    pass

            if open_thread and isinstance(open_thread, discord.Thread):
                try:
                    parent_msg_obj = await open_thread.fetch_message(parent_msg_id)
                except (discord.NotFound, discord.HTTPException):
                    pass

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
        f"**18+?:** `{age}` • **Steam:** `{steam}` • "
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

    if isinstance(target_thread, discord.Thread):
        await target_thread.send(embed=compressed_embed)

    # Delete the parent application embed from open-applications
    if parent_msg_obj:
        try:
            await parent_msg_obj.delete()
        except (discord.NotFound, discord.HTTPException) as e:
            logger.error(f"Failed to delete parent app message: {e}")

    # Delete private discussion thread if open
    if isinstance(thread_to_delete, discord.Thread):
        try:
            await thread_to_delete.delete()
        except (discord.NotFound, discord.Forbidden, discord.HTTPException) as e:
            logger.error(f"Failed to delete thread: {e}")


async def _process_approval_roles(guild: discord.Guild, applicant_id: int):
    rank_cfg = load_rank_config().get(str(guild.id), {})
    member = guild.get_member(applicant_id)
    if not member:
        return []

    bot_member = guild.me
    recruit_role_id = rank_cfg.get("recruit_role_id")
    recruit_role = guild.get_role(recruit_role_id) if recruit_role_id else None

    if not recruit_role or recruit_role.position >= bot_member.top_role.position:
        return []

    try:
        await member.add_roles(recruit_role, reason="Application Approved — Granted Recruit Role")
    except discord.HTTPException as e:
        logger.error(f"[AppManager] Failed to add Recruit role: {e}")
        return []

    try:
        dm_embed = discord.Embed(
            title="🎉 Application Approved — Welcome to 20R!",
            description=(
                f"Congratulations {member.display_name}! Your membership application for **20R Gaming** "
                f"has been **Approved**!\n\n"
                f"You have been granted the **{recruit_role.name}** role. Head over to the server to check out your division channels!"
            ),
            color=discord.Color.green(),
        )
        await member.send(embed=dm_embed)
    except discord.HTTPException:
        pass

    return [recruit_role]


# -------------------------------------------------------------------------
# REVIEWS VIEWS
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

    def _resolve_thread_data(self, interaction: discord.Interaction) -> tuple[int, dict, int | None]:
        if self.applicant_id and self.form_data:
            return self.applicant_id, self.form_data, self.parent_msg_id

        app_threads = load_app_threads()
        entry = next(
            (t for t in app_threads if t.get("thread_id") == interaction.channel_id), None
        )
        if entry:
            return entry.get("user_id", 0), entry.get("form_data", {}), entry.get("parent_msg_id")

        return 0, {}, None

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

        applicant_id, form_data, parent_msg_id = self._resolve_thread_data(interaction)

        await _process_approval_roles(guild, applicant_id)

        await interaction.followup.send(
            "✅ Application approved, granted Recruit role, and logged!",
            ephemeral=True,
        )

        approved_thread_id = config.get("approved_thread_id")
        await _archive_compressed_helper(
            interaction,
            parent_msg_id,
            applicant_id,
            form_data,
            approved_thread_id,
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
            await interaction.followup.send(
                "❌ You do not have staff permissions to review applications!",
                ephemeral=True,
            )
            return

        applicant_id, form_data, parent_msg_id = self._resolve_thread_data(interaction)

        await interaction.response.send_modal(
            DenyReasonModal((applicant_id, form_data, parent_msg_id))
        )


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
                if field.name in ("Age", "18 or Older?"):
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
            "✅ Application approved, granted Recruit role, and logged!",
            ephemeral=True,
        )

        approved_thread_id = config.get("approved_thread_id")
        await _archive_compressed_helper(
            interaction,
            interaction.message,
            applicant_id,
            form_data,
            approved_thread_id,
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

            if thread and not thread.archived:
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
        rank_cfg = load_rank_config().get(str(guild.id), {})

        recruit_role_id = rank_cfg.get("recruit_role_id")
        member_role_id = rank_cfg.get("member_role_id")
        rank_role_ids = rank_cfg.get("rank_role_ids", [])

        blocked_ids = set(rank_role_ids)
        if recruit_role_id:
            blocked_ids.add(recruit_role_id)
        if member_role_id:
            blocked_ids.add(member_role_id)

        user_role_ids = {r.id for r in member.roles}
        if blocked_ids.intersection(user_role_ids):
            await interaction.response.send_message(
                "❌ You are already an official member or recruit of 20R!",
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
            denied_thread_id = config.get("denied_thread_id")

            thread = guild.get_thread(thread_id)

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

                await _archive_compressed_helper(
                    interaction=None,
                    parent_msg=parent_msg_id,
                    applicant_id=applicant_id,
                    form_data=form_data,
                    target_thread_id=denied_thread_id,
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
                        await msg.edit(embed=build_panel_embed(), view=ApplicationPanelLauncher())
                    except (discord.NotFound, discord.HTTPException):
                        pass

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        """Auto-syncs members who earn the Application Operator role into all operator threads."""
        guild = after.guild
        config = load_app_config().get(str(guild.id), {})
        op_role_id = config.get("application_operator_role_id")

        if not op_role_id:
            return

        op_role = guild.get_role(op_role_id)
        if not op_role:
            return

        had_role = op_role in before.roles
        has_role = op_role in after.roles

        if not had_role and has_role:
            for thread_key in ("open_thread_id", "approved_thread_id", "denied_thread_id"):
                t_id = config.get(thread_key)
                if t_id:
                    thread = guild.get_thread(t_id)
                    if thread:
                        try:
                            await thread.add_user(after)
                        except discord.HTTPException as e:
                            logger.error(f"Failed to add {after.display_name} to operator thread: {e}")

    @app_commands.command(
        name="send_app_panel",
        description="Configure the Member Application Panel and create private operator threads inside the panel channel.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def send_app_panel(
        self,
        interaction: discord.Interaction,
        panel_channel: discord.TextChannel | None = None,
        application_operator_role: discord.Role | None = None,
    ):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild

        all_configs = load_app_config()
        existing_cfg = all_configs.get(str(guild.id), {})

        final_panel_channel = panel_channel or guild.get_channel(existing_cfg.get("panel_channel_id")) or interaction.channel
        final_op_role = application_operator_role if application_operator_role is not None else (
            guild.get_role(existing_cfg.get("application_operator_role_id")) if existing_cfg.get("application_operator_role_id") else None
        )

        embed = build_panel_embed()
        view = ApplicationPanelLauncher()
        posted_msg = await final_panel_channel.send(embed=embed, view=view)

        existing_cfg["panel_channel_id"] = final_panel_channel.id
        existing_cfg["panel_message_id"] = posted_msg.id
        existing_cfg["application_operator_role_id"] = final_op_role.id if final_op_role else None

        all_configs[str(guild.id)] = existing_cfg
        save_app_config(all_configs)

        # Create/ensure private operator threads exist inside the panel channel
        op_threads = await ensure_operator_threads(guild, final_panel_channel)

        # Sync existing members with operator role into the operator threads
        if final_op_role:
            for m in final_op_role.members:
                for t_key in ("open_thread_id", "approved_thread_id", "denied_thread_id"):
                    t_id = op_threads.get(t_key)
                    if t_id:
                        thread = guild.get_thread(t_id)
                        if thread:
                            try:
                                await thread.add_user(m)
                            except discord.HTTPException:
                                pass

        await interaction.followup.send(
            f"✅ **Application Panel Configured & Posted!**\n"
            f"• **Panel Channel:** {final_panel_channel.mention}\n"
            f"• **Application Operator Role:** {final_op_role.mention if final_op_role else 'None'}\n"
            f"• **Private Operator Threads Created:** 🔒 `open-applications`, 🔒 `approved-applications`, 🔒 `denied-applications` inside {final_panel_channel.mention}",
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(ApplicationManager(bot))