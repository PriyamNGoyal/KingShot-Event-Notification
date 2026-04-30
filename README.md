# Kingshot Event Notification Bot

Lightweight Discord notification bot for the approved Kingshot event set only:

- Bear Trap
- Viking Vengeance
- Swordland Showdown
- Eternity's Reach
- Castle Battle
- KvK

Explicitly unsupported and intentionally not implemented: Tri-Alliance Clash, Fortress Battle, Daily Reset, and any event not listed above.

## Setup

1. Install Python 3.11+.
2. Create a virtual environment and install packages:

   ```powershell
   uv venv .venv
   .venv\Scripts\activate
   uv pip install -r requirements.txt
   ```

3. Copy `.env.example` to `.env` and set:

   - `DISCORD_TOKEN`: your Discord bot token.
   - `BOT_OWNER_USER_ID`: the Discord user ID allowed to manage role access globally.
   - `DB_PATH`: SQLite database path, default `kingshot_events.sqlite3`. Parent directories are created automatically at startup and on database access.
   - `DEFAULT_TIMEZONE`: default guild timezone, default `UTC`.
   - `DEFAULT_DELETE_ENABLED`: `true` or `false`.
   - `DEFAULT_DELETE_DELAY_MINUTES`: fallback cleanup delay.
   - `DEFAULT_REMINDER_LEAD_MINUTES`: reminder lead time; default and intended value is `15`.

4. In the Discord Developer Portal, enable the Server Members Intent for Bear role button assignment.
5. Invite the bot with permissions for Send Messages, Embed Links, Mention Everyone, Manage Roles, and Manage Messages if cleanup is enabled.
6. Start the bot:

   ```powershell
   python bot.py
   ```

   On startup, the bot initializes SQLite automatically, creates missing tables and indexes, and applies additive schema migrations for missing columns without deleting existing data.

   The bot ships supported event thumbnail files in `data/assets` and attaches those local files to reminder embeds when available. If a local thumbnail file is missing or cannot be attached, the embed falls back to that event's metadata `thumbnail_url` Imgur URL.

## Discord configuration flow

Use slash commands in each server:

1. `/settings add-manage-role <role>` as the bot owner, if non-owner staff should manage settings.
2. `/settings set-announcement-channel <channel>` for event reminders.
3. `/settings set-role-channel <channel>` for Bear role opt-in buttons.
4. `/settings set-timezone <timezone>` such as `UTC` or `Asia/Kolkata`.
5. `/settings setup-bear-roles` to create/reuse `Bear 1` and `Bear 2`, post/update the persistent button panel, and announce the role selection in the announcement channel.
6. `/events configure <event> [time] [date] [instance]` to enable reminders. Most events require `time`; Castle Battle requires `date` plus battle `time`; KvK requires only `date`. Eternity's Reach still accepts a time because of the shared command, but that value is only a placeholder for scheduling storage and is ignored in reminder text; there is no meaningful time granularity to configure for Eternity's Reach.

## Event instances

- Bear Trap requires `bear_1` or `bear_2`, shown to users as Bear 1 or Bear 2.
- Viking Vengeance supports `tuesday` and `thursday`, shown to users as Tuesday or Thursday.
- Swordland Showdown supports `legion1` and `legion2`, shown to users as Legion 1 or Legion 2.
- Castle Battle is configured once by users with event date and battle time. The bot internally creates Teleport Window and Battle Start phases; Teleport Window is always 1 hour before battle time.
- KvK is configured once by users with event date only. The bot internally creates Borders & Teleport Open at `10:00 UTC` and Battle Start at `12:00 UTC` on that date; border opening and teleport opening are the same phase/time, not separate configuration items.
- Events without a meaningful instance, including Eternity's Reach stored as `default`, omit instance text in user-facing messages.

## Reminder behavior

- Bear Trap reminders mention only the matching Bear role.
- All other configured approved events mention `@everyone`.
- Notification message text and embeds include full UTC date/time values, for example `2026-05-01 12:00 UTC`, except Eternity's Reach reset/open reminders, which intentionally show the open date at reset instead of a configured time.
- Bear Trap, Viking Vengeance, Castle Battle, and KvK final reminders are sent 15 minutes before the configured start time by default.
- Viking Vengeance keeps its Tuesday/Thursday 4-week schedule and supports custom configured times in 5-minute slots for both `tuesday` and `thursday` instances.
- Swordland Showdown reminders are sent at `23:45 UTC` on the previous calendar day: 15 minutes before `00:00 UTC` on the event-open date. Their reminder text says the event opens today/at reset and includes the configured battle date/time.
- Eternity's Reach reminders are sent at `23:45 UTC` on the previous calendar day if configured. The reminder says Eternity's Reach opens tomorrow at reset, shows `Opens: YYYY-MM-DD at reset (00:00 UTC)`, and does not show or require a meaningful configured event time.
- Castle Battle and KvK also send a persistent-state-tracked `@everyone` one-day reminder for the internally generated Battle Start phase.
- Notification messages are tracked in SQLite and cleaned up after the event duration or the configured fallback delay.
- One-time configurations using `[date]` are disabled after they notify once.
- Reminder embeds use local Discord file attachments for event thumbnails from `data/assets` first. If a local file is missing or cannot be attached, normal reminders, one-day reminders, and `/events test` reminders fall back to the event metadata `thumbnail_url` Imgur URL from `services/events.py`.
- `/events test` is restricted to the bot owner or configured management roles, but it no longer requires a configured event row or announcement channel. It builds dummy/sample event data, sends the test embed to the channel where the command is invoked, and suppresses real `@everyone`/role pings for safer testing.
- `/events test event:All Supported Events` sends dummy reminders for every supported event sample. Grouped events without an `instance` send each generated phase; KvK uses the single Borders & Teleport Open sample for its `10:00 UTC` phase. Non-grouped multi-instance events default to a representative sample instance unless an instance is supplied.

## Reference metadata notes

- The supported event thumbnails and emoji metadata are aligned with `../Kingshot-Discord-Bot/cogs/bear_event_types.py`.
- Reference `image_url` values for the supported events are empty placeholders; no additional local image/icon asset files were found in `../Kingshot-Discord-Bot` beyond the existing thumbnail URLs, so those URLs were used to download the shipped `data/assets` thumbnails and remain as runtime Imgur fallback URLs when a local thumbnail is unavailable.

## Sample event configurations

- Castle Battle on `2026-05-02` with battle at `12:00 UTC`: `/events configure event:Castle Battle time:12:00 date:2026-05-02`
- KvK on `2026-05-16`: `/events configure event:KvK date:2026-05-16`
- For KvK only, if the Discord client requires filling `time`, the bot also accepts the date in the `time` field: `/events configure event:KvK time:2026-05-16`

## Sample event tests

- Test a single dummy event in the current channel: `/events test event:Bear Trap`
- Test a specific dummy event instance: `/events test event:Swordland Showdown instance:legion2`
- Test all phases of a grouped event: `/events test event:Castle Battle`
- Test every supported dummy event sample: `/events test event:All Supported Events`

## Production deployment

This repository deploys to the same VM as the Kingshot Gift Bot through GitHub Actions over SSH.

- GitHub repository: `https://github.com/PriyamNGoyal/KingShot-Event-Notification.git`
- Deployment branch: `main`
- Server user: `ubuntu`
- Server repository path: `/home/ubuntu/KingShot-Event-Notification`
- systemd service name: `kingshot-event-notification`
- Workflow: `.github/workflows/deploy.yml`
- Service template: `deploy/kingshot-event-notification.service`

### Server bootstrap

Run these commands once on the VM as `ubuntu`.

```bash
sudo apt-get update
sudo apt-get install -y git python3 python3-venv python3-pip

sudo mkdir -p /var/lib/kingshot_event_notification
sudo chown ubuntu:ubuntu /var/lib/kingshot_event_notification
sudo chmod 750 /var/lib/kingshot_event_notification

cd /home/ubuntu
git clone https://github.com/PriyamNGoyal/KingShot-Event-Notification.git KingShot-Event-Notification
cd /home/ubuntu/KingShot-Event-Notification

python3 -m venv venv
venv/bin/pip install --upgrade pip
venv/bin/pip install -r requirements.txt

cp deploy/kingshot-event-notification.service /tmp/kingshot-event-notification.service
sudo mv /tmp/kingshot-event-notification.service /etc/systemd/system/kingshot-event-notification.service
sudo systemctl daemon-reload
sudo systemctl enable kingshot-event-notification
sudo systemctl start kingshot-event-notification
```

If the repository already exists on the VM, replace the `git clone` step with:

```bash
cd /home/ubuntu/KingShot-Event-Notification
git fetch origin
git reset --hard origin/main
```

### Server `.env`

Create `/home/ubuntu/KingShot-Event-Notification/.env` on the VM. Do not commit `.env` to GitHub.

Production `DB_PATH` must point outside the repository so deploys do not overwrite runtime data:

```dotenv
DISCORD_TOKEN=your_discord_bot_token
BOT_OWNER_USER_ID=123456789012345678
DB_PATH=/var/lib/kingshot_event_notification/bot.db
DEFAULT_TIMEZONE=UTC
DEFAULT_DELETE_ENABLED=true
DEFAULT_DELETE_DELAY_MINUTES=60
DEFAULT_REMINDER_LEAD_MINUTES=15
SCHEDULER_POLL_SECONDS=15
DELETION_POLL_SECONDS=15
```

The `.env` file and runtime SQLite database must not be committed. Keep `/var/lib/kingshot_event_notification/bot.db` on the server only.

### systemd service file

The production service file should be installed at `/etc/systemd/system/kingshot-event-notification.service` with these contents:

```ini
[Unit]
Description=Kingshot Event Notification Discord Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=ubuntu
Group=ubuntu
WorkingDirectory=/home/ubuntu/KingShot-Event-Notification
EnvironmentFile=/home/ubuntu/KingShot-Event-Notification/.env
ExecStart=/home/ubuntu/KingShot-Event-Notification/venv/bin/python /home/ubuntu/KingShot-Event-Notification/bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

After editing the service file, run:

```bash
sudo systemctl daemon-reload
sudo systemctl restart kingshot-event-notification
```

### GitHub Actions secrets

Configure these repository secrets in GitHub before relying on automatic deploys:

- `SERVER_IP`: VM public IP or DNS name.
- `SERVER_USER`: `ubuntu`.
- `SSH_PRIVATE_KEY`: private SSH key allowed to connect as `ubuntu`.

The deploy workflow runs on pushes to `main` and performs:

1. SSH to the VM.
2. `cd /home/ubuntu/KingShot-Event-Notification`.
3. `git fetch origin`.
4. `git reset --hard origin/main`.
5. `venv/bin/pip install -r requirements.txt`.
6. `sudo systemctl restart kingshot-event-notification`.

Ensure the `ubuntu` user has passwordless sudo for `systemctl restart kingshot-event-notification`, or the GitHub Actions SSH step can fail while restarting the service.

### Post-deploy checks

Run these checks on the VM after bootstrap or a deploy:

```bash
cd /home/ubuntu/KingShot-Event-Notification
git rev-parse --abbrev-ref HEAD
git log -1 --oneline
test -f .env
test ! -f bot.db
test -f /var/lib/kingshot_event_notification/bot.db || echo "Database will be created on first startup"
sudo systemctl status kingshot-event-notification --no-pager
sudo journalctl -u kingshot-event-notification -n 100 --no-pager
```
