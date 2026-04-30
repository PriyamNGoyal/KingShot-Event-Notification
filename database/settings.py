from dataclasses import dataclass

import aiosqlite

from config import DEFAULT_DELETE_DELAY_MINUTES, DEFAULT_DELETE_ENABLED, DEFAULT_TIMEZONE
from database.db import connect_db


@dataclass(slots=True)
class GuildSettings:
    guild_id: int
    role_channel_id: int | None
    announcement_channel_id: int | None
    timezone: str
    delete_enabled: bool
    delete_delay_minutes: int
    bear_1_role_id: int | None
    bear_2_role_id: int | None
    bear_panel_message_id: int | None


async def ensure_guild_settings_row(db: aiosqlite.Connection, guild_id: int) -> None:
    await db.execute(
        """
        INSERT INTO guild_settings (guild_id, timezone, delete_enabled, delete_delay_minutes, updated_at)
        VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(guild_id) DO NOTHING
        """,
        (guild_id, DEFAULT_TIMEZONE, 1 if DEFAULT_DELETE_ENABLED else 0, DEFAULT_DELETE_DELAY_MINUTES),
    )


def _settings_from_row(row: tuple) -> GuildSettings:
    return GuildSettings(
        guild_id=int(row[0]),
        role_channel_id=int(row[1]) if row[1] else None,
        announcement_channel_id=int(row[2]) if row[2] else None,
        timezone=str(row[3] or DEFAULT_TIMEZONE),
        delete_enabled=bool(row[4]),
        delete_delay_minutes=int(row[5] or DEFAULT_DELETE_DELAY_MINUTES),
        bear_1_role_id=int(row[6]) if row[6] else None,
        bear_2_role_id=int(row[7]) if row[7] else None,
        bear_panel_message_id=int(row[8]) if row[8] else None,
    )


async def get_guild_settings(guild_id: int) -> GuildSettings:
    async with connect_db() as db:
        await ensure_guild_settings_row(db, guild_id)
        await db.commit()
        async with db.execute(
            """
            SELECT guild_id, role_channel_id, announcement_channel_id, timezone, delete_enabled,
                   delete_delay_minutes, bear_1_role_id, bear_2_role_id, bear_panel_message_id
            FROM guild_settings
            WHERE guild_id = ?
            """,
            (guild_id,),
        ) as cur:
            row = await cur.fetchone()
            if row is None:
                raise RuntimeError(f"guild_settings row missing for guild {guild_id}")
            return _settings_from_row(row)


async def set_role_channel(guild_id: int, channel_id: int) -> None:
    async with connect_db() as db:
        await ensure_guild_settings_row(db, guild_id)
        await db.execute(
            "UPDATE guild_settings SET role_channel_id = ?, updated_at = CURRENT_TIMESTAMP WHERE guild_id = ?",
            (channel_id, guild_id),
        )
        await db.commit()


async def set_announcement_channel(guild_id: int, channel_id: int) -> None:
    async with connect_db() as db:
        await ensure_guild_settings_row(db, guild_id)
        await db.execute(
            "UPDATE guild_settings SET announcement_channel_id = ?, updated_at = CURRENT_TIMESTAMP WHERE guild_id = ?",
            (channel_id, guild_id),
        )
        await db.commit()


async def set_timezone(guild_id: int, timezone_name: str) -> None:
    async with connect_db() as db:
        await ensure_guild_settings_row(db, guild_id)
        await db.execute(
            "UPDATE guild_settings SET timezone = ?, updated_at = CURRENT_TIMESTAMP WHERE guild_id = ?",
            (timezone_name, guild_id),
        )
        await db.commit()


async def set_delete_policy(guild_id: int, enabled: bool, delay_minutes: int) -> None:
    async with connect_db() as db:
        await ensure_guild_settings_row(db, guild_id)
        await db.execute(
            """
            UPDATE guild_settings
            SET delete_enabled = ?, delete_delay_minutes = ?, updated_at = CURRENT_TIMESTAMP
            WHERE guild_id = ?
            """,
            (1 if enabled else 0, delay_minutes, guild_id),
        )
        await db.commit()


async def set_bear_roles_and_panel(guild_id: int, bear_1_role_id: int, bear_2_role_id: int, panel_message_id: int) -> None:
    async with connect_db() as db:
        await ensure_guild_settings_row(db, guild_id)
        await db.execute(
            """
            UPDATE guild_settings
            SET bear_1_role_id = ?, bear_2_role_id = ?, bear_panel_message_id = ?, updated_at = CURRENT_TIMESTAMP
            WHERE guild_id = ?
            """,
            (bear_1_role_id, bear_2_role_id, panel_message_id, guild_id),
        )
        await db.commit()


async def add_management_role(guild_id: int, role_id: int) -> bool:
    async with connect_db() as db:
        cur = await db.execute(
            "INSERT OR IGNORE INTO guild_management_roles (guild_id, role_id) VALUES (?, ?)",
            (guild_id, role_id),
        )
        await db.commit()
        return cur.rowcount > 0


async def remove_management_role(guild_id: int, role_id: int) -> bool:
    async with connect_db() as db:
        cur = await db.execute(
            "DELETE FROM guild_management_roles WHERE guild_id = ? AND role_id = ?",
            (guild_id, role_id),
        )
        await db.commit()
        return cur.rowcount > 0


async def list_management_roles(guild_id: int) -> list[int]:
    async with connect_db() as db:
        async with db.execute(
            "SELECT role_id FROM guild_management_roles WHERE guild_id = ? ORDER BY role_id",
            (guild_id,),
        ) as cur:
            rows = await cur.fetchall()
            return [int(row[0]) for row in rows]


async def list_bear_panel_guild_ids() -> list[int]:
    async with connect_db() as db:
        async with db.execute(
            """
            SELECT guild_id
            FROM guild_settings
            WHERE bear_panel_message_id IS NOT NULL
            """
        ) as cur:
            rows = await cur.fetchall()
            return [int(row[0]) for row in rows]
