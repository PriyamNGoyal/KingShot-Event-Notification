# Implementation Plan

## Current supported events

- Bear Trap
- Viking Vengeance
- Swordland Showdown
- Eternity's Reach
- Castle Battle
- KvK

Caesares Fury and all other events are intentionally unsupported.

## Simplified Castle Battle and KvK configuration

- Castle Battle users provide only the UTC event date and UTC battle time.
- Castle Battle internally stores two phases: `teleport_window` at battle time minus 1 hour, and `battle_start` at the provided battle time.
- KvK users provide only the UTC event date.
- KvK internally stores two phases: `teleport_window` at `10:00 UTC`, and `battle_start` at `12:00 UTC`. The `teleport_window` phase is displayed as Borders & Teleport Open because border opening and teleport opening happen at the same time.
- Users no longer configure `teleport_window`, `battle_start`, or `borders_open` directly for these grouped events.

## Sample commands

- Castle Battle: `/events configure event:Castle Battle time:12:00 date:2026-05-02`
- KvK: `/events configure event:KvK date:2026-05-16`
- KvK fallback if a Discord client requires a value in `time`: `/events configure event:KvK time:2026-05-16`

## Reminder behavior

- Final reminders remain 15 minutes before each internally generated phase.
- One-day reminders for Castle Battle and KvK are sent for the internally generated `battle_start` phase only.
- Eternity's Reach has no meaningful user-configured time granularity. Its final reminder is sent at `23:45 UTC` on the previous calendar day and says it opens tomorrow at reset, with a simple open-date field instead of a configured event time.
- `/events list` and `/events disable` group Castle Battle and KvK phases into a user-facing single event when no internal instance is specified; old KvK `borders_open` rows are treated as equivalent to `teleport_window` for display and disabling without destructive database changes.
- `/events test` is management/owner-only, uses dummy/sample data instead of stored event rows, sends to the current channel instead of the configured announcement channel, and suppresses real pings while still using the normal embed/thumbnail send path.
- `/events test event:All Supported Events` sends dummy samples for every supported event. Grouped events without an instance send each generated phase; non-grouped events with instances use a sensible default sample unless a valid instance is provided.
