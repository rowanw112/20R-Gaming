import logging
import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger(__name__)

# Standard Hex Colors
COLOR_DIVISION_STAFF = discord.Color(0xE67E22)  # #e67e22
COLOR_STAFF = discord.Color(0xF1C40F)           # #f1c40f
COLOR_MEMBER = discord.Color(0xAD1457)          # #ad1457


# Confirmation View for Division Deletion
class ConfirmDeleteView(discord.ui.View):
    def __init__(
        self,
        category: discord.CategoryChannel,
        roles_to_delete: list[discord.Role],
        user: discord.User,
    ):
        super().__init__(timeout=60)
        self.category = category
        self.roles_to_delete = roles_to_delete
        self.user = user

    @discord.ui.button(label="Confirm Deletion", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user.id:
            await interaction.response.send_message(
                "❌ You cannot confirm this operation.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        deleted_channels = 0
        deleted_roles = 0

        # 1. Delete all channels within the category
        for channel in self.category.channels:
            try:
                await channel.delete(reason=f"Division Teardown requested by {self.user}")
                deleted_channels += 1
            except discord.HTTPException as e:
                logger.error(f"Failed to delete channel {channel.name}: {e}")

        # 2. Delete the category itself
        try:
            await self.category.delete(reason=f"Division Teardown requested by {self.user}")
        except discord.HTTPException as e:
            logger.error(f"Failed to delete category {self.category.name}: {e}")

        # 3. Delete specified roles (if any)
        for role in self.roles_to_delete:
            try:
                await role.delete(reason=f"Division Teardown requested by {self.user}")
                deleted_roles += 1
            except discord.HTTPException as e:
                logger.error(f"Failed to delete role {role.name}: {e}")

        await interaction.followup.send(
            f"✅ **Division Deleted Successfully**\n"
            f"• **Category & Channels Removed:** `{deleted_channels + 1}`\n"
            f"• **Roles Removed:** `{deleted_roles}`"
        )
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user.id:
            await interaction.response.send_message(
                "❌ You cannot cancel this operation.", ephemeral=True
            )
            return

        await interaction.response.edit_message(
            content="❌ Division deletion canceled.", view=None
        )
        self.stop()


class DivisionManager(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # -------------------------------------------------------------------------
    # 1. CREATE DIVISION
    # -------------------------------------------------------------------------
    @app_commands.command(
        name="createdivision",
        description="Automates the creation of a full game division with custom roles, category, and channels.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(
        game_name="Full game name for Category (e.g. 'World of Warcraft')",
        short_name="Short name/abbreviation for Roles & Channels (e.g. 'WoW'). Optional.",
    )
    async def create_division(
        self, interaction: discord.Interaction, game_name: str, short_name: str = None
    ):
        await interaction.response.defer(ephemeral=True)

        guild = interaction.guild
        if not guild:
            await interaction.followup.send("This command can only be used in a server.")
            return

        clean_game = game_name.strip()
        clean_short = short_name.strip() if short_name else clean_game
        slug_short = clean_short.lower().replace(" ", "-")

        # Standardized Names
        div_staff_role_name = f"{clean_short} Division Staff"
        staff_role_name = f"{clean_short} Staff"
        member_role_name = f"{clean_short} Division"
        category_name = f"{clean_game} Division"

        try:
            # 1. Create Roles
            logger.info(
                f"Creating division roles for '{clean_game}' (Short: '{clean_short}')..."
            )

            div_staff_role = await guild.create_role(
                name=div_staff_role_name,
                color=COLOR_DIVISION_STAFF,
                mentionable=True,
                reason=f"Division Setup: Created by {interaction.user}",
            )

            staff_role = await guild.create_role(
                name=staff_role_name,
                color=COLOR_STAFF,
                mentionable=True,
                reason=f"Division Setup: Created by {interaction.user}",
            )

            member_role = await guild.create_role(
                name=member_role_name,
                color=COLOR_MEMBER,
                mentionable=True,
                reason=f"Division Setup: Created by {interaction.user}",
            )

            # 2. Build Category Permission Overwrites
            category_overwrites = {
                member_role: discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                    connect=True,
                    speak=True,
                    stream=True,
                    use_voice_activation=True,
                ),
                staff_role: discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                    connect=True,
                    speak=True,
                    stream=True,
                    use_voice_activation=True,
                    manage_webhooks=True,
                    create_public_threads=True,
                    create_private_threads=True,
                    send_messages_in_threads=True,
                    mention_everyone=True,
                    manage_messages=True,
                    pin_messages=True,
                    use_application_commands=True,
                    manage_threads=True,
                    send_polls=True,
                    mute_members=True,
                    deafen_members=True,
                    move_members=True,
                    create_events=True,
                    manage_events=True,
                ),
                div_staff_role: discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                    connect=True,
                    speak=True,
                    stream=True,
                    use_voice_activation=True,
                    manage_webhooks=True,
                    create_public_threads=True,
                    create_private_threads=True,
                    send_messages_in_threads=True,
                    mention_everyone=True,
                    manage_messages=True,
                    pin_messages=True,
                    use_application_commands=True,
                    manage_threads=True,
                    send_polls=True,
                    mute_members=True,
                    deafen_members=True,
                    move_members=True,
                    create_events=True,
                    manage_events=True,
                    manage_channels=True,
                    manage_permissions=True,
                ),
            }

            # 3. Create Category
            category = await guild.create_category(
                name=category_name,
                overwrites=category_overwrites,
                reason=f"Division Setup: Created by {interaction.user}",
            )

            # 4. Create Channels
            read_only_overwrites = {
                member_role: discord.PermissionOverwrite(
                    send_messages=False, add_reactions=True
                )
            }

            info_chan = await guild.create_text_channel(
                name=f"{slug_short}-info",
                category=category,
                overwrites=read_only_overwrites,
                reason=f"Division Setup: Created by {interaction.user}",
            )

            announcements_chan = await guild.create_text_channel(
                name=f"{slug_short}-announcements",
                category=category,
                overwrites=read_only_overwrites,
                reason=f"Division Setup: Created by {interaction.user}",
            )

            general_chan = await guild.create_text_channel(
                name=f"{slug_short}-general",
                category=category,
                reason=f"Division Setup: Created by {interaction.user}",
            )

            staff_chan_overwrites = {
                guild.default_role: discord.PermissionOverwrite(view_channel=False),
                member_role: discord.PermissionOverwrite(view_channel=False),
                staff_role: discord.PermissionOverwrite(
                    view_channel=True, send_messages=True, read_message_history=True
                ),
                div_staff_role: discord.PermissionOverwrite(
                    view_channel=True, send_messages=True, read_message_history=True
                ),
            }
            staff_chan = await guild.create_text_channel(
                name=f"{slug_short}-staff",
                category=category,
                overwrites=staff_chan_overwrites,
                reason=f"Division Setup: Created by {interaction.user}",
            )

            clips_chan = await guild.create_text_channel(
                name=f"{slug_short}-clips",
                category=category,
                reason=f"Division Setup: Created by {interaction.user}",
            )

            embed = discord.Embed(
                title=f"✅ Division Created: {clean_game}",
                color=discord.Color.green(),
                timestamp=interaction.created_at,
            )
            embed.add_field(
                name="Roles Created",
                value=(
                    f"• {div_staff_role.mention} (`#e67e22`)\n"
                    f"• {staff_role.mention} (`#f1c40f`)\n"
                    f"• {member_role.mention} (`#ad1457`)"
                ),
                inline=False,
            )
            embed.add_field(name="Category", value=category.name, inline=False)
            embed.add_field(
                name="Channels Created",
                value=(
                    f"• {info_chan.mention}\n"
                    f"• {announcements_chan.mention}\n"
                    f"• {general_chan.mention}\n"
                    f"• {staff_chan.mention}\n"
                    f"• {clips_chan.mention}"
                ),
                inline=False,
            )

            await interaction.followup.send(embed=embed)

        except discord.Forbidden:
            await interaction.followup.send(
                "❌ Bot lacks required permissions (`Manage Roles`, `Manage Channels`)."
            )
        except discord.HTTPException as e:
            logger.error(f"HTTP Error creating division '{clean_game}': {e}")
            await interaction.followup.send(f"❌ Failed to create division: `{e}`")

    # -------------------------------------------------------------------------
    # 2. DELETE DIVISION
    # -------------------------------------------------------------------------
    @app_commands.command(
        name="deletedivision",
        description="Safely deletes a division category, all nested channels, and optionally associated roles.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(
        category="Select the division category to delete",
        delete_roles="Whether to delete division roles alongside channels (Default: True)",
        division_staff_role="Optional override: Division Staff role to delete",
        staff_role="Optional override: Staff role to delete",
        member_role="Optional override: Member Division role to delete",
    )
    async def delete_division(
        self,
        interaction: discord.Interaction,
        category: discord.CategoryChannel,
        delete_roles: bool = True,
        division_staff_role: discord.Role = None,
        staff_role: discord.Role = None,
        member_role: discord.Role = None,
    ):
        guild = interaction.guild
        roles_to_delete = set()

        # Build list of channel mentions/names to display
        channels_list = category.channels
        if channels_list:
            channels_text = "\n".join([f"• {c.mention} (`#{c.name}`)" for c in channels_list])
        else:
            channels_text = "• *No channels inside this category.*"

        # Determine roles to delete if delete_roles is enabled
        if delete_roles:
            def is_valid_custom_role(r: discord.Role) -> bool:
                return (
                    r is not None
                    and r != guild.default_role
                    and not r.is_bot_managed()
                    and not r.is_integration()
                )

            # 1. User manual overrides if provided
            for role in (division_staff_role, staff_role, member_role):
                if is_valid_custom_role(role):
                    roles_to_delete.add(role)

            # 2. Auto-detect roles assigned to the category if no manual roles passed
            if not roles_to_delete:
                for target in category.overwrites.keys():
                    if isinstance(target, discord.Role) and is_valid_custom_role(target):
                        roles_to_delete.add(target)

        roles_list = list(roles_to_delete)
        roles_text = (
            "\n".join([f"• {r.mention}" for r in roles_list])
            if roles_list
            else "• *None (Roles will remain intact)*"
        )

        view = ConfirmDeleteView(
            category=category, roles_to_delete=roles_list, user=interaction.user
        )

        await interaction.response.send_message(
            f"⚠️ **Confirm Division Teardown**\n"
            f"Are you sure you want to delete **{category.name}**?\n\n"
            f"**Channels to be deleted:**\n{channels_text}\n\n"
            f"**Roles to be deleted:**\n{roles_text}\n\n"
            f"*This action cannot be undone.*",
            view=view,
            ephemeral=True,
        )

    # -------------------------------------------------------------------------
    # ERROR HANDLER
    # -------------------------------------------------------------------------
    @create_division.error
    @delete_division.error
    async def division_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ):
        if isinstance(error, app_commands.MissingPermissions):
            msg = "❌ You do not have permission to run this command."
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(DivisionManager(bot))