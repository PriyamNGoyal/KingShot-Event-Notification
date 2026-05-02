from dataclasses import dataclass
from datetime import datetime

import aiosqlite
import pytz

from database.db import connect_db


@dataclass(slots=True)
class EventConfigRow:
    id: int
    guild_id: int
    event_name: str
    instance: str
    enabled: bool
    event_time: str
    event_date: str | None
    timezone: str
    next_occurrence_utc: datetime
    mention_mode: str
    delete_enabled: bool | None
    delete_delay_minutes: int | None
    last_notification_message_id: int | None
    last_notification_channel_id: int | None


def utc_to_db(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = pytz.UTC.localize(dt)
    return dt.astimezone(pytz.UTC).isoformat()


def db_to_utc(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(pytz.UTC)


def _row_to_event(row: tuple) -> EventConfigRow:
    return EventConfigRow(
        id=int(row[0]),
        guild_id=int(row[1]),
        event_name=str(row[2]),
        instance=str(row[3]),
        enabled=bool(row[4]),
        event_time=str(row[5]),
        event_date=str(row[6]) if row[6] else None,
        timezone=str(row[7]),
        next_occurrence_utc=db_to_utc(str(row[8])),
        mention_mode=str(row[9]),
        delete_enabled=None if row[10] is None else bool(row[10]),
        delete_delay_minutes=None if row[11] is None else int(row[11]),
        last_notification_message_id=None if row[12] is None else int(row[12]),
        last_notification_channel_id=None if row[13] is None else int(row[13]),
    )


async def upsert_event_config(guild_id: int, event_name: str, instance: str, event_time: str, event_date: str | None, timezone: str, next_occurrence_utc: datetime, mention_mode: str) -> None:
    async with connect_db() as db:
        await db.execute(
            """
            INSERT INTO event_configs (guild_id, event_name, instance, enabled, event_time, event_date, timezone, next_occurrence_utc, mention_mode, updated_at)
            VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(guild_id, event_name, instance) DO UPDATE SET
                enabled = 1,
                event_time = excluded.event_time,
                event_date = excluded.event_date,
                timezone = excluded.timezone,
                next_occurrence_utc = excluded.next_occurrence_utc,
                mention_mode = excluded.mention_mode,
                updated_at = CURRENT_TIMESTAMP
            """,
            (guild_id, event_name, instance, event_time, event_date, timezone, utc_to_db(next_occurrence_utc), mention_mode),
        )
        await db.commit()


async def disable_event_config(guild_id: int, event_name: str, instance: str) -> bool:
    async with connect_db() as db:
        cur = await db.execute(
            "UPDATE event_configs SET enabled = 0, updated_at = CURRENT_TIMESTAMP WHERE guild_id = ? AND event_name = ? AND instance = ?",
            (guild_id, event_name, instance),
        )
        await db.commit()
        return cur.rowcount > 0


async def list_event_configs(guild_id: int) -> list[EventConfigRow]:
    async with connect_db() as db:
        async with db.execute(
            """
            SELECT id, guild_id, event_name, instance, enabled, event_time, event_date, timezone, next_occurrence_utc,
                   mention_mode, delete_enabled, delete_delay_minutes, last_notification_message_id, last_notification_channel_id
            FROM event_configs
            WHERE guild_id = ?
            ORDER BY event_name, instance
            """,
            (guild_id,),
        ) as cur:
            return [_row_to_event(row) for row in await cur.fetchall()]


async def list_due_events(remind_before_utc: datetime) -> list[EventConfigRow]:
    async with connect_db() as db:
        async with db.execute(
            """
            SELECT id, guild_id, event_name, instance, enabled, event_time, event_date, timezone, next_occurrence_utc,
                   mention_mode, delete_enabled, delete_delay_minutes, last_notification_message_id, last_notification_channel_id
            FROM event_configs
            WHERE enabled = 1 AND next_occurrence_utc <= ?
            ORDER BY next_occurrence_utc, guild_id, event_name, instance
            """,
            (utc_to_db(remind_before_utc),),
        ) as cur:
            return [_row_to_event(row) for row in await cur.fetchall()]


async def list_due_one_day_events(remind_before_utc: datetime, event_names: list[str]) -> list[EventConfigRow]:
    if not event_names:
        return []
    placeholders = ", ".join("?" for _ in event_names)
    async with connect_db() as db:
        async with db.execute(
            f"""
            SELECT id, guild_id, event_name, instance, enabled, event_time, event_date, timezone, next_occurrence_utc,
                   mention_mode, delete_enabled, delete_delay_minutes, last_notification_message_id, last_notification_channel_id
            FROM event_configs
            WHERE enabled = 1 AND event_name IN ({placeholders}) AND next_occurrence_utc <= ?
            ORDER BY next_occurrence_utc, guild_id, event_name, instance
            """,
            (*event_names, utc_to_db(remind_before_utc)),
        ) as cur:
            return [_row_to_event(row) for row in await cur.fetchall()]


async def list_due_named_events(remind_before_utc: datetime, event_names: list[str]) -> list[EventConfigRow]:
    if not event_names:
        return []
    placeholders = ", ".join("?" for _ in event_names)
    async with connect_db() as db:
        async with db.execute(
            f"""
            SELECT id, guild_id, event_name, instance, enabled, event_time, event_date, timezone, next_occurrence_utc,
                   mention_mode, delete_enabled, delete_delay_minutes, last_notification_message_id, last_notification_channel_id
            FROM event_configs
            WHERE enabled = 1 AND event_name IN ({placeholders}) AND next_occurrence_utc <= ?
            ORDER BY next_occurrence_utc
            """,
            (*event_names, utc_to_db(remind_before_utc)),
        ) as cur:
            return [_row_to_event(row) for row in await cur.fetchall()]


async def claim_event_reminder(event_id: int, occurrence_utc: datetime, reminder_phase: str) -> bool:
    async with connect_db() as db:
        cur = await db.execute(
            """
            INSERT OR IGNORE INTO event_reminder_state (event_config_id, occurrence_utc, reminder_phase)
            VALUES (?, ?, ?)
            """,
            (event_id, utc_to_db(occurrence_utc), reminder_phase),
        )
        await db.commit()
        return cur.rowcount > 0


async def update_next_occurrence(event_id: int, next_occurrence_utc: datetime) -> None:
    async with connect_db() as db:
        await db.execute(
            "UPDATE event_configs SET next_occurrence_utc = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (utc_to_db(next_occurrence_utc), event_id),
        )
        await db.commit()


async def set_event_enabled(event_id: int, enabled: bool) -> None:
    async with connect_db() as db:
        await db.execute(
            "UPDATE event_configs SET enabled = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (1 if enabled else 0, event_id),
        )
        await db.commit()


async def update_last_notification(event_id: int, channel_id: int, message_id: int) -> None:
    async with connect_db() as db:
        await db.execute(
            """
            UPDATE event_configs
            SET last_notification_channel_id = ?, last_notification_message_id = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (channel_id, message_id, event_id),
        )
        await db.commit()
