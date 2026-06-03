# iObsi — Obsidian ⇄ iCloud Sync Daemon

Bidirectional sync daemon for your Obsidian vault between iCloud Drive and a Linux machine. Keeps your notes in sync without a third-party cloud.

Features a dark-theme web dashboard (port 11111) with real-time sync logs via WebSocket, a conflict resolution UI, config editor, and a CLI.

## Installation

```bash
git clone <url> && cd iObsi
python3 -m venv .venv && source .venv/bin/activate
pip install pyicloud watchdog keyring fastapi uvicorn jinja2 websockets python-multipart click
```

## Usage

```bash
source .venv/bin/activate

# First-time setup — Apple ID, 2FA, vault discovery
python3 sync.py setup

# Start the daemon (sync loop + web UI at http://localhost:11111)
python3 sync.py run

# Or run a single sync cycle and exit
python3 sync.py once

# Check vault status
python3 sync.py status
```

The daemon watches your local vault via `watchdog`, polls iCloud Drive every 60s, and handles conflicts with a configurable strategy (last-writer-wins by default).
