import asyncio
import json
import os
import time
import queue
import threading
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from jinja2 import Environment as Jinja2Env, FileSystemLoader
import uvicorn

from config import load as load_config, save as save_config
from sync_engine import (
    get_logs, subscribe_logs, unsubscribe_logs,
    is_running, is_paused, trigger_sync, shutdown,
    _load_stats, set_log_level, log as engine_log,
    get_pending_deletions, confirm_pending_deletions, cancel_pending_deletions, upload_pending_deletions,
)
from state_db import unresolved_conflicts, resolve_conflict, remove_conflict, set_meta, clear_logs

HERE = Path(__file__).parent
TEMPLATES = HERE / "templates"
STATIC = HERE / "static"

app = FastAPI(title="Obsidian iCloud Sync")
jinja_env = Jinja2Env(loader=FileSystemLoader(str(TEMPLATES)), cache_size=0)
templates = Jinja2Templates(env=jinja_env)

app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")

_ws_clients = set()


# ── HTML pages ──────────────────────────────────────


PROJECT_ROOT = HERE.parent

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    pending = get_pending_deletions()
    return templates.TemplateResponse(
        request, "dashboard.html", {
            "pending": pending,
            "venv_activate": str(PROJECT_ROOT / ".venv" / "bin" / "activate"),
            "sync_py": str(PROJECT_ROOT / "sync.py"),
        }
    )


@app.get("/logs", response_class=HTMLResponse)
async def logs_page(request: Request):
    return templates.TemplateResponse(
        request, "logs.html", {}
    )


@app.get("/conflicts", response_class=HTMLResponse)
async def conflicts_page(request: Request):
    return templates.TemplateResponse(
        request, "conflicts.html", {}
    )


@app.get("/config", response_class=HTMLResponse)
async def config_page(request: Request):
    cfg = load_config()
    return templates.TemplateResponse(
        request, "config.html", {"config": cfg}
    )


# ── REST API ────────────────────────────────────────


@app.get("/api/status")
async def api_status():
    cfg = load_config()
    stats = _load_stats()
    pending = get_pending_deletions()
    return {
        "running": is_running(),
        "paused": is_paused(),
        "vault_path": cfg["local_path"],
        "vault_name": cfg.get("vault_name", ""),
        **stats,
        "conflicts": len(unresolved_conflicts()),
        "pending_deletions": len(pending),
        "pending_list": pending,
    }


@app.post("/api/sync")
async def api_sync():
    engine_log("INFO", "Manual sync triggered via web UI")
    trigger_sync()
    return {"ok": True, "message": "Sync triggered"}


@app.get("/api/pending-deletions")
async def api_pending_deletions():
    return get_pending_deletions()


@app.post("/api/pending-deletions/confirm")
async def api_confirm_deletions():
    try:
        from config import load as load_cfg
        from auth import authenticate, find_vault_root, get_password
        cfg = load_cfg()
        api = authenticate(cfg["apple_id"], get_password(cfg["apple_id"]), interactive=False)
        vault_node = find_vault_root(api, cfg["vault_name"])
        confirm_pending_deletions(api, vault_node, cfg)
        return {"ok": True, "message": "Deletions confirmed"}
    except Exception as e:
        engine_log("ERROR", f"Failed to confirm deletions: {e}")
        return {"ok": False, "message": str(e)}


@app.post("/api/pending-deletions/cancel")
async def api_cancel_deletions():
    cancel_pending_deletions()
    return {"ok": True, "message": "Deletions skipped"}


@app.post("/api/pending-deletions/upload")
async def api_upload_deletions():
    try:
        from config import load as load_cfg
        from auth import authenticate, find_vault_root, get_password
        cfg = load_cfg()
        api = authenticate(cfg["apple_id"], get_password(cfg["apple_id"]), interactive=False)
        vault_node = find_vault_root(api, cfg["vault_name"])
        upload_pending_deletions(api, vault_node, cfg)
        return {"ok": True, "message": "Files uploaded back to iCloud"}
    except Exception as e:
        engine_log("ERROR", f"Failed to upload pending files: {e}")
        return {"ok": False, "message": str(e)}


@app.post("/api/clear-stats")
async def api_clear_stats():
    for key in ("uploaded", "downloaded", "conflicts", "errors", "deleted"):
        set_meta(f"stats_{key}", "0")
    set_meta("last_sync", "")
    clear_logs()
    engine_log("INFO", "Stats cleared")
    return {"ok": True}


@app.post("/api/stop")
async def api_stop():
    engine_log("INFO", "Stop requested via web UI — shutting down")
    shutdown()
    loop = asyncio.get_event_loop()
    loop.call_later(1, os._exit, 0)
    return {"status": "stopping"}


@app.get("/api/logs")
async def api_logs(tail: int = 100):
    return get_logs(limit=tail)


@app.get("/api/conflicts")
async def api_conflicts():
    rows = unresolved_conflicts()
    return [
        {
            "path": r["path"],
            "local_mtime": r["local_mtime"],
            "remote_mtime": r["remote_mtime"],
            "local_preview": r["local_preview"],
            "remote_preview": r["remote_preview"],
            "created_at": r["created_at"],
        }
        for r in rows
    ]


@app.post("/api/conflicts/{path:path}")
async def api_resolve_conflict(path: str, action: str = "local"):
    from config import load as load_cfg
    from conflict import resolve_manually

    cfg = load_cfg()
    result = resolve_manually(path, action, cfg["local_path"])
    if result == "download":
        trigger_sync()
    return {"ok": True, "resolution": result}


@app.get("/api/config")
async def api_get_config():
    cfg = load_config()
    cfg.pop("apple_id", None)
    return cfg


@app.put("/api/config")
async def api_put_config(data: dict):
    cfg = load_config()
    for k, v in data.items():
        if k in cfg and k not in ("apple_id",):
            cfg[k] = v
    save_config(cfg)
    if "log_level" in data:
        set_log_level(data["log_level"])
    return {"ok": True}


@app.get("/api/stats")
async def api_stats():
    return _load_stats()


# ── WebSocket: live logs ────────────────────────────


@app.websocket("/ws/logs")
async def ws_logs(websocket: WebSocket):
    await websocket.accept()
    q = queue.Queue()
    subscribe_logs(q)
    _ws_clients.add(websocket)
    loop = asyncio.get_running_loop()
    try:
        while True:
            try:
                entry = await loop.run_in_executor(None, q.get, 30)
                await websocket.send_json(entry)
            except queue.Empty:
                try:
                    await websocket.send_json({"type": "ping"})
                except Exception:
                    break
    except WebSocketDisconnect:
        pass
    finally:
        unsubscribe_logs(q)
        _ws_clients.discard(websocket)


@app.websocket("/ws/status")
async def ws_status(websocket: WebSocket):
    await websocket.accept()
    _ws_clients.add(websocket)
    try:
        while True:
            stats = _load_stats()
            pending = get_pending_deletions()
            await websocket.send_json({
                "running": is_running(),
                "paused": is_paused(),
                **stats,
                "conflicts": len(unresolved_conflicts()),
                "pending_deletions": len(pending),
                "pending_list": pending,
            })
            await asyncio.sleep(2)
    except WebSocketDisconnect:
        pass
    finally:
        _ws_clients.discard(websocket)


# ── startup / shutdown hooks ────────────────────────


@app.on_event("startup")
async def startup():
    pass


@app.on_event("shutdown")
async def shutdown_event():
    shutdown()
