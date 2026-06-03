# Obsidian ⇄ iCloud Sync Daemon

## Overview
Bidirectional sync daemon for an Obsidian vault between iCloud Drive and a Linux machine using `pyicloud`. Includes a dark-theme web dashboard on port 11111 with real-time logs (WebSocket), conflict resolution UI, config editor, and a CLI.

## Project Location
`/home/dingus/scripts/iObsi/`

## Virtual Environment
`/home/dingus/scripts/iObsi/.venv/` — required (Arch PEP 668).
Activate: `source /home/dingus/scripts/iObsi/.venv/bin/activate`

## CLI Entry Point
`/home/dingus/scripts/iObsi/sync.py` — Click-based CLI. All commands must be run inside the venv.

### Commands
- `python3 sync.py setup` — Interactive first-run: prompts for Apple ID, password, 2FA code, vault name (auto-discovers), local path config.
- `python3 sync.py run` — Start daemon (sync loop + watchdog watcher) + web UI (http://localhost:11111).
- `python3 sync.py once` — Run a single sync cycle, then exit.
- `python3 sync.py status` — Print vault name, local path, file/upload/download/conflict counts, recent logs.
- `python3 sync.py clear-auth` — Remove stored iCloud credentials from system keyring.

## Architecture

### File Layout
```
sync.py              — CLI entry point
config.py            — JSON config (~/.config/obsidian-icloud-sync/config.json)
state_db.py          — SQLite (WAL), tables: file_states, sync_log, conflicts, sync_meta
filters.py           — fnmatch ignore patterns
auth.py              — pyicloud auth, keyring, cookies, vault discovery
scanner.py           — SHA-256 head (4KiB) file hashing, local/remote inventory
conflict.py          — Strategies + manual resolution
sync_engine.py       — Core sync: bootstrap, diff, upload/download/delete, daemon loop
watcher.py           — Watchdog observer with 300ms debounce
web/
  server.py          — FastAPI app (8 REST routes, 4 HTML pages, 2 WebSocket endpoints)
  templates/
    base.html        — Dark theme base layout (Jinja2)
    dashboard.html   — Stats grid + live log table + controls
    logs.html        — Full log viewer
    conflicts.html   — Conflict queue with action buttons
    config.html      — Config form editor
  static/
    app.js           — WebSocket clients (auto-reconnect), API helpers, conflict UI
```

### Sync Flow
1. `scanner.scan_local()` walks vault dir → dict of `{rel_path: {mtime, size, hash_head}}`
2. `scanner.scan_remote()` walks iCloud Drive folder → same shape (etag instead of hash)
3. Engine compares both against `state_db.file_states`:
   - **New local only** → upload
   - **New remote only** → download
   - **Both changed** → conflict resolution
   - **Tracked but gone** → deletion propagation (if `sync_deletes` enabled)
4. All actions logged to DB + in-memory ring buffer (500 entries).
5. Conflicts recorded in `state_db.conflicts` — resolved automatically per config strategy or manually via web UI.

### Daemon Mode
- Background thread runs `sync_engine.daemon_loop()` — polls iCloud every 60s (configurable), reactive to `trigger_sync()`.
- Watchdog observer (`watcher.py`) fires `trigger_sync()` after 300ms debounce on local file changes.
- Web UI control: pause/resume/trigger via REST endpoints.

### Bootstrap
- If local vault directory has no `.obsidian/` at startup, `sync_engine.bootstrap_vault()` downloads ALL remote files (shows progress via logs).
- Bootstrap triggered in both `daemon_loop()` and `run_sync_cycle()`.

## Key Config (defaults)
- `local_path`: `/home/dingus/obsi`
- `web_port`: `11111`
- `poll_interval`: `60` seconds
- `conflict_strategy`: `last-writer-wins`
- `sync_deletes`: `True`
- `ignore_patterns`: `*.tmp`, `*.swp`, `*.part`, `*.icloud`, `.DS_Store`, `.*`, `~$*`, `.trash/`, `.sync-tmp-*`, `.obsidian/workspace`, `.obsidian/workspace-mobile`

## Web API
All at `http://localhost:11111`:

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Dashboard HTML |
| GET | `/logs` | Log viewer HTML |
| GET | `/conflicts` | Conflict queue HTML |
| GET | `/config` | Config editor HTML |
| GET | `/api/status` | JSON: running, paused, stats, conflict count |
| POST | `/api/sync` | Trigger sync cycle |
| POST | `/api/pause` | Pause sync |
| POST | `/api/resume` | Resume sync |
| GET | `/api/logs?tail=100` | Recent log entries |
| GET | `/api/conflicts` | Unresolved conflicts |
| POST | `/api/conflicts/{path}?action=local\|remote\|keep-both\|skip` | Resolve conflict |
| GET | `/api/config` | Current config JSON |
| PUT | `/api/config` | Update config (JSON body) |
| GET | `/api/stats` | Sync statistics |
| WS | `/ws/logs` | Live log stream (JSON, 30s pings) |
| WS | `/ws/status` | Status push every 2s |

## Conflict Strategies
- `last-writer-wins` — compare mtime (default)
- `keep-both` — rename local with " (iCloud Conflict)" suffix
- `prefer-local` — always keep local version
- `prefer-remote` — always accept remote version
- `skip` — skip and record conflict (resolve manually later)

## Auth
- Apple ID password stored in system keyring (`obsidian-icloud-sync` service).
- pyicloud session cookies at `~/.config/obsidian-icloud-sync/session/` (managed by pyicloud's built-in cookie persistence via `cookie_directory` parameter).
- `sync.py setup` handles interactive 2FA.
- Session cookies last ~2 months.

## Dependencies (in .venv)
- pyicloud, watchdog, keyring, fastapi, uvicorn, jinja2, websockets, python-multipart, click

## Important Implementation Notes
- `state_db.py` uses `threading.local()` for per-thread SQLite connections (WAL mode).
- `sqlite3.Row` results are converted with `dict(row)` before returning to callers (so `.get()` works on results).
- File writes are atomic: download to temp dir → `shutil.move()` to final path.
- SHA-256 of first 4KB for change detection (fast, sufficient for .md files).
- Starlette 1.2.1 `Jinja2Templates.TemplateResponse` signature is `(request, name, context)` — template route handlers updated accordingly.
- WebSocket `/ws/logs` keepalive ping every 30s.
- Log ring buffer in `sync_engine.py` (`_LOG_RING_MAX = 500`) + `subscribe_logs()`/`unsubscribe_logs()` for WebSocket fan-out.
- iCloud Drive has no webhooks — polling only.
- `discover_vaults()` uses `ThreadPoolExecutor` for parallel root-item probes.
- Vault entries can be `type="app_library"` (not just `"folder"`) — both are handled in `discover_vaults()` and `find_vault_root()`.
- `find_vault_root()` supports nested paths split by `/` (e.g. `Obsidian/Obsidian`).

## Testing
All web endpoints verified (200 on all GET/POST/PUT routes). No formal test framework configured.
