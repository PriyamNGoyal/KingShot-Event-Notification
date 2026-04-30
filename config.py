import os
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
BOT_OWNER_USER_ID = int(os.getenv("BOT_OWNER_USER_ID", "0") or "0")
DB_PATH = os.getenv("DB_PATH", str(Path("kingshot_events.sqlite3"))).strip()

DEFAULT_TIMEZONE = os.getenv("DEFAULT_TIMEZONE", "UTC").strip() or "UTC"
DEFAULT_DELETE_ENABLED = os.getenv("DEFAULT_DELETE_ENABLED", "true").strip().lower() not in {"0", "false", "no"}
DEFAULT_DELETE_DELAY_MINUTES = int(os.getenv("DEFAULT_DELETE_DELAY_MINUTES", "60") or "60")
DEFAULT_REMINDER_LEAD_MINUTES = int(os.getenv("DEFAULT_REMINDER_LEAD_MINUTES", "15") or "15")
SCHEDULER_POLL_SECONDS = int(os.getenv("SCHEDULER_POLL_SECONDS", "15") or "15")
DELETION_POLL_SECONDS = int(os.getenv("DELETION_POLL_SECONDS", "10") or "10")
