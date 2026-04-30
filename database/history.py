from datetime import datetime

import aiosqlite
import pytz

from database.db import connect_db
from database.events import db_to_utc, utc_to_db


async def add_notification_history(guild_id: int, event_name: str, instance: str, channel_id: int, message_id: int, scheduled_delete_at_utc: datetime | None) -> None:
    async with connect_db() as db:
        await db.execute(
            """
            INSERT INTO notification_history (guild_id, event_name, instance, channel_id, message_id, scheduled_delete_at_utc)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (guild_id, event_name, instance, channel_id, message_id, utc_to_db(scheduled_delete_at_utc) if scheduled_delete_at_utc else None),
        )
        await db.commit()


async def list_due_deletions(now_utc: datetime) -> list[tuple[int, int, int]]:
    async with connect_db() as db:
        async with db.execute(
            """
            SELECT id, channel_id, message_id
            FROM notification_history
            WHERE deleted_at_utc IS NULL AND scheduled_delete_at_utc IS NOT NULL AND scheduled_delete_at_utc <= ?
            ORDER BY scheduled_delete_at_utc
            """,
            (utc_to_db(now_utc),),
        ) as cur:
            rows = await cur.fetchall()
            return [(int(row[0]), int(row[1]), int(row[2])) for row in rows]


async def mark_deleted(history_id: int) -> None:
    async with connect_db() as db:
        await db.execute(
            "UPDATE notification_history SET deleted_at_utc = ? WHERE id = ?",
            (utc_to_db(datetime.now(pytz.UTC)), history_id),
        )
        await db.commit()
