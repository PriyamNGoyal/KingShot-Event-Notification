import os
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

import aiosqlite

from config import DB_PATH, DEFAULT_DELETE_DELAY_MINUTES, DEFAULT_DELETE_ENABLED, DEFAULT_TIMEZONE


_INITIALIZED = False


def _db_path() -> str:
    return DB_PATH or "kingshot_events.sqlite3"


def ensure_db_directory() -> None:
    os.makedirs(os.path.dirname(_db_path()) or ".", exist_ok=True)


async def _configure_connection(db: aiosqlite.Connection) -> None:
    await db.execute("PRAGMA foreign_keys = ON")
    await db.execute("PRAGMA journal_mode = WAL")
    await db.execute("PRAGMA busy_timeout = 30000")


async def _table_columns(db: aiosqlite.Connection, table_name: str) -> set[str]:
    async with db.execute(f"PRAGMA table_info({table_name})") as cur:
        rows = await cur.fetchall()
    return {str(row[1]) for row in rows}


async def _add_missing_columns(db: aiosqlite.Connection, table_name: str, columns: dict[str, str]) -> None:
    existing_columns = await _table_columns(db, table_name)
    for column_name, column_definition in columns.items():
        if column_name not in existing_columns:
            await db.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_definition}")


async def init_db() -> None:
    global _INITIALIZED

    ensure_db_directory()
    async with aiosqlite.connect(_db_path()) as db:
        await _configure_connection(db)
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS guild_settings (
                guild_id INTEGER PRIMARY KEY,
                role_channel_id INTEGER,
                announcement_channel_id INTEGER,
                timezone TEXT NOT NULL DEFAULT 'UTC',
                delete_enabled INTEGER NOT NULL DEFAULT 1,
                delete_delay_minutes INTEGER NOT NULL DEFAULT 60,
                bear_1_role_id INTEGER,
                bear_2_role_id INTEGER,
                bear_panel_message_id INTEGER,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS guild_management_roles (
                guild_id INTEGER NOT NULL,
                role_id INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (guild_id, role_id)
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS event_configs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                event_name TEXT NOT NULL,
                instance TEXT NOT NULL DEFAULT 'default',
                enabled INTEGER NOT NULL DEFAULT 1,
                event_time TEXT NOT NULL,
                event_date TEXT,
                timezone TEXT NOT NULL DEFAULT 'UTC',
                next_occurrence_utc TEXT NOT NULL,
                mention_mode TEXT NOT NULL DEFAULT 'everyone',
                delete_enabled INTEGER,
                delete_delay_minutes INTEGER,
                last_notification_message_id INTEGER,
                last_notification_channel_id INTEGER,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (guild_id, event_name, instance)
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS notification_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                event_name TEXT NOT NULL,
                instance TEXT NOT NULL DEFAULT 'default',
                channel_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                scheduled_delete_at_utc TEXT,
                deleted_at_utc TEXT,
                created_at_utc TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS event_reminder_state (
                event_config_id INTEGER NOT NULL,
                occurrence_utc TEXT NOT NULL,
                reminder_phase TEXT NOT NULL,
                sent_at_utc TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (event_config_id, occurrence_utc, reminder_phase),
                FOREIGN KEY (event_config_id) REFERENCES event_configs(id) ON DELETE CASCADE
            )
            """
        )

        await _add_missing_columns(
            db,
            "guild_settings",
            {
                "role_channel_id": "INTEGER",
                "announcement_channel_id": "INTEGER",
                "timezone": "TEXT NOT NULL DEFAULT 'UTC'",
                "delete_enabled": "INTEGER NOT NULL DEFAULT 1",
                "delete_delay_minutes": "INTEGER NOT NULL DEFAULT 60",
                "bear_1_role_id": "INTEGER",
                "bear_2_role_id": "INTEGER",
                "bear_panel_message_id": "INTEGER",
                "updated_at": "TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP",
            },
        )
        await _add_missing_columns(
            db,
            "guild_management_roles",
            {
                "created_at": "TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP",
            },
        )
        await _add_missing_columns(
            db,
            "event_configs",
            {
                "instance": "TEXT NOT NULL DEFAULT 'default'",
                "enabled": "INTEGER NOT NULL DEFAULT 1",
                "event_date": "TEXT",
                "timezone": "TEXT NOT NULL DEFAULT 'UTC'",
                "mention_mode": "TEXT NOT NULL DEFAULT 'everyone'",
                "delete_enabled": "INTEGER",
                "delete_delay_minutes": "INTEGER",
                "last_notification_message_id": "INTEGER",
                "last_notification_channel_id": "INTEGER",
                "updated_at": "TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP",
            },
        )
        await _add_missing_columns(
            db,
            "notification_history",
            {
                "instance": "TEXT NOT NULL DEFAULT 'default'",
                "scheduled_delete_at_utc": "TEXT",
                "deleted_at_utc": "TEXT",
                "created_at_utc": "TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP",
            },
        )

        await db.execute(
            """
            UPDATE guild_settings
            SET timezone = COALESCE(timezone, ?),
                delete_enabled = COALESCE(delete_enabled, ?),
                delete_delay_minutes = COALESCE(delete_delay_minutes, ?)
            """,
            (DEFAULT_TIMEZONE, 1 if DEFAULT_DELETE_ENABLED else 0, DEFAULT_DELETE_DELAY_MINUTES),
        )
        await db.execute("UPDATE event_configs SET instance = COALESCE(instance, 'default')")
        await db.execute("UPDATE event_configs SET enabled = COALESCE(enabled, 1)")
        await db.execute("UPDATE event_configs SET timezone = COALESCE(timezone, ?)", (DEFAULT_TIMEZONE,))
        await db.execute("UPDATE event_configs SET mention_mode = COALESCE(mention_mode, 'everyone')")
        await db.execute("UPDATE notification_history SET instance = COALESCE(instance, 'default')")

        await db.execute("CREATE INDEX IF NOT EXISTS idx_guild_settings_bear_panel ON guild_settings(bear_panel_message_id)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_management_roles_guild ON guild_management_roles(guild_id)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_event_configs_guild ON event_configs(guild_id)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_event_configs_due ON event_configs(enabled, next_occurrence_utc)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_event_configs_due_named ON event_configs(enabled, event_name, next_occurrence_utc)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_notification_history_due_delete ON notification_history(deleted_at_utc, scheduled_delete_at_utc)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_notification_history_guild ON notification_history(guild_id)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_reminder_state_event ON event_reminder_state(event_config_id)")

        await db.commit()
    _INITIALIZED = True


async def ensure_initialized() -> None:
    if not _INITIALIZED:
        await init_db()


@asynccontextmanager
async def connect_db() -> AsyncIterator[aiosqlite.Connection]:
    await ensure_initialized()
    async with aiosqlite.connect(_db_path()) as db:
        await _configure_connection(db)
        yield db
