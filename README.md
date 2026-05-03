# Kingshot Event Notification Bot

A Discord bot for Kingshot alliance event reminders. It supports recurring event schedules, Bear Trap role pings, localized Discord timestamps, private test previews, and automatic cleanup of reminder messages.

## Supported Events

- Bear Trap
- Viking Vengeance
- Swordland Showdown
- Eternity's Reach
- Castle Battle
- KvK

## Setup

1. Create and activate a Python virtual environment.

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

2. Install dependencies.

   ```powershell
   pip install -r requirements.txt
   ```

3. Copy `.env.example` to `.env` and fill in the values.

   ```env
   DISCORD_TOKEN=your_discord_bot_token
   BOT_OWNER_USER_ID=123456789012345678
   DB_PATH=kingshot_events.sqlite3
   DEFAULT_TIMEZONE=UTC
   DEFAULT_DELETE_ENABLED=true
   DEFAULT_DELETE_DELAY_MINUTES=60
   DEFAULT_REMINDER_LEAD_MINUTES=15
   SCHEDULER_POLL_SECONDS=15
   DELETION_POLL_SECONDS=15
   ```

4. Run the bot.

   ```powershell
   python bot.py
   ```

The bot creates and migrates its SQLite database automatically.

## Discord Setup

The bot owner is the user ID in `BOT_OWNER_USER_ID`. Only the owner can add or remove bot management roles.

Recommended first-time setup:

```text
/settings add-manage-role role:<manager role>
/settings set-role-channel channel:<bear role channel>
/settings set-announcement-channel channel:<event reminder channel>
/settings set-timezone timezone_name:Asia/Kolkata
/settings setup-bear-roles
```

The bot needs permissions to send messages, embed links, attach files, manage roles for Bear role assignment, and read member roles for management checks.

## Commands

Settings:

```text
/settings set-role-channel <channel>
/settings set-announcement-channel <channel>
/settings set-timezone <IANA timezone>
/settings set-delete-policy <enabled> [delay_minutes]
/settings setup-bear-roles
/settings show
/settings add-manage-role <role>
/settings remove-manage-role <role>
/settings list-manage-roles
```

Events:

```text
/events configure <event> [time] [date] [instance]
/events disable <event> [instance]
/events list
/events test <event|All Supported Events> [instance] [ephemeral]
```

`/events test` sends private ephemeral previews by default and suppresses real `@everyone` and role pings. Set `ephemeral:false` to post normal visible dummy embeds in the current channel, useful for testing companion bots such as the translation bot. When no instance is provided, it previews every supported instance or phase for that event. `All Supported Events` previews every supported event, instance/phase, and reminder phase.

## Time Display

Reminder embeds use Discord timestamps for exact start times:

```text
Start (your time)
Saturday, May 2, 2026 7:43 PM
```

Discord localizes that field for each viewer. The bot avoids printing duplicate UTC times in normal reminder text. Reset-based reminders use explicit labels such as `server reset` or `server time`.

## Event Configuration

Dates are used as the first occurrence date. They do not make the event one-shot. After a reminder sends, the bot advances the same configuration to the next recurrence and skips missed intervals if the bot was offline.

### Bear Trap

Instances:

```text
bear_1
bear_2
```

Configure each Bear instance separately:

```text
/events configure event:Bear Trap instance:bear_1 time:12:00 date:2026-05-01
/events configure event:Bear Trap instance:bear_2 time:16:00 date:2026-05-02
```

Recurrence: every 48 hours per configured Bear instance.

Final reminder: 15 minutes before the configured Bear time. Bear Trap reminders mention only the matching Bear role.

### Viking Vengeance

Instances:

```text
tuesday
thursday
```

Configure each day separately:

```text
/events configure event:Viking Vengeance instance:tuesday time:12:00
/events configure event:Viking Vengeance instance:thursday time:12:00
```

Recurrence: every 4 weeks. Tuesday is based on the reference Tuesday; Thursday is 2 days after that Tuesday.

Final reminder text:

```text
The Vikings are marching to burn your town in 15 minutes. Come online and join the defense!
```

### Swordland Showdown

Instances:

```text
legion1
legion2
```

Configure each Legion battle time separately:

```text
/events configure event:Swordland Showdown instance:legion1 time:14:00
/events configure event:Swordland Showdown instance:legion2 time:19:00
```

Recurrence: every 2 weeks.

Reminders:

- One event-level reminder 15 minutes before server reset:

  ```text
  Swordland Showdown opens after the next server reset. Legion battle reminders will go out before each configured battle time.
  ```

- One final instance reminder 15 minutes before each configured Legion battle time:

  ```text
  Swordland Showdown Legion 1 battle starts in 15 minutes.
  ```

### Eternity's Reach

Configure with a time because the shared command requires one, but the reminder text does not use a meaningful battle time.

```text
/events configure event:Eternity's Reach time:12:00
```

Recurrence: every 4 weeks.

Reminder: 15 minutes before server reset on the event-open date.

Reminder text:

```text
Eternity's Reach opens after the next server reset. Recall troops and prepare if you are joining.
```

### Castle Battle

Configure once with the UTC event date and battle time:

```text
/events configure event:Castle Battle date:2026-05-02 time:12:00
```

The bot creates two internal phases:

- Teleport Window: 1 hour before battle start
- Battle Start: configured battle time

Recurrence: every 4 weeks from the configured occurrence.

Reminders:

- One-day reminder for Battle Start
- Final reminder 15 minutes before each internal phase

### KvK

Configure once with the UTC event date:

```text
/events configure event:KvK date:2026-05-16
```

If Discord requires the `time` field, the bot also accepts the date there:

```text
/events configure event:KvK time:2026-05-16
```

The bot creates two internal phases:

- Borders & Teleport Open: 10:00 UTC
- Battle Start: 12:00 UTC

Recurrence: every 4 weeks from the configured occurrence.

Reminders:

- Two-week KvK prep reminder
- One-week KvK checkpoint reminder
- One-day reminder for Battle Start
- Final reminder 15 minutes before each internal phase

## Cleanup

Notifications are tracked in SQLite. If deletion is enabled, messages are removed after the event duration or the configured fallback delete delay.

Configure cleanup:

```text
/settings set-delete-policy enabled:true delay_minutes:60
```

## Assets

Reminder embeds use local thumbnail files from `data/assets` when available. If a local file is missing or cannot be attached, the bot falls back to the event thumbnail URL in `services/events.py`.

## Development Checks

Compile check:

```powershell
.\.venv\Scripts\python.exe -m py_compile bot.py services/events.py database/events.py
```
