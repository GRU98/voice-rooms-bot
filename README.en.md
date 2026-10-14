<div align="center">

# 🎙 TempVoice Bot

**Personal temporary voice rooms on demand: join a channel, get your own room with a control panel.**

[![Python](https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![discord.py](https://img.shields.io/badge/discord.py-2.x-5865F2?logo=discord&logoColor=white)](https://discordpy.readthedocs.io/)
[![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.x_async-D71F00)](https://www.sqlalchemy.org/)
[![Docker](https://img.shields.io/badge/Docker-ready-2496ED?logo=docker&logoColor=white)](https://www.docker.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

[Русский](README.md) · **English**

</div>

---

## 📖 Table of contents

- [Features](#-features)
- [How it works](#-how-it-works)
- [Quick start](#-quick-start)
- [Create the Discord bot](#-create-the-discord-bot)
- [Installation](#-installation)
- [Server setup](#-server-setup)
- [Room panel](#-room-panel)
- [Commands](#-commands)
- [Configuration](#-configuration)
- [Bot permissions](#-bot-permissions)
- [Architecture](#-architecture)
- [PostgreSQL instead of SQLite](#-postgresql-instead-of-sqlite)
- [Troubleshooting](#-troubleshooting)
- [Security](#-security)
- [License](#-license)

---

## ✨ Features

| | |
|---|---|
| ➕ **Create on join** | Join the trigger channel and the bot creates a room and moves you into it |
| 🎛 **Panel in the room's chat** | Buttons, selects and modals live in the voice channel's built-in chat, no extra text channel |
| 🔒 **Lock / unlock** | Stop new members from connecting |
| 👁 **Hide / show** | Hide the room from others, people inside stay |
| ✏️ **Rename** | Via a modal form |
| 👥 **User limit** | Pick from a list, from unlimited to 99 |
| 👤 **Kick / block / unblock** | Blocks are stored in the database until the owner removes them |
| 👑 **Ownership transfer** | Manual, or automatic when the owner leaves |
| 📶 **Bitrate** | Limited by the server's boost level |
| 🗑 **Delete room** | One click |
| 💾 **Personal name preset** | Save the room name — your next rooms get it automatically |
| 📩 **Panel to bottom** | Re-posts the panel at the end of the room's chat |
| ⚙️ **`/setup`** | Channel Select menus (no IDs) and **Automatic Setup** |
| 🔁 **Resilient** | Panels survive restarts, the database is reconciled with Discord |
| 🏢 **Multi-guild** | Separate settings per server |
| 🐳 **Docker + nginx** | Ready-made `docker-compose.yml` and a `/health` endpoint |

## 🧭 How it works

```
User joins ➕・Create room
   ├─ the bot creates one voice channel in the configured category
   ├─ moves the user into it
   └─ posts the control panel in that voice channel's chat
The owner manages the room with the panel buttons
Everyone leaves → deletion timer → channel deleted, database record removed
```

The owner gets permissions **only on their own room** and never Administrator, Manage Guild or Manage Channels. Only the owner
and server administrators can use a room's panel; this is re-checked on every interaction.

## 🚀 Quick start

1. [Create the bot](#-create-the-discord-bot) and copy its token.
2. Install it using any method from [Installation](#-installation).
3. Invite the bot and run `/setup` → **⚡ Automatic Setup**.
4. Join the `➕・Create room` channel.

## 🤖 Create the Discord bot

1. Open the [Developer Portal](https://discord.com/developers/applications) → **New Application**.
2. **Bot** tab → **Reset Token** → copy the token (shown only once).
3. Under **Privileged Gateway Intents** enable **Server Members Intent** and save. Without it the bot will not start
   (`4014 Disallowed intent(s)`). Message Content Intent is **not** needed.
4. **OAuth2 → URL Generator**:
   - Scopes: `bot`, `applications.commands`
   - Bot permissions: see [Bot permissions](#-bot-permissions)
5. Open the generated URL and add the bot to your server.

## 📦 Installation

Requirements: **Python 3.12+** (without Docker) or **Docker** with the Compose plugin.

For every method, prepare the settings first:

```bash
cp .env.example .env        # Windows (cmd): copy .env.example .env
# open .env and set DISCORD_TOKEN
```

### Windows

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python bot.py
```

### Linux / macOS

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python bot.py
```

### Docker (any OS)

```bash
docker compose up -d --build
docker compose logs -f bot
```

Two containers start: `bot` and `nginx`. The database lives in `./data` and survives rebuilds. Check with `curl http://localhost/health`.
nginx is optional: it only proxies `/health`. Remove the `nginx` service from `docker-compose.yml` if you don't need it.

### One command on Debian 12

```bash
git clone <your-repo> voice-bot && cd voice-bot
sudo bash deploy/install_debian12.sh
```

The script installs Docker (if missing), asks for the token, creates `.env`, fixes permissions on `data` and starts the containers.

**Updating on the server:**

```bash
git pull && docker compose up -d --build
```

## ⚙️ Server setup

`/setup` (administrators only) opens the configuration panel:

| Button | What it does |
|---|---|
| ⚡ **Automatic Setup** | Creates the `🎙 TEMPORARY ROOMS` category and the trigger channel, enables the system |
| 🎙 **Trigger** | Pick the channel that creates rooms when joined |
| 📁 **Category** | Category where rooms are created |
| 👥 **Default Limit** | Default user limit |
| ⏱ **Delete Delay** | Seconds before an empty room is deleted |
| ✏️ **Room Name** | Name template, `{user}` is replaced with the owner's name |
| 👑 **Auto Transfer** | Hand ownership over when the owner leaves |
| 🟢 / 🔴 **Enable / Disable** | Turn the system on or off |

If the bot lacks permissions, the panel shows a warning listing the missing ones.

## 🎛 Room panel

The panel appears in the voice channel's chat right after the room is created and is edited in place.

| Button | Action |
|---|---|
| 🔒 Lock / 🔓 Unlock | Forbid or allow connecting |
| 👁 Hide / 👀 Show | Hide the room from others |
| ✏️ Name | Rename the room |
| 👥 Limit | Choose the user limit |
| 👑 Owner | Transfer ownership to another member |
| 👤 Members | Kick, block, list blocked users and unblock |
| ⚙️ Settings | Bitrate, delete room, save and clear your personal name preset |
| 📩 Panel to bottom | Deletes the old panel and posts a fresh one at the end of the chat |

> Discord allows renaming a channel only twice per 10 minutes. The bot waits up to 15 seconds and reports when the limit is hit.

When a room is hidden, members inside get a personal view grant; it is revoked automatically when they leave the room
or get blocked. A blocked user cannot see a hidden room.

## 💬 Commands

| Command | Who | Description |
|---|---|---|
| `/setup` | administrators | Bot configuration panel |
| `/voice_admin rooms` | administrators | List active rooms of the server |
| `/voice_admin reconcile` | administrators | Reconcile the database with Discord and clean up |

## 🔧 Configuration

Environment variables (`.env`):

| Variable | Default | Description |
|---|---|---|
| `DISCORD_TOKEN` | — | Bot token (required) |
| `DATABASE_URL` | `sqlite+aiosqlite:///./data/bot.db` | Database connection string |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `HEALTH_HOST` | `127.0.0.1` | Health endpoint host (`0.0.0.0` in Docker) |
| `HEALTH_PORT` | `8080` | Health endpoint port, `0` disables it |

## 🔑 Bot permissions

Grant these to the bot's **role** (Administrator is not required).

| Permission | Why |
|---|---|
| View Channels | See the category and rooms |
| Manage Channels | Create, delete and edit channels |
| Manage Roles | Set channel overwrites (lock, hide, block) |
| Connect | The bot's own overwrite on a room |
| Move Members | Move users into the room, kick and block |
| Send Messages | Post the panel in the room's chat |
| Embed Links | The panel is an embed |
| Read Message History | Edit the panel after a restart |

If permissions are missing, no room is created and the log shows `bot lacks permissions [...]`.

## 🏗 Architecture

```
discord_voice_bot/
├── bot.py                  # entry point, service wiring, /health
├── config.py               # .env loading
├── cogs/
│   ├── voice.py            # voice events and channel deletion
│   ├── setup.py            # /setup
│   └── admin.py            # /voice_admin
├── services/
│   ├── voice_service.py    # room lifecycle, owner actions, reconciliation
│   ├── channel_service.py  # channel create/delete, panel
│   ├── permission_service.py  # all overwrites in one place
│   └── ownership_service.py   # ownership transfer
├── views/                  # panel, selects, modals, /setup
├── database/               # models, repositories, migrations (SQLAlchemy async)
├── utils/                  # locks, permission checks, logging
├── deploy/install_debian12.sh
├── nginx/default.conf
├── Dockerfile
└── docker-compose.yml
```

**Concurrency:** an `asyncio.Lock` per guild (creation) and per room (join, leave, delete, owner actions). Deletion is an
`asyncio.Task` that is cancelled on join and re-checks emptiness before deleting.

**After a restart:** records of missing channels are removed, empty rooms are cleaned up, missing owners are replaced
(if auto transfer is on) and lost panel messages are re-posted.

## 🐘 PostgreSQL instead of SQLite

```bash
pip install asyncpg
```

```env
DATABASE_URL=postgresql+asyncpg://user:password@host:5432/dbname
```

No code changes are needed: all database access goes through async SQLAlchemy repositories.

## 🩺 Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `4014 Disallowed intent(s)` / `PrivilegedIntentsRequired` | Enable **Server Members Intent** in Developer Portal → Bot |
| `LoginFailure` / invalid token | Reset the token in the Developer Portal and update `.env` |
| No `/setup` command | Invite the bot with the `applications.commands` scope and wait a couple of minutes |
| Room is not created | Check the bot's permissions and `docker compose logs bot` (`bot lacks permissions`) |
| No panel in the room chat | The bot needs Send Messages, Embed Links and Read Message History on the category |
| `permission denied` on `data` in Docker | `sudo chown -R 1000:1000 data` |
| PyNaCl / davey warnings | Harmless, the bot does not play audio |

## 🔐 Security

- Keep the token only in `.env` (it is in `.gitignore`); never commit it or put it in `.env.example`.
- If the token leaks via git, chat or a screenshot, reset it in the Developer Portal immediately.
- Room owners get no administrative rights; every action is authorized server-side on each click.

## 📄 License

[MIT](LICENSE) — free to use, modify and distribute as long as the copyright notice is kept.
