# iObsi — Obsidian ⇄ iCloud Sync Daemon

Bidirectional sync daemon for your Obsidian vault between iCloud Drive and a Linux machine. Keeps your notes in sync without a third-party cloud.

Features a dark-theme web dashboard (port 11111) with real-time sync logs via WebSocket, a conflict resolution UI, config editor, and a CLI.

## Status and disclaimer

1. This is **VIBE CODED** (with opencode + big pickle model). I am not a developer, just needed this specific tool.
Now, I do realise that putting vibecoded shit on gh is questionable, to put it mildly, but i did spend a couple days debugging it, so someone might find it handy and save themselves a few hours.
2. Very much WIP. Feedback / PRs welcome. Seems to work for me but YMMV.
3. **I TAKE ABSOLUTELY NO RESPONSIBILITY FOR ANYTHING THIS TOOL CAUSES**, including complete data loss or anything else whatsoever.

**ALWAYS BACK UP YOUR VAULT!**  
**ALWAYS BACK UP YOUR VAULT!**  
**ALWAYS BACK UP YOUR VAULT!**

## Installation

```bash
git clone git@github.com:biomassa/iObsi.git && cd iObsi
python3 -m venv .venv && source .venv/bin/activate
pip install pyicloud watchdog keyring fastapi uvicorn jinja2 websockets python-multipart click
```

## Usage

```bash
source .venv/bin/activate

python3 sync.py setup   # first-time setup — Apple ID, 2FA, vault discovery
python3 sync.py run     # start daemon + web UI (http://localhost:11111)
python3 sync.py once    # single sync cycle
python3 sync.py status  # vault status
```

Alternatively, run without activating the venv first:

```bash
bash -c "source .venv/bin/activate && python3 sync.py setup"
bash -c "source .venv/bin/activate && python3 sync.py run"
bash -c "source .venv/bin/activate && python3 sync.py once"
bash -c "source .venv/bin/activate && python3 sync.py status"
```

The daemon watches your local vault via `watchdog`, polls iCloud Drive every 60s, and handles conflicts with a configurable strategy (last-writer-wins by default).
