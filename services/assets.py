import logging
import re
from pathlib import Path

from services.events import get_event_config


logger = logging.getLogger("kingshot_event_notification.assets")

ASSET_DIR = Path("data") / "assets"


def _safe_asset_stem(event_name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", event_name.lower()).strip("_")


def thumbnail_filename(event_name: str) -> str | None:
    event_meta = get_event_config(event_name) or {}
    if not event_meta.get("thumbnail_url"):
        return None
    return f"{_safe_asset_stem(event_name)}_thumbnail.png"


def shipped_thumbnail_path(event_name: str) -> Path | None:
    filename = thumbnail_filename(event_name)
    if not filename:
        return None
    path = ASSET_DIR / filename
    if path.is_file():
        return path
    logger.warning("Local thumbnail asset is missing for event=%s; caller may use remote metadata fallback", event_name)
    return None
