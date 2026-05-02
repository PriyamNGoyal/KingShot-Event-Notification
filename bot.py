import asyncio
import logging
import warnings
from datetime import datetime, timedelta
from pathlib import Path

import discord
import pytz
from discord import app_commands
from discord.ext import commands

from config import (
    BOT_OWNER_USER_ID,
    DEFAULT_REMINDER_LEAD_MINUTES,
    DELETION_POLL_SECONDS,
    DISCORD_TOKEN,
    SCHEDULER_POLL_SECONDS,
)
from database.db import init_db
from database.events import (
    EventConfigRow,
    claim_event_reminder,
    disable_event_config,
    list_due_named_events,
    list_due_one_day_events,
    list_due_events,
    list_event_configs,
    set_event_enabled,
    update_last_notification,
    update_next_occurrence,
    upsert_event_config,
)
from database.history import add_notification_history, list_due_deletions, mark_deleted
from database.settings import (
    GuildSettings,
    add_management_role,
    get_guild_settings,
    list_bear_panel_guild_ids,
    list_management_roles,
    remove_management_role,
    set_announcement_channel,
    set_bear_roles_and_panel,
    set_delete_policy,
    set_role_channel,
    set_timezone,
)
from services.assets import shipped_thumbnail_path, thumbnail_filename
from services.events import (
    APPROVED_EVENT_NAMES,
    EVENT_CONFIG,
    EVENT_LEVEL_ONE_DAY_REMINDER_EVENT_NAMES,
    ONE_DAY_REMINDER_EVENT_NAMES,
    ONE_WEEK_REMINDER_EVENT_NAMES,
    OPEN_RESET_REMINDER_EVENT_NAMES,
    TWO_WEEK_REMINDER_EVENT_NAMES,
    calculate_next_start,
    calculate_following_start,
    event_open_reminder_time,
    find_event_name,
    format_instance_label,
    format_message,
    format_one_day_message,
    format_two_week_message,
    format_one_week_message,
    get_event_config,
    grouped_event_phases,
    grouped_event_schedule,
    is_grouped_event,
    one_day_reminder_time,
    two_week_reminder_time,
    one_week_reminder_time,
    reminder_time,
    reminder_time_for_event,
    should_send_one_day_reminder,
    should_send_two_week_reminder,
    should_send_one_week_reminder,
    validate_configurable_time,
    validate_instance,
)


class _DiscordNoiseFilter(logging.Filter):
    IGNORED_SUBSTRINGS = (
        "PyNaCl is not installed, voice will NOT be supported",
        "davey is not installed, voice will NOT be supported",
        "Privileged message content intent is missing, commands may not work as expected.",
    )

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        return not any(ignored in message for ignored in self.IGNORED_SUBSTRINGS)


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
_discord_noise_filter = _DiscordNoiseFilter()
for logger_name in ("discord.client", "discord.ext.commands.bot"):
    logging.getLogger(logger_name).addFilter(_discord_noise_filter)
warnings.filterwarnings("ignore", message=".*voice will NOT be supported.*")
warnings.filterwarnings("ignore", message=".*Privileged message content intent is missing.*")
logger = logging.getLogger("kingshot_event_notification")

EVENT_CHOICES = [app_commands.Choice(name=name, value=name) for name in APPROVED_EVENT_NAMES]
EVENT_TEST_CHOICES = [*EVENT_CHOICES, app_commands.Choice(name="All Supported Events", value="__all__")]
TEST_ALL_EVENTS_VALUE = "__all__"


def _utc_now() -> datetime:
    return datetime.now(pytz.UTC)


def _is_text_channel(channel: object) -> bool:
    return isinstance(channel, (discord.TextChannel, discord.Thread))


def _event_display_name(event_name: str, instance: str | None) -> str:
    instance_label = format_instance_label(event_name, instance)
    return f"{event_name} {instance_label}" if instance_label else event_name


def _grouped_storage_instances(event_name: str) -> tuple[str, ...]:
    phases = grouped_event_phases(event_name)
    if event_name == "KvK":
        return (*phases, "borders_open")
    return phases


def _grouped_display_phase(event_name: str, instance: str) -> str:
    if event_name == "KvK" and instance == "borders_open":
        return "teleport_window"
    return instance


def _format_datetime_for_timezone(value: datetime, timezone_name: str) -> str:
    timezone = pytz.timezone(timezone_name)
    return value.astimezone(timezone).strftime(f"%Y-%m-%d %H:%M {timezone_name}")


def _format_reset_date_for_timezone(value: datetime, timezone_name: str) -> str:
    timezone = pytz.timezone(timezone_name)
    open_date = value.astimezone(timezone).date()
    return f"{open_date.isoformat()} at server reset (00:00 {timezone_name})"


def _format_configure_response(event_name: str, event_label: str, start_utc: datetime, timezone_name: str) -> str:
    reminder_at = reminder_time_for_event(event_name, start_utc, DEFAULT_REMINDER_LEAD_MINUTES)
    if event_name == "Eternity's Reach":
        return (
            f"Configured {event_label}; it opens {_format_reset_date_for_timezone(start_utc, timezone_name)}. "
            f"Reminder will send at {_format_datetime_for_timezone(reminder_at, timezone_name)}."
        )
    return f"Configured {event_label} for {_format_datetime_for_timezone(start_utc, timezone_name)} (reminder at {_format_datetime_for_timezone(reminder_at, timezone_name)})."


class BearRoleView(discord.ui.View):
    def __init__(self, bot: "KingshotEventBot"):
        super().__init__(timeout=None)
        self.bot = bot

    async def _toggle_bear_role(self, interaction: discord.Interaction, slot: int) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Bear roles can only be managed inside a server.", ephemeral=True)
            return
        settings = await self.bot.get_settings_cached(interaction.guild.id)
        role_id = settings.bear_1_role_id if slot == 1 else settings.bear_2_role_id
        other_role_id = settings.bear_2_role_id if slot == 1 else settings.bear_1_role_id
        if not role_id:
            await interaction.response.send_message(f"Bear {slot} role has not been configured yet.", ephemeral=True)
            return
        role = interaction.guild.get_role(role_id)
        if role is None:
            await interaction.response.send_message(f"Configured Bear {slot} role no longer exists.", ephemeral=True)
            return
        try:
            if role in interaction.user.roles:
                await interaction.user.remove_roles(role, reason="Bear role opt-out")
                await interaction.response.send_message(f"Removed {role.mention}.", ephemeral=True)
                return
            other_role = interaction.guild.get_role(other_role_id) if other_role_id else None
            roles_to_remove = [other_role] if other_role and other_role in interaction.user.roles else []
            if roles_to_remove:
                await interaction.user.remove_roles(*roles_to_remove, reason="Bear role switch")
            await interaction.user.add_roles(role, reason="Bear role opt-in")
            await interaction.response.send_message(f"Assigned {role.mention}.", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("I need Manage Roles and a role position above the Bear roles.", ephemeral=True)
        except Exception as exc:
            logger.exception("Bear role toggle failed guild=%s slot=%s err=%s", interaction.guild.id, slot, exc)
            await interaction.response.send_message("Could not update your Bear role.", ephemeral=True)

    @discord.ui.button(label="Bear 1", style=discord.ButtonStyle.primary, custom_id="bear_role:1")
    async def bear_1(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self._toggle_bear_role(interaction, 1)

    @discord.ui.button(label="Bear 2", style=discord.ButtonStyle.primary, custom_id="bear_role:2")
    async def bear_2(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self._toggle_bear_role(interaction, 2)

    @discord.ui.button(label="Clear Bear Roles", style=discord.ButtonStyle.secondary, custom_id="bear_role:clear")
    async def clear(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Bear roles can only be managed inside a server.", ephemeral=True)
            return
        settings = await self.bot.get_settings_cached(interaction.guild.id)
        roles = [interaction.guild.get_role(role_id) for role_id in (settings.bear_1_role_id, settings.bear_2_role_id) if role_id]
        removable = [role for role in roles if role and role in interaction.user.roles]
        if not removable:
            await interaction.response.send_message("You do not currently have a Bear role.", ephemeral=True)
            return
        try:
            await interaction.user.remove_roles(*removable, reason="Bear role clear")
            await interaction.response.send_message("Cleared your Bear roles.", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("I need Manage Roles and a role position above the Bear roles.", ephemeral=True)


class KingshotEventBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.guilds = True
        intents.members = True
        super().__init__(command_prefix="!", intents=intents, help_command=None)
        self.remove_command("help")
        self.settings_cache: dict[int, GuildSettings] = {}
        self.management_role_ids_cache: dict[int, list[int]] = {}
        self.bg_tasks: list[asyncio.Task] = []

    async def setup_hook(self) -> None:
        await init_db()
        self.add_view(BearRoleView(self))
        self.register_commands()
        await self.tree.sync()
        self.bg_tasks.append(asyncio.create_task(self.scheduler_loop()))
        self.bg_tasks.append(asyncio.create_task(self.cleanup_loop()))

    async def on_ready(self) -> None:
        logger.info("Bot ready as %s", self.user)
        panel_guilds = await list_bear_panel_guild_ids()
        logger.info("Persistent Bear role view registered; known panels=%s", len(panel_guilds))

    async def get_settings_cached(self, guild_id: int) -> GuildSettings:
        if guild_id not in self.settings_cache:
            self.settings_cache[guild_id] = await get_guild_settings(guild_id)
        return self.settings_cache[guild_id]

    def invalidate_settings(self, guild_id: int) -> None:
        self.settings_cache.pop(guild_id, None)

    async def get_management_role_ids_cached(self, guild_id: int) -> list[int]:
        if guild_id not in self.management_role_ids_cache:
            self.management_role_ids_cache[guild_id] = await list_management_roles(guild_id)
        return self.management_role_ids_cache[guild_id]

    def _is_owner_user(self, user_id: int) -> bool:
        return bool(BOT_OWNER_USER_ID and user_id == BOT_OWNER_USER_ID)

    async def _can_manage(self, interaction: discord.Interaction) -> bool:
        if interaction.guild_id is None:
            return False
        if self._is_owner_user(interaction.user.id):
            return True
        roles = getattr(interaction.user, "roles", [])
        allowed_role_ids = set(await self.get_management_role_ids_cached(interaction.guild_id))
        return bool(allowed_role_ids and any(getattr(role, "id", 0) in allowed_role_ids for role in roles))

    async def _require_manage(self, interaction: discord.Interaction) -> bool:
        if await self._can_manage(interaction):
            return True
        await interaction.response.send_message("You do not have access to this command.", ephemeral=True)
        return False

    async def _fetch_messageable_channel(self, channel_id: int) -> discord.abc.Messageable | None:
        channel = self.get_channel(channel_id)
        if channel is None:
            try:
                channel = await self.fetch_channel(channel_id)
            except Exception as exc:
                logger.warning("Could not fetch channel=%s err=%s", channel_id, exc)
                return None
        return channel if isinstance(channel, discord.abc.Messageable) else None

    async def _get_or_create_bear_role(self, guild: discord.Guild, name: str) -> discord.Role:
        role = discord.utils.get(guild.roles, name=name)
        if role:
            return role
        return await guild.create_role(name=name, mentionable=True, reason="Kingshot Bear role setup")

    async def _send_or_update_bear_panel(self, guild: discord.Guild, settings: GuildSettings, role_1: discord.Role, role_2: discord.Role) -> discord.Message:
        if not settings.role_channel_id:
            raise ValueError("Set the Bear role channel first with /settings set-role-channel")
        channel = await self._fetch_messageable_channel(settings.role_channel_id)
        if not channel or not _is_text_channel(channel):
            raise ValueError("Configured role channel is missing or is not a text channel")
        embed = discord.Embed(
            title="Bear Trap Role Selection",
            description=(
                f"Choose {role_1.mention} or {role_2.mention} to receive the matching Bear Trap reminder.\n"
                "Use Clear Bear Roles to remove both Bear roles."
            ),
            color=discord.Color.gold(),
        )
        if settings.bear_panel_message_id:
            try:
                old_message = await channel.fetch_message(settings.bear_panel_message_id)
                await old_message.edit(embed=embed, view=BearRoleView(self))
                return old_message
            except Exception as exc:
                logger.warning("Could not update Bear panel guild=%s message=%s err=%s", guild.id, settings.bear_panel_message_id, exc)
        return await channel.send(embed=embed, view=BearRoleView(self), allowed_mentions=discord.AllowedMentions(roles=False))

    async def _delete_message(self, channel_id: int, message_id: int) -> None:
        channel = await self._fetch_messageable_channel(channel_id)
        if not channel:
            return
        try:
            message = await channel.fetch_message(message_id)
            await message.delete()
        except discord.NotFound:
            return
        except discord.Forbidden as exc:
            logger.warning("Missing permission deleting channel=%s message=%s err=%s", channel_id, message_id, exc)
        except Exception as exc:
            logger.warning("Delete failed channel=%s message=%s err=%s", channel_id, message_id, exc)

    async def _send_bear_role_announcement(self, guild: discord.Guild, settings: GuildSettings, role_1: discord.Role, role_2: discord.Role, panel: discord.Message) -> discord.Message | None:
        if not settings.announcement_channel_id:
            logger.warning("No announcement channel for Bear role setup guild=%s", guild.id)
            return None
        channel = await self._fetch_messageable_channel(settings.announcement_channel_id)
        if not channel or not _is_text_channel(channel):
            logger.warning("Configured announcement channel missing/invalid for Bear role setup guild=%s", guild.id)
            return None
        role_channel_text = f" in <#{settings.role_channel_id}>" if settings.role_channel_id else ""
        content = (
            f"@everyone Bear Trap role selection is ready{role_channel_text}. "
            f"Please assign yourself {role_1.mention} or {role_2.mention} using the Bear role panel: {panel.jump_url}"
        )
        return await channel.send(content=content, allowed_mentions=discord.AllowedMentions(everyone=True, roles=True))

    def _build_notification(
        self,
        row: EventConfigRow,
        settings: GuildSettings,
        reminder_phase: str = "final",
        thumbnail_attachment_filename: str | None = None,
        thumbnail_url: str | None = None,
        suppress_mentions: bool = False,
    ) -> tuple[str, discord.Embed, discord.AllowedMentions]:
        if reminder_phase == "two_week":
            title, body = format_two_week_message(row.event_name, row.instance, row.next_occurrence_utc, settings.timezone)
        elif reminder_phase == "one_week":
            title, body = format_one_week_message(row.event_name, row.instance, row.next_occurrence_utc, settings.timezone)
        elif reminder_phase == "one_day":
            title, body = format_one_day_message(row.event_name, row.instance, row.next_occurrence_utc, settings.timezone)
        else:
            title, body = format_message(row.event_name, row.instance, row.next_occurrence_utc, DEFAULT_REMINDER_LEAD_MINUTES, settings.timezone)
        mention = "@everyone"
        allowed_mentions = discord.AllowedMentions(everyone=True, roles=False)
        if row.event_name == "Bear Trap" and reminder_phase != "one_day":
            role_id = settings.bear_1_role_id if row.instance == "bear_1" else settings.bear_2_role_id
            mention = f"<@&{role_id}>" if role_id else ""
            allowed_mentions = discord.AllowedMentions(everyone=False, roles=True)
        if suppress_mentions:
            mention = ""
            allowed_mentions = discord.AllowedMentions(everyone=False, roles=False, users=False)
        hide_eternity_time = row.event_name == "Eternity's Reach" and reminder_phase == "final"
        event_level_one_day = row.event_name in EVENT_LEVEL_ONE_DAY_REMINDER_EVENT_NAMES and reminder_phase == "one_day"
        timestamp = None if hide_eternity_time else row.next_occurrence_utc
        embed = discord.Embed(title=title, description=body, color=discord.Color.orange(), timestamp=timestamp)
        if hide_eternity_time:
            embed.add_field(name="Opens (server time)", value=_format_reset_date_for_timezone(row.next_occurrence_utc, settings.timezone), inline=True)
        elif event_level_one_day:
            reset_utc = pytz.UTC.localize(datetime.combine(row.next_occurrence_utc.astimezone(pytz.UTC).date(), datetime.min.time()))
            embed.add_field(name="Opens (server reset)", value=f"<t:{int(reset_utc.timestamp())}:F>", inline=True)
        else:
            embed.add_field(name="Start (your time)", value=f"<t:{int(row.next_occurrence_utc.timestamp())}:F>", inline=True)
        if reminder_phase == "two_week":
            reminder_label = "2 weeks before"
        elif reminder_phase == "one_week":
            reminder_label = "1 week before"
        elif reminder_phase == "one_day":
            reminder_label = "15 minutes before server reset" if event_level_one_day else "1 day before"
        elif row.event_name in OPEN_RESET_REMINDER_EVENT_NAMES:
            reminder_at = event_open_reminder_time(row.next_occurrence_utc, DEFAULT_REMINDER_LEAD_MINUTES)
            if hide_eternity_time:
                reminder_label = _format_datetime_for_timezone(reminder_at, settings.timezone)
            else:
                reminder_label = f"15 minutes before server reset on event-open date ({reminder_at.strftime('%Y-%m-%d %H:%M UTC')})"
        else:
            reminder_label = f"{DEFAULT_REMINDER_LEAD_MINUTES} minutes before"
        reminder_field_name = "Reminder sent (server time)" if hide_eternity_time else "Reminder"
        embed.add_field(name=reminder_field_name, value=reminder_label, inline=True)
        instance_label = format_instance_label(row.event_name, row.instance)
        if instance_label and not event_level_one_day:
            embed.add_field(name="Instance", value=instance_label, inline=True)
        if thumbnail_attachment_filename:
            embed.set_thumbnail(url=f"attachment://{thumbnail_attachment_filename}")
        elif thumbnail_url:
            embed.set_thumbnail(url=thumbnail_url)
        return mention, embed, allowed_mentions

    async def _notification_thumbnail_file(self, event_name: str) -> discord.File | None:
        thumbnail_path = shipped_thumbnail_path(event_name)
        filename = thumbnail_filename(event_name)
        if not thumbnail_path or not filename:
            return None
        try:
            return discord.File(Path(thumbnail_path), filename=filename)
        except Exception as exc:
            logger.warning("Could not attach shipped thumbnail event=%s path=%s err=%s", event_name, thumbnail_path, exc)
            return None

    async def _send_event_notification_to_channel(
        self,
        row: EventConfigRow,
        settings: GuildSettings,
        channel: discord.abc.Messageable,
        test_only: bool = False,
        reminder_phase: str = "final",
        suppress_mentions: bool = False,
    ) -> discord.Message | None:
        if not test_only and reminder_phase == "final" and row.last_notification_channel_id and row.last_notification_message_id:
            await self._delete_message(row.last_notification_channel_id, row.last_notification_message_id)
        thumbnail_file = await self._notification_thumbnail_file(row.event_name)
        thumbnail_filename_value = thumbnail_file.filename if thumbnail_file else None
        event_meta = get_event_config(row.event_name) or {}
        fallback_thumbnail_url = event_meta.get("thumbnail_url") if not thumbnail_file else None
        mention, embed, allowed_mentions = self._build_notification(row, settings, reminder_phase, thumbnail_filename_value, fallback_thumbnail_url, suppress_mentions)
        content = mention if test_only or mention else mention
        if test_only:
            embed.title = f"TEST: {embed.title}"
            embed.set_footer(text="Dummy test notification. No real event configuration or announcement channel is required.")
        if thumbnail_file:
            message = await channel.send(content=content, embed=embed, file=thumbnail_file, allowed_mentions=allowed_mentions)
        else:
            message = await channel.send(content=content, embed=embed, allowed_mentions=allowed_mentions)
        if not test_only:
            duration_minutes = int(EVENT_CONFIG[row.event_name].get("duration_minutes") or settings.delete_delay_minutes)
            delete_enabled = settings.delete_enabled if row.delete_enabled is None else row.delete_enabled
            delay = row.delete_delay_minutes or duration_minutes or settings.delete_delay_minutes
            scheduled_delete = row.next_occurrence_utc + timedelta(minutes=delay) if delete_enabled else None
            await add_notification_history(row.guild_id, row.event_name, row.instance, message.channel.id, message.id, scheduled_delete)
            if reminder_phase == "final":
                await update_last_notification(row.id, message.channel.id, message.id)
        logger.info("Sent notification guild=%s event=%s instance=%s channel=%s test=%s phase=%s", row.guild_id, row.event_name, row.instance, message.channel.id, test_only, reminder_phase)
        return message

    async def _send_event_notification(self, row: EventConfigRow, test_only: bool = False, reminder_phase: str = "final") -> discord.Message | None:
        settings = await self.get_settings_cached(row.guild_id)
        if not settings.announcement_channel_id:
            logger.warning("No announcement channel guild=%s event=%s instance=%s", row.guild_id, row.event_name, row.instance)
            return None
        channel = await self._fetch_messageable_channel(settings.announcement_channel_id)
        if not channel:
            return None
        return await self._send_event_notification_to_channel(row, settings, channel, test_only, reminder_phase)

    async def _send_event_notification_ephemeral_test(
        self,
        interaction: discord.Interaction,
        row: EventConfigRow,
        settings: GuildSettings,
        reminder_phase: str = "final",
    ) -> None:
        thumbnail_file = await self._notification_thumbnail_file(row.event_name)
        thumbnail_filename_value = thumbnail_file.filename if thumbnail_file else None
        event_meta = get_event_config(row.event_name) or {}
        fallback_thumbnail_url = event_meta.get("thumbnail_url") if not thumbnail_file else None
        mention, embed, allowed_mentions = self._build_notification(
            row,
            settings,
            reminder_phase,
            thumbnail_filename_value,
            fallback_thumbnail_url,
            suppress_mentions=True,
        )
        embed.title = f"TEST: {embed.title}"
        embed.set_footer(text="Dummy test notification. No real event configuration or announcement channel is required.")
        content = mention or None
        if thumbnail_file:
            await interaction.followup.send(content=content, embed=embed, file=thumbnail_file, allowed_mentions=allowed_mentions, ephemeral=True)
        else:
            await interaction.followup.send(content=content, embed=embed, allowed_mentions=allowed_mentions, ephemeral=True)

    def _dummy_event_start(self, event_name: str, instance: str) -> datetime:
        now = _utc_now()
        if event_name in OPEN_RESET_REMINDER_EVENT_NAMES:
            return pytz.UTC.localize(datetime.combine((now + timedelta(days=1)).date(), datetime.min.time())) + timedelta(hours=12)
        if event_name == "Swordland Showdown":
            return pytz.UTC.localize(datetime.combine((now + timedelta(days=1)).date(), datetime.min.time())) + timedelta(hours=12)
        if event_name == "Castle Battle" and instance == "teleport_window":
            return now + timedelta(minutes=DEFAULT_REMINDER_LEAD_MINUTES, hours=1)
        if event_name == "KvK" and instance == "teleport_window":
            return now + timedelta(minutes=DEFAULT_REMINDER_LEAD_MINUTES, hours=2)
        return now + timedelta(minutes=DEFAULT_REMINDER_LEAD_MINUTES, hours=3)

    def _dummy_event_row(self, guild_id: int, event_name: str, instance: str) -> EventConfigRow:
        next_start = self._dummy_event_start(event_name, instance)
        return EventConfigRow(
            id=0,
            guild_id=guild_id,
            event_name=event_name,
            instance=instance,
            enabled=True,
            event_time=next_start.strftime("%H:%M"),
            event_date=next_start.strftime("%Y-%m-%d"),
            timezone="UTC",
            next_occurrence_utc=next_start,
            mention_mode="test",
            delete_enabled=None,
            delete_delay_minutes=None,
            last_notification_message_id=None,
            last_notification_channel_id=None,
        )

    def _dummy_test_instances(self, event_name: str, instance: str | None) -> list[str]:
        if is_grouped_event(event_name):
            if instance:
                normalized_instance = validate_instance(event_name, instance)
                if normalized_instance not in grouped_event_phases(event_name):
                    raise ValueError(f"{event_name} test instance must be one of: {', '.join(grouped_event_phases(event_name))}")
                return [normalized_instance]
            return list(grouped_event_phases(event_name))
        config = get_event_config(event_name) or {}
        instances = config.get("instances") or []
        if instance:
            return [validate_instance(event_name, instance)]
        if instances:
            return list(instances)
        return ["default"]

    def _dummy_test_rows(self, guild_id: int, event_name: str, instance: str | None) -> list[EventConfigRow]:
        if event_name == TEST_ALL_EVENTS_VALUE:
            rows: list[EventConfigRow] = []
            for approved_event_name in APPROVED_EVENT_NAMES:
                for test_instance in self._dummy_test_instances(approved_event_name, None):
                    rows.append(self._dummy_event_row(guild_id, approved_event_name, test_instance))
            return rows
        return [self._dummy_event_row(guild_id, event_name, test_instance) for test_instance in self._dummy_test_instances(event_name, instance)]

    def _dummy_test_reminder_cases(self, rows: list[EventConfigRow]) -> list[tuple[EventConfigRow, str]]:
        cases: list[tuple[EventConfigRow, str]] = []
        event_level_one_day_keys: set[tuple[int, str, int]] = set()
        for row in rows:
            if should_send_two_week_reminder(row.event_name, row.instance):
                cases.append((row, "two_week"))
            if should_send_one_week_reminder(row.event_name, row.instance):
                cases.append((row, "one_week"))
            if should_send_one_day_reminder(row.event_name, row.instance):
                if row.event_name in EVENT_LEVEL_ONE_DAY_REMINDER_EVENT_NAMES:
                    event_date = row.next_occurrence_utc.astimezone(pytz.UTC).date().toordinal()
                    event_key = (row.guild_id, row.event_name, event_date)
                    if event_key not in event_level_one_day_keys:
                        cases.append((row, "one_day"))
                        event_level_one_day_keys.add(event_key)
                else:
                    cases.append((row, "one_day"))
            cases.append((row, "final"))
        return cases

    async def _advance_or_disable_event(self, row: EventConfigRow) -> None:
        try:
            next_start = calculate_following_start(row.event_name, row.event_time, row.timezone, row.next_occurrence_utc, _utc_now() + timedelta(minutes=1), row.instance)
            await update_next_occurrence(row.id, next_start)
        except Exception as exc:
            logger.warning("Could not advance event; disabling guild=%s event=%s instance=%s err=%s", row.guild_id, row.event_name, row.instance, exc)
            await set_event_enabled(row.id, False)

    async def _configure_grouped_event(self, interaction: discord.Interaction, event_name: str, time: str | None, date: str | None) -> None:
        if not date:
            if event_name == "KvK" and time and len(time) == 10 and time.count("-") == 2:
                date = time
                time = None
            else:
                raise ValueError(f"{event_name} requires a UTC date in YYYY-MM-DD format.")
        schedule = grouped_event_schedule(event_name, date, time, _utc_now())
        for phase, next_start in schedule.items():
            await upsert_event_config(interaction.guild_id, event_name, phase, next_start.strftime("%H:%M"), next_start.strftime("%Y-%m-%d"), "UTC", next_start, "everyone")

    def _format_grouped_config_response(self, event_name: str, schedule: dict[str, datetime]) -> str:
        lines = [f"Configured {event_name}:"]
        for phase in grouped_event_phases(event_name):
            start = schedule[phase]
            phase_label = format_instance_label(event_name, phase) or phase
            lines.append(
                f"- {phase_label}: <t:{int(start.timestamp())}:F> "
                f"(reminder <t:{int(reminder_time_for_event(event_name, start, DEFAULT_REMINDER_LEAD_MINUTES).timestamp())}:R>)"
            )
        if event_name == "Castle Battle":
            lines.append("Teleport Window was calculated automatically as 1 hour before battle start.")
        elif event_name == "KvK":
            lines.append("KvK times were calculated automatically: Borders & Teleport Open 10:00 UTC, Battle Start 12:00 UTC.")
        return "\n".join(lines)

    async def _disable_event_by_user_request(self, guild_id: int, event_name: str, instance: str | None) -> bool:
        if is_grouped_event(event_name) and not instance:
            disabled_any = False
            for phase in _grouped_storage_instances(event_name):
                disabled_any = await disable_event_config(guild_id, event_name, phase) or disabled_any
            return disabled_any
        if event_name == "KvK" and (instance or "").strip().lower() == "borders_open":
            disabled_legacy = await disable_event_config(guild_id, event_name, "borders_open")
            disabled_current = await disable_event_config(guild_id, event_name, "teleport_window")
            return disabled_legacy or disabled_current
        normalized_instance = validate_instance(event_name, instance)
        return await disable_event_config(guild_id, event_name, normalized_instance)

    async def scheduler_loop(self) -> None:
        await asyncio.sleep(5)
        while True:
            try:
                two_week_rows = await list_due_one_day_events(_utc_now() + timedelta(days=14), sorted(TWO_WEEK_REMINDER_EVENT_NAMES))
                for row in two_week_rows:
                    if not should_send_two_week_reminder(row.event_name, row.instance):
                        continue
                    if two_week_reminder_time(row.next_occurrence_utc) <= _utc_now():
                        if await claim_event_reminder(row.id, row.next_occurrence_utc, "two_week"):
                            await self._send_event_notification(row, reminder_phase="two_week")
                one_week_rows = await list_due_one_day_events(_utc_now() + timedelta(days=7), sorted(ONE_WEEK_REMINDER_EVENT_NAMES))
                for row in one_week_rows:
                    if not should_send_one_week_reminder(row.event_name, row.instance):
                        continue
                    if one_week_reminder_time(row.next_occurrence_utc) <= _utc_now():
                        if await claim_event_reminder(row.id, row.next_occurrence_utc, "one_week"):
                            await self._send_event_notification(row, reminder_phase="one_week")
                one_day_rows = await list_due_one_day_events(_utc_now() + timedelta(days=1), sorted(ONE_DAY_REMINDER_EVENT_NAMES))
                event_level_one_day_keys: set[tuple[int, str, int]] = set()
                for row in one_day_rows:
                    if not should_send_one_day_reminder(row.event_name, row.instance):
                        continue
                    if row.event_name in EVENT_LEVEL_ONE_DAY_REMINDER_EVENT_NAMES:
                        event_date = row.next_occurrence_utc.astimezone(pytz.UTC).date().toordinal()
                        event_key = (row.guild_id, row.event_name, event_date)
                        if event_key in event_level_one_day_keys:
                            continue
                        event_level_one_day_keys.add(event_key)
                    if row.event_name in EVENT_LEVEL_ONE_DAY_REMINDER_EVENT_NAMES:
                        one_day_due = event_open_reminder_time(row.next_occurrence_utc, DEFAULT_REMINDER_LEAD_MINUTES)
                    else:
                        one_day_due = one_day_reminder_time(row.next_occurrence_utc)
                    if one_day_due <= _utc_now():
                        if await claim_event_reminder(row.id, row.next_occurrence_utc, "one_day"):
                            await self._send_event_notification(row, reminder_phase="one_day")
                open_reset_rows = await list_due_named_events(_utc_now() + timedelta(days=1), sorted(OPEN_RESET_REMINDER_EVENT_NAMES))
                for row in open_reset_rows:
                    if event_open_reminder_time(row.next_occurrence_utc, DEFAULT_REMINDER_LEAD_MINUTES) <= _utc_now():
                        if await claim_event_reminder(row.id, row.next_occurrence_utc, "final"):
                            await self._send_event_notification(row)
                        await self._advance_or_disable_event(row)
                due_rows = await list_due_events(_utc_now() + timedelta(minutes=DEFAULT_REMINDER_LEAD_MINUTES))
                for row in due_rows:
                    if row.event_name in OPEN_RESET_REMINDER_EVENT_NAMES:
                        continue
                    if reminder_time(row.next_occurrence_utc, DEFAULT_REMINDER_LEAD_MINUTES) <= _utc_now():
                        if await claim_event_reminder(row.id, row.next_occurrence_utc, "final"):
                            await self._send_event_notification(row)
                        await self._advance_or_disable_event(row)
            except Exception as exc:
                logger.exception("Scheduler loop failed: %s", exc)
            await asyncio.sleep(max(10, SCHEDULER_POLL_SECONDS))

    async def cleanup_loop(self) -> None:
        await asyncio.sleep(10)
        while True:
            try:
                for history_id, channel_id, message_id in await list_due_deletions(_utc_now()):
                    await self._delete_message(channel_id, message_id)
                    await mark_deleted(history_id)
            except Exception as exc:
                logger.exception("Cleanup loop failed: %s", exc)
            await asyncio.sleep(max(10, DELETION_POLL_SECONDS))

    def register_commands(self) -> None:
        @self.tree.command(name="help", description="Show Kingshot event notification bot usage")
        async def help_cmd(interaction: discord.Interaction) -> None:
            await interaction.response.send_message(
                "Commands:\n"
                "/settings set-role-channel <channel>\n"
                "/settings set-announcement-channel <channel>\n"
                "/settings set-timezone <timezone>\n"
                "/settings set-delete-policy <enabled> [delay_minutes]\n"
                "/settings setup-bear-roles\n"
                "/settings show\n"
                "/events configure <event> [time] [date] [instance]\n"
                "/events disable <event> [instance]\n"
                "/events list\n"
                "/events test <event|all> [instance]",
                ephemeral=True,
            )

        settings_group = app_commands.Group(name="settings", description="Configure notification bot settings")

        @settings_group.command(name="set-role-channel", description="Set where Bear role buttons are posted")
        async def set_role_channel_cmd(interaction: discord.Interaction, channel: discord.TextChannel) -> None:
            if not await self._require_manage(interaction):
                return
            await set_role_channel(interaction.guild_id, channel.id)
            self.invalidate_settings(interaction.guild_id)
            await interaction.response.send_message(f"Bear role channel set to {channel.mention}.", ephemeral=True)

        @settings_group.command(name="set-announcement-channel", description="Set where event reminders are sent")
        async def set_announcement_channel_cmd(interaction: discord.Interaction, channel: discord.TextChannel) -> None:
            if not await self._require_manage(interaction):
                return
            await set_announcement_channel(interaction.guild_id, channel.id)
            self.invalidate_settings(interaction.guild_id)
            await interaction.response.send_message(f"Announcement channel set to {channel.mention}.", ephemeral=True)

        @settings_group.command(name="set-timezone", description="Set the default guild timezone")
        async def set_timezone_cmd(interaction: discord.Interaction, timezone_name: str) -> None:
            if not await self._require_manage(interaction):
                return
            try:
                pytz.timezone(timezone_name)
            except Exception:
                await interaction.response.send_message("Invalid timezone. Use an IANA name like UTC or Asia/Kolkata.", ephemeral=True)
                return
            await set_timezone(interaction.guild_id, timezone_name)
            self.invalidate_settings(interaction.guild_id)
            await interaction.response.send_message(f"Timezone set to `{timezone_name}`.", ephemeral=True)

        @settings_group.command(name="set-delete-policy", description="Set automatic notification cleanup")
        async def set_delete_policy_cmd(interaction: discord.Interaction, enabled: bool, delay_minutes: int = 60) -> None:
            if not await self._require_manage(interaction):
                return
            if delay_minutes < 1:
                await interaction.response.send_message("Delay must be at least 1 minute.", ephemeral=True)
                return
            await set_delete_policy(interaction.guild_id, enabled, delay_minutes)
            self.invalidate_settings(interaction.guild_id)
            await interaction.response.send_message(f"Delete policy set: enabled={enabled}, delay={delay_minutes} minutes.", ephemeral=True)

        @settings_group.command(name="setup-bear-roles", description="Create/reuse Bear roles and post the persistent button panel")
        async def setup_bear_roles_cmd(interaction: discord.Interaction) -> None:
            if not await self._require_manage(interaction):
                return
            if interaction.guild is None:
                await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
                return
            await interaction.response.defer(ephemeral=True, thinking=True)
            try:
                settings = await self.get_settings_cached(interaction.guild.id)
                role_1 = await self._get_or_create_bear_role(interaction.guild, "Bear 1")
                role_2 = await self._get_or_create_bear_role(interaction.guild, "Bear 2")
                panel = await self._send_or_update_bear_panel(interaction.guild, settings, role_1, role_2)
                await self._send_bear_role_announcement(interaction.guild, settings, role_1, role_2, panel)
                await set_bear_roles_and_panel(interaction.guild.id, role_1.id, role_2.id, panel.id)
                self.invalidate_settings(interaction.guild.id)
                await interaction.followup.send(f"Bear roles configured and panel posted/updated: {panel.jump_url}", ephemeral=True)
            except discord.Forbidden:
                await interaction.followup.send("I need Manage Roles plus Send Messages/Embed Links in the role channel.", ephemeral=True)
            except Exception as exc:
                logger.exception("Bear setup failed guild=%s err=%s", interaction.guild.id, exc)
                await interaction.followup.send(str(exc), ephemeral=True)

        @settings_group.command(name="show", description="Show current settings")
        async def show_settings_cmd(interaction: discord.Interaction) -> None:
            if not await self._require_manage(interaction):
                return
            settings = await self.get_settings_cached(interaction.guild_id)
            manage_roles = await self.get_management_role_ids_cached(interaction.guild_id)
            await interaction.response.send_message(
                f"Role channel: {f'<#{settings.role_channel_id}>' if settings.role_channel_id else 'Not set'}\n"
                f"Announcement channel: {f'<#{settings.announcement_channel_id}>' if settings.announcement_channel_id else 'Not set'}\n"
                f"Timezone: `{settings.timezone}`\n"
                f"Delete policy: `{settings.delete_enabled}` after `{settings.delete_delay_minutes}` minutes fallback\n"
                f"Bear 1 role: {f'<@&{settings.bear_1_role_id}>' if settings.bear_1_role_id else 'Not set'}\n"
                f"Bear 2 role: {f'<@&{settings.bear_2_role_id}>' if settings.bear_2_role_id else 'Not set'}\n"
                f"Bear panel message ID: `{settings.bear_panel_message_id or 'Not set'}`\n"
                f"Manage roles: {' '.join(f'<@&{role_id}>' for role_id in manage_roles) if manage_roles else 'None'}\n"
                f"Owner ID: `{BOT_OWNER_USER_ID}`",
                ephemeral=True,
            )

        @settings_group.command(name="add-manage-role", description="Allow a role to manage this bot; owner only")
        async def add_manage_role_cmd(interaction: discord.Interaction, role: discord.Role) -> None:
            if not self._is_owner_user(interaction.user.id):
                await interaction.response.send_message("Only the bot owner can change manage roles.", ephemeral=True)
                return
            added = await add_management_role(interaction.guild_id, role.id)
            self.management_role_ids_cache.pop(interaction.guild_id, None)
            await interaction.response.send_message(f"{role.mention} added." if added else f"{role.mention} is already allowed.", ephemeral=True)

        @settings_group.command(name="remove-manage-role", description="Remove a bot manage role; owner only")
        async def remove_manage_role_cmd(interaction: discord.Interaction, role: discord.Role) -> None:
            if not self._is_owner_user(interaction.user.id):
                await interaction.response.send_message("Only the bot owner can change manage roles.", ephemeral=True)
                return
            removed = await remove_management_role(interaction.guild_id, role.id)
            self.management_role_ids_cache.pop(interaction.guild_id, None)
            await interaction.response.send_message(f"{role.mention} removed." if removed else f"{role.mention} was not configured.", ephemeral=True)

        @settings_group.command(name="list-manage-roles", description="List bot manage roles")
        async def list_manage_roles_cmd(interaction: discord.Interaction) -> None:
            if not await self._require_manage(interaction):
                return
            role_ids = await self.get_management_role_ids_cached(interaction.guild_id)
            await interaction.response.send_message("Manage roles: " + (" ".join(f"<@&{role_id}>" for role_id in role_ids) if role_ids else "None"), ephemeral=True)

        events_group = app_commands.Group(name="events", description="Configure Kingshot event reminders")

        @events_group.command(name="configure", description="Enable/configure an approved event reminder")
        @app_commands.choices(event=EVENT_CHOICES)
        async def configure_event_cmd(interaction: discord.Interaction, event: app_commands.Choice[str], time: str | None = None, date: str | None = None, instance: str | None = None) -> None:
            if not await self._require_manage(interaction):
                return
            try:
                event_name = find_event_name(event.value)
                if is_grouped_event(event_name):
                    schedule = grouped_event_schedule(event_name, date or (time if event_name == "KvK" else None), time if event_name == "Castle Battle" else None, _utc_now())
                    await self._configure_grouped_event(interaction, event_name, time, date)
                    await interaction.response.send_message(self._format_grouped_config_response(event_name, schedule), ephemeral=True)
                    return
                settings = await self.get_settings_cached(interaction.guild_id)
                if not time:
                    raise ValueError(f"{event_name} requires a time in HH:MM format.")
                normalized_instance = validate_instance(event_name, instance)
                validate_configurable_time(event_name, time)
                next_start = calculate_next_start(event_name, time, settings.timezone, date, None, normalized_instance)
                mention_mode = "bear_role" if event_name == "Bear Trap" else "everyone"
                await upsert_event_config(interaction.guild_id, event_name, normalized_instance, time, date, settings.timezone, next_start, mention_mode)
                event_label = _event_display_name(event_name, normalized_instance)
                await interaction.response.send_message(_format_configure_response(event_name, event_label, next_start, settings.timezone), ephemeral=True)
            except Exception as exc:
                await interaction.response.send_message(str(exc), ephemeral=True)

        @events_group.command(name="disable", description="Disable a configured event")
        @app_commands.choices(event=EVENT_CHOICES)
        async def disable_event_cmd(interaction: discord.Interaction, event: app_commands.Choice[str], instance: str | None = None) -> None:
            if not await self._require_manage(interaction):
                return
            try:
                event_name = find_event_name(event.value)
                disabled = await self._disable_event_by_user_request(interaction.guild_id, event_name, instance)
                event_label = event_name if is_grouped_event(event_name) and not instance else _event_display_name(event_name, validate_instance(event_name, instance))
                await interaction.response.send_message(f"{event_label} disabled." if disabled else "No matching configured event found.", ephemeral=True)
            except Exception as exc:
                await interaction.response.send_message(str(exc), ephemeral=True)

        @events_group.command(name="list", description="List configured event reminders")
        async def list_events_cmd(interaction: discord.Interaction) -> None:
            if not await self._require_manage(interaction):
                return
            rows = await list_event_configs(interaction.guild_id)
            if not rows:
                await interaction.response.send_message("No events configured.", ephemeral=True)
                return
            lines = []
            grouped: dict[str, list[EventConfigRow]] = {}
            visible_rows: list[EventConfigRow] = []
            for row in rows:
                if is_grouped_event(row.event_name) and row.instance in _grouped_storage_instances(row.event_name):
                    grouped.setdefault(row.event_name, []).append(row)
                else:
                    visible_rows.append(row)
            for event_name, phase_rows in grouped.items():
                phase_rows_by_instance: dict[str, EventConfigRow] = {}
                for row in phase_rows:
                    display_phase = _grouped_display_phase(event_name, row.instance)
                    if display_phase not in phase_rows_by_instance or row.instance != "borders_open":
                        phase_rows_by_instance[display_phase] = row
                battle_row = phase_rows_by_instance.get("battle_start") or phase_rows[0]
                status = "enabled" if any(row.enabled for row in phase_rows) else "disabled"
                phase_text = []
                for phase in grouped_event_phases(event_name):
                        phase_row = phase_rows_by_instance.get(phase)
                        if phase_row:
                            phase_label = format_instance_label(event_name, phase) or phase
                        phase_text.append(f"{phase_label} {_format_datetime_for_timezone(phase_row.next_occurrence_utc, phase_row.timezone)}")
                reminder_at = reminder_time_for_event(event_name, battle_row.next_occurrence_utc, DEFAULT_REMINDER_LEAD_MINUTES)
                lines.append(f"{event_name}: {status}, {', '.join(phase_text)}, battle reminder {_format_datetime_for_timezone(reminder_at, battle_row.timezone)}")
            for row in visible_rows:
                status = "enabled" if row.enabled else "disabled"
                reminder_at = reminder_time_for_event(row.event_name, row.next_occurrence_utc, DEFAULT_REMINDER_LEAD_MINUTES)
                event_label = _event_display_name(row.event_name, row.instance)
                lines.append(f"{event_label}: {status}, start {_format_datetime_for_timezone(row.next_occurrence_utc, row.timezone)}, reminder {_format_datetime_for_timezone(reminder_at, row.timezone)}")
            await interaction.response.send_message("\n".join(lines[:25]), ephemeral=True)

        @events_group.command(name="test", description="Preview a dummy reminder privately")
        @app_commands.choices(event=EVENT_TEST_CHOICES)
        async def test_event_cmd(interaction: discord.Interaction, event: app_commands.Choice[str], instance: str | None = None) -> None:
            if not await self._require_manage(interaction):
                return
            if interaction.guild_id is None:
                await interaction.response.send_message("Test reminders can only be previewed inside a server.", ephemeral=True)
                return
            try:
                event_name = TEST_ALL_EVENTS_VALUE if event.value == TEST_ALL_EVENTS_VALUE else find_event_name(event.value)
                if event_name == TEST_ALL_EVENTS_VALUE and instance:
                    raise ValueError("The all-events test does not accept an instance.")
                rows = self._dummy_test_rows(interaction.guild_id, event_name, instance)
                reminder_cases = self._dummy_test_reminder_cases(rows)
            except Exception as exc:
                await interaction.response.send_message(str(exc), ephemeral=True)
                return
            await interaction.response.defer(ephemeral=True, thinking=True)
            settings = await self.get_settings_cached(interaction.guild_id)
            sent_count = 0
            for row, reminder_phase in reminder_cases:
                await self._send_event_notification_ephemeral_test(interaction, row, settings, reminder_phase)
                sent_count += 1
            if event_name == TEST_ALL_EVENTS_VALUE:
                test_label = "all supported events"
            elif len(rows) > 1:
                test_label = event_name
            else:
                test_label = _event_display_name(event_name, rows[0].instance)
            await interaction.followup.send(f"Sent {sent_count} private dummy test preview(s) for {test_label}. Mentions were suppressed.", ephemeral=True)

        self.tree.add_command(settings_group)
        self.tree.add_command(events_group)


def main() -> None:
    if not DISCORD_TOKEN:
        raise RuntimeError("DISCORD_TOKEN is required in environment")
    if not BOT_OWNER_USER_ID:
        raise RuntimeError("BOT_OWNER_USER_ID is required in environment")
    bot = KingshotEventBot()
    bot.run(DISCORD_TOKEN)


if __name__ == "__main__":
    main()
