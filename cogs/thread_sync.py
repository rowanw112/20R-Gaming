import discord
from discord.ext import commands
from discord import app_commands
from core.database import (
    load_thread_mappings, 
    save_thread_mappings, 
    load_dashboard_config, 
    save_dashboard_config
)

class ThreadSync(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def update_dashboard(self, guild: discord.Guild):
        """Builds and edits the live-updating embed in the designated dashboard channel."""
        dash_config = load_dashboard_config()
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

        mappings = load_thread_mappings()

        # Build Embed
        embed = discord.Embed(
            title="📌 Role ➔ Thread Auto-Sync Dashboard",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow()
        )

        # Overview & Purpose Section
        embed.add_field(
            name="📖 Purpose & How It Works",
            value=(
                "Thread Mapping automatically manages member access to private threads based on Discord roles.\n"
                "• **Role Added:** When a member receives a linked role, the bot immediately adds them to the corresponding thread.\n"
                "• **Role Removed:** When the role is removed, the bot automatically removes them from the thread."
            ),
            inline=False
        )

        # Staff Instructions
        embed.add_field(
            name="🛠️ Staff Instructions",
            value=(
                "• Run `/link_thread role:@Role` inside a thread (or specify the thread) to link access.\n"
                "• Run `/unlink_thread role:@Role` inside a thread to remove the auto-sync connection."
            ),
            inline=False
        )

        # Active Mappings List
        if not mappings:
            embed.add_field(
                name="🔗 Active Links", 
                value="*No roles are currently linked to threads.*", 
                inline=False
            )
        else:
            lines = []
            for role_id_str, val in mappings.items():
                # Handle backwards compatibility (if string/int ID was stored directly vs dict)
                if isinstance(val, dict):
                    thread_id = val.get("thread_id")
                    creator_id = val.get("created_by")
                else:
                    thread_id = val
                    creator_id = None

                role = guild.get_role(int(role_id_str))
                
                thread = guild.get_thread(int(thread_id))
                if not thread:
                    try:
                        thread = await guild.fetch_channel(int(thread_id))
                    except (discord.NotFound, discord.HTTPException):
                        thread = None

                role_str = role.mention if role else f"`Unknown Role ({role_id_str})`"
                thread_str = thread.mention if thread else f"`Unknown Thread ({thread_id})`"
                creator_str = f"<@{creator_id}>" if creator_id else "System"

                lines.append(f"• {role_str} ➔ {thread_str} *(Added by {creator_str})*")

            embed.add_field(
                name="🔗 Active Links", 
                value="\n".join(lines), 
                inline=False
            )

        embed.set_footer(text="Auto-updates live on link / unlink")

        # Edit existing message or send a new one
        try:
            if message_id:
                try:
                    msg = await channel.fetch_message(message_id)
                    await msg.edit(embed=embed)
                    return
                except discord.NotFound:
                    pass

            msg = await channel.send(embed=embed)
            save_dashboard_config(channel_id=channel.id, message_id=msg.id)

        except (discord.Forbidden, discord.HTTPException) as e:
            print(f"❌ Dashboard update error in #{channel.name}: {e}")

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        """Triggers when a member's roles change."""
        before_roles = set(before.roles)
        after_roles = set(after.roles)

        added_roles = after_roles - before_roles
        removed_roles = before_roles - after_roles

        if not added_roles and not removed_roles:
            return

        mappings = load_thread_mappings()
        if not mappings:
            return

        # Handle Added Roles
        for role in added_roles:
            role_id_str = str(role.id)
            if role_id_str in mappings:
                val = mappings[role_id_str]
                thread_id = int(val["thread_id"]) if isinstance(val, dict) else int(val)
                
                try:
                    thread = after.guild.get_thread(thread_id) or await after.guild.fetch_channel(thread_id)
                    if isinstance(thread, discord.Thread):
                        try:
                            await thread.add_user(discord.Object(id=self.bot.user.id))
                        except discord.HTTPException:
                            pass

                        await thread.add_user(discord.Object(id=after.id))
                        print(f"✅ Added {after.display_name} to thread '{thread.name}' via role @{role.name}")
                except discord.NotFound:
                    print(f"⚠️ Thread ID {thread_id} not found in guild '{after.guild.name}'.")
                except discord.Forbidden as e:
                    print(f"⚠️ Forbidden (403): {e.text} | Code: {e.code}")
                except discord.HTTPException as e:
                    print(f"❌ Failed to add {after.display_name} to thread: {e}")

        # Handle Removed Roles
        for role in removed_roles:
            role_id_str = str(role.id)
            if role_id_str in mappings:
                val = mappings[role_id_str]
                thread_id = int(val["thread_id"]) if isinstance(val, dict) else int(val)

                try:
                    thread = before.guild.get_thread(thread_id) or await before.guild.fetch_channel(thread_id)
                    if isinstance(thread, discord.Thread):
                        await thread.remove_user(discord.Object(id=before.id))
                        print(f"✅ Removed {before.display_name} from thread '{thread.name}' after role removal @{role.name}")
                except discord.NotFound:
                    print(f"⚠️ Thread ID {thread_id} not found in guild '{before.guild.name}'.")
                except discord.Forbidden as e:
                    print(f"⚠️ Forbidden (403): {e.text} | Code: {e.code}")
                except discord.HTTPException as e:
                    print(f"❌ Failed to remove {before.display_name} from thread: {e}")

    @app_commands.command(name="link_thread", description="Link a Discord Role to a Private Thread.")
    @app_commands.checks.has_permissions(administrator=True)
    async def link_thread(
        self, 
        interaction: discord.Interaction, 
        role: discord.Role, 
        thread: discord.Thread | None = None
    ):
        target_thread = thread or interaction.channel

        if not isinstance(target_thread, discord.Thread):
            await interaction.response.send_message(
                "❌ You must either specify a thread in the `thread` option or run this command inside the target thread!",
                ephemeral=True
            )
            return

        mappings = load_thread_mappings()
        # Save both thread_id and the user ID of whoever ran the command
        mappings[str(role.id)] = {
            "thread_id": target_thread.id,
            "created_by": interaction.user.id
        }
        save_thread_mappings(mappings)

        try:
            await target_thread.add_user(discord.Object(id=self.bot.user.id))
        except discord.HTTPException:
            pass

        await interaction.response.send_message(
            f"✅ Linked **@{role.name}** to thread **{target_thread.name}**!",
            ephemeral=True
        )

        await self.update_dashboard(interaction.guild)

    @app_commands.command(name="unlink_thread", description="Unlink a role from a specific thread.")
    @app_commands.checks.has_permissions(administrator=True)
    async def unlink_thread(
        self, 
        interaction: discord.Interaction, 
        role: discord.Role,
        thread: discord.Thread | None = None
    ):
        target_thread = thread or interaction.channel

        if not isinstance(target_thread, discord.Thread):
            await interaction.response.send_message(
                "❌ You must either run this command **inside the thread** or select a valid thread in the `thread` option!",
                ephemeral=True
            )
            return

        mappings = load_thread_mappings()
        role_id_str = str(role.id)

        if role_id_str in mappings:
            val = mappings[role_id_str]
            thread_id = val["thread_id"] if isinstance(val, dict) else val

            if thread_id == target_thread.id:
                del mappings[role_id_str]
                save_thread_mappings(mappings)
                
                await interaction.response.send_message(
                    f"✅ Successfully unlinked **@{role.name}** from thread **{target_thread.name}**!", 
                    ephemeral=True
                )
                await self.update_dashboard(interaction.guild)
                return

        await interaction.response.send_message(
            f"⚠️ No active link found between **@{role.name}** and thread **{target_thread.name}**.", 
            ephemeral=True
        )

    @app_commands.command(name="set_sync_channel", description="Set the channel where the live role-thread dashboard lives.")
    @app_commands.checks.has_permissions(administrator=True)
    async def set_sync_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        await interaction.response.defer(ephemeral=True)

        save_dashboard_config(channel_id=channel.id, message_id=None)
        await self.update_dashboard(interaction.guild)

        await interaction.followup.send(f"✅ Live dashboard set to {channel.mention}!", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(ThreadSync(bot))