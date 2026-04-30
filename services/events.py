import re
from datetime import datetime, time, timedelta
from typing import Any

import pytz


APPROVED_EVENT_NAMES = [
    "Bear Trap",
    "Viking Vengeance",
    "Swordland Showdown",
    "Eternity's Reach",
    "Castle Battle",
    "KvK",
]

ONE_DAY_REMINDER_EVENT_NAMES = {"Castle Battle", "KvK"}
OPEN_RESET_REMINDER_EVENT_NAMES = {"Swordland Showdown", "Eternity's Reach"}
GROUPED_EVENT_PHASES: dict[str, tuple[str, ...]] = {
    "Castle Battle": ("teleport_window", "battle_start"),
    "KvK": ("teleport_window", "battle_start"),
}
ONE_DAY_REMINDER_INSTANCES: dict[str, set[str]] = {
    "Castle Battle": {"battle_start"},
    "KvK": {"battle_start"},
}

EVENT_CONFIG: dict[str, dict[str, Any]] = {
    "Bear Trap": {
        "emoji": "🐻",
        "duration_minutes": 30,
        "schedule_type": "custom",
        "description": "The %e %n opens in %t. Get your buffs on and prepare your marches for the hunt!",
        "time_slots": "5min",
        "instances": ["bear_1", "bear_2"],
        "thumbnail_url": "https://i.imgur.com/2s9QX4T.png",
    },
    "Viking Vengeance": {
        "emoji": "🔥",
        "duration_minutes": 30,
        "schedule_type": "global_biweekly",
        "fixed_days": "Tuesday and Thursday every 4 weeks",
        "reference_date": "2025-11-18",
        "cycle_weeks": 4,
        "description": "%n is coming to town at %e. Come online in %t and join the defense!",
        "time_slots": "5min",
        "instances": ["tuesday", "thursday"],
        "thumbnail_url": "https://i.imgur.com/cGrsmqk.png",
    },
    "Swordland Showdown": {
        "emoji": "⚔️",
        "duration_minutes": 60,
        "schedule_type": "global_biweekly",
        "fixed_days": "Every 2 weeks on Sunday",
        "reference_date": "2025-11-16",
        "cycle_weeks": 2,
        "available_times": ["02:00", "12:00", "14:00", "19:00"],
        "description": "%n opens today at reset. Your configured battle time is %e; buff up, heal up, recall your marches and get ready to fight!",
        "descriptions": {
            "legion1": "%n Legion 1 opens today at reset. Your configured battle time is %e; buff up, heal up, recall your marches and get ready to fight!",
            "legion2": "%n Legion 2 opens today at reset. Your configured battle time is %e; buff up, heal up, recall your marches and get ready to fight!",
        },
        "instances": ["legion1", "legion2"],
        "thumbnail_url": "https://i.imgur.com/QBALQsN.png",
    },
    "Eternity's Reach": {
        "emoji": "♾️",
        "duration_minutes": 30,
        "schedule_type": "global_monthly",
        "fixed_days": "Monthly on Tuesday",
        "reference_date": "2025-11-18",
        "cycle_weeks": 4,
        "description": "%n opens tomorrow at reset. Recall troops and prepare if you are joining.",
        "show_scheduled_time": False,
        "thumbnail_url": "https://i.imgur.com/G12FyL1.png",
    },
    "Castle Battle": {
        "emoji": "🏰",
        "duration_minutes": 360,
        "schedule_type": "global_4weekly",
        "fixed_days": "Every 4 weeks on Saturday",
        "reference_date": "2025-11-22",
        "cycle_weeks": 4,
        "fixed_time": "12:00",
        "description": "%n starts in %t, get ready!",
        "descriptions": {
            "teleport_window": "%n teleport window opens in %t! Get ready to take your places.",
            "battle_start": "%n starts in %t. Get ready to fight!",
        },
        "instances": ["teleport_window", "battle_start"],
        "thumbnail_url": "https://i.imgur.com/i3RwgWT.png",
    },
    "KvK": {
        "emoji": "👑",
        "duration_minutes": 360,
        "schedule_type": "global_4weekly_alt",
        "fixed_days": "Every 4 weeks on Saturday (alternating with Castle Battle)",
        "reference_date": "2025-12-06",
        "cycle_weeks": 4,
        "fixed_time": "12:00",
        "description": "%n starts in %t, get ready!",
        "descriptions": {
            "borders_open": "%n Borders & Teleport Open phase starts in %t! Shield up, get ready to take your places, and prepare for battle.",
            "teleport_window": "%n Borders & Teleport Open phase starts in %t! Shield up, get ready to take your places, and prepare for battle.",
            "battle_start": "%n battle starts in %t. Get ready to battle and win this for the glory of our kingdom!",
        },
        "instances": ["teleport_window", "battle_start"],
        "thumbnail_url": "https://i.imgur.com/P4MLrJF.png",
    },
}


def get_event_config(event_name: str) -> dict[str, Any] | None:
    return EVENT_CONFIG.get(event_name)


def get_event_choices() -> list[str]:
    return APPROVED_EVENT_NAMES.copy()


def find_event_name(value: str) -> str:
    normalized = value.strip().lower()
    for event_name in APPROVED_EVENT_NAMES:
        if event_name.lower() == normalized:
            return event_name
    raise ValueError(f"Unsupported event: {value}")


def validate_time_slot(time_str: str, slot_type: str = "5min") -> bool:
    try:
        hours, minutes = map(int, time_str.split(":"))
    except ValueError:
        return False
    if not (0 <= hours <= 23 and 0 <= minutes <= 59):
        return False
    if slot_type == "5min":
        return minutes % 5 == 0
    return True


def validate_configurable_time(event_name: str, event_time: str) -> None:
    config = EVENT_CONFIG[event_name]
    available_times = config.get("available_times")
    if available_times and event_time not in available_times:
        raise ValueError(f"{event_name} time must be one of: {', '.join(available_times)}")
    fixed_time = config.get("fixed_time")
    if fixed_time and event_time != fixed_time:
        raise ValueError(f"{event_name} time must be {fixed_time}")
    if not validate_time_slot(event_time, config.get("time_slots", "any")):
        raise ValueError("Time must use HH:MM format and match the event time slot rules")


def validate_instance(event_name: str, instance: str | None) -> str:
    config = EVENT_CONFIG[event_name]
    instances = config.get("instances")
    if event_name in GROUPED_EVENT_PHASES and not instance:
        return "default"
    normalized = (instance or "default").strip().lower()
    if not instances:
        return "default"
    if normalized in instances:
        return normalized
    allowed = ", ".join(instances)
    raise ValueError(f"{event_name} requires one of these instances: {allowed}")


def format_instance_label(event_name: str, instance: str | None) -> str | None:
    """Return a user-facing instance label, or None when the instance is optional/default."""
    normalized = (instance or "").strip()
    if not normalized or normalized.lower() == "default":
        return None
    if event_name == "KvK" and normalized.lower() in {"borders_open", "teleport_window"}:
        return "Borders & Teleport Open"
    config = EVENT_CONFIG.get(event_name, {})
    if not config.get("instances"):
        return None
    words = re.sub(r"(?<=[A-Za-z])(?=\d)", " ", normalized.replace("_", " "))
    return " ".join(part.capitalize() for part in words.split())


def is_grouped_event(event_name: str) -> bool:
    return event_name in GROUPED_EVENT_PHASES


def grouped_event_phases(event_name: str) -> tuple[str, ...]:
    return GROUPED_EVENT_PHASES.get(event_name, ())


def should_send_one_day_reminder(event_name: str, instance: str | None) -> bool:
    allowed_instances = ONE_DAY_REMINDER_INSTANCES.get(event_name)
    if not allowed_instances:
        return event_name in ONE_DAY_REMINDER_EVENT_NAMES
    return (instance or "default") in allowed_instances


def parse_utc_start(event_date: str, event_time: str) -> datetime:
    if not validate_time_slot(event_time, "any"):
        raise ValueError("Time must use HH:MM format")
    date_value = datetime.strptime(event_date, "%Y-%m-%d").date()
    hour, minute = map(int, event_time.split(":"))
    return pytz.UTC.localize(datetime.combine(date_value, time(hour=hour, minute=minute)))


def grouped_event_schedule(event_name: str, event_date: str, battle_time: str | None = None, now_utc: datetime | None = None) -> dict[str, datetime]:
    now = now_utc or datetime.now(pytz.UTC)
    if now.tzinfo is None:
        now = pytz.UTC.localize(now)
    if event_name == "Castle Battle":
        if not battle_time:
            raise ValueError("Castle Battle requires date and battle time. Teleport Window is calculated automatically as 1 hour before battle time.")
        battle_start = parse_utc_start(event_date, battle_time)
        schedule = {
            "teleport_window": battle_start - timedelta(hours=1),
            "battle_start": battle_start,
        }
    elif event_name == "KvK":
        schedule = {
            "teleport_window": parse_utc_start(event_date, "10:00"),
            "battle_start": parse_utc_start(event_date, "12:00"),
        }
    else:
        raise ValueError(f"{event_name} is not a grouped event")
    if all(start <= now for start in schedule.values()):
        raise ValueError("Configured event date/time is in the past")
    return schedule


def _reference_date(config: dict[str, Any]) -> datetime:
    reference = datetime.strptime(config["reference_date"], "%Y-%m-%d")
    return pytz.UTC.localize(reference)


def calculate_next_base_date(event_name: str, from_date: datetime | None = None) -> datetime | None:
    config = EVENT_CONFIG[event_name]
    if from_date is None:
        from_date = datetime.now(pytz.UTC)
    if from_date.tzinfo is None:
        from_date = pytz.UTC.localize(from_date)
    schedule_type = config["schedule_type"]
    if schedule_type == "custom":
        return None
    reference = _reference_date(config)
    cycle_weeks = int(config.get("cycle_weeks", 4))
    weeks_diff = (from_date - reference).days // 7
    if weeks_diff < 0:
        return reference
    cycles_passed = weeks_diff // cycle_weeks
    next_occurrence = reference + timedelta(weeks=cycles_passed * cycle_weeks)
    if next_occurrence <= from_date:
        next_occurrence += timedelta(weeks=cycle_weeks)
    return next_occurrence


def calculate_next_start(event_name: str, event_time: str, timezone_name: str, event_date: str | None = None, from_date: datetime | None = None, instance: str = "default") -> datetime:
    if event_name not in EVENT_CONFIG:
        raise ValueError(f"Unsupported event: {event_name}")
    if not validate_time_slot(event_time, EVENT_CONFIG[event_name].get("time_slots", "any")):
        raise ValueError("Time must use HH:MM format and match the event time slot rules")
    tz = pytz.timezone(timezone_name)
    now_utc = from_date or datetime.now(pytz.UTC)
    if now_utc.tzinfo is None:
        now_utc = pytz.UTC.localize(now_utc)
    hour, minute = map(int, event_time.split(":"))
    config = EVENT_CONFIG[event_name]
    if event_date:
        date_value = datetime.strptime(event_date, "%Y-%m-%d").date()
        local_start = tz.localize(datetime.combine(date_value, time(hour=hour, minute=minute)))
        if local_start.astimezone(pytz.UTC) <= now_utc:
            raise ValueError("Configured date/time is in the past")
        return local_start.astimezone(pytz.UTC)
    if config["schedule_type"] == "custom":
        today_local = now_utc.astimezone(tz).date()
        local_start = tz.localize(datetime.combine(today_local, time(hour=hour, minute=minute)))
        if local_start.astimezone(pytz.UTC) <= now_utc:
            local_start += timedelta(days=1)
        return local_start.astimezone(pytz.UTC)
    base_date_from = now_utc
    if event_name == "Viking Vengeance" and instance == "thursday":
        base_date_from = now_utc - timedelta(days=2)
    base_date = calculate_next_base_date(event_name, base_date_from)
    if base_date is None:
        raise ValueError("Could not calculate event occurrence")
    if event_name == "Viking Vengeance" and instance == "thursday":
        base_date += timedelta(days=2)
    local_base_date = base_date.astimezone(tz).date()
    local_start = tz.localize(datetime.combine(local_base_date, time(hour=hour, minute=minute)))
    if local_start.astimezone(pytz.UTC) <= now_utc:
        next_base_from = now_utc + timedelta(days=1)
        if event_name == "Viking Vengeance" and instance == "thursday":
            next_base_from = next_base_from - timedelta(days=2)
        next_base = calculate_next_base_date(event_name, next_base_from)
        if next_base is None:
            raise ValueError("Could not calculate next event occurrence")
        if event_name == "Viking Vengeance" and instance == "thursday":
            next_base += timedelta(days=2)
        local_start = tz.localize(datetime.combine(next_base.astimezone(tz).date(), time(hour=hour, minute=minute)))
    return local_start.astimezone(pytz.UTC)


def reminder_time(start_utc: datetime, lead_minutes: int = 15) -> datetime:
    return start_utc - timedelta(minutes=lead_minutes)


def event_open_reminder_time(start_utc: datetime, lead_minutes: int = 15) -> datetime:
    event_date_utc = start_utc.astimezone(pytz.UTC).date()
    reset_utc = pytz.UTC.localize(datetime.combine(event_date_utc, time(hour=0, minute=0)))
    return reset_utc - timedelta(minutes=lead_minutes)


def reminder_time_for_event(event_name: str, start_utc: datetime, lead_minutes: int = 15) -> datetime:
    if event_name in OPEN_RESET_REMINDER_EVENT_NAMES:
        return event_open_reminder_time(start_utc, lead_minutes)
    return reminder_time(start_utc, lead_minutes)


def one_day_reminder_time(start_utc: datetime) -> datetime:
    return start_utc - timedelta(days=1)


def format_message(event_name: str, instance: str, start_utc: datetime, lead_minutes: int) -> tuple[str, str]:
    config = EVENT_CONFIG[event_name]
    emoji = config.get("emoji", "📅")
    description = config.get("descriptions", {}).get(instance, config["description"])
    event_time = start_utc.astimezone(pytz.UTC).strftime("%Y-%m-%d %H:%M UTC")
    lead_text = f"{lead_minutes} minutes"
    body = description.replace("%n", event_name).replace("%e", event_time).replace("%t", lead_text)
    if config.get("show_scheduled_time", True) and event_time not in body:
        body = f"{body} Scheduled for {event_time}."
    return f"{emoji} {event_name}", body


def format_one_day_message(event_name: str, instance: str, start_utc: datetime) -> tuple[str, str]:
    config = EVENT_CONFIG[event_name]
    emoji = config.get("emoji", "📅")
    event_time = start_utc.astimezone(pytz.UTC).strftime("%Y-%m-%d %H:%M UTC")
    instance_label = format_instance_label(event_name, instance)
    event_label = f"{event_name} {instance_label}" if instance_label else event_name
    body = (
        f"@everyone One-day reminder: {event_label} starts tomorrow at {event_time}. "
        "Review assignments, prepare troops, and be ready before the event begins."
    )
    return f"{emoji} {event_name} - 1 Day Reminder", body
