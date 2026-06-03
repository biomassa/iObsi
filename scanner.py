import hashlib
import os
import time
import datetime
import concurrent.futures

from filters import should_ignore


def _log(level, message):
    from sync_engine import log as se_log
    se_log(level, message)


def hash_file_head(filepath, bytes_to_read=4096):
    h = hashlib.sha256()
    try:
        with open(filepath, "rb") as f:
            h.update(f.read(bytes_to_read))
        return h.hexdigest()
    except Exception:
        return None


def scan_local(vault_path, extra_ignore=None):
    result = {}
    vault_path = os.path.abspath(vault_path)
    for dirpath, dirnames, filenames in os.walk(vault_path):
        for d in list(dirnames):
            rel = os.path.relpath(os.path.join(dirpath, d), vault_path)
            if should_ignore(rel, extra_ignore):
                dirnames.remove(d)

        for fname in filenames:
            abspath = os.path.join(dirpath, fname)
            rel = os.path.relpath(abspath, vault_path)
            if should_ignore(rel, extra_ignore):
                continue
            try:
                st = os.stat(abspath)
                result[rel] = {
                    "path": rel,
                    "mtime": st.st_mtime,
                    "size": st.st_size,
                    "hash": hash_file_head(abspath),
                }
            except OSError:
                continue
    return result


def _walk_sync(node, prefix=""):
    entries = {}
    children = getattr(node, "_children", None)
    if children is None:
        try:
            node.get_children()
            children = node._children or []
        except Exception:
            return entries
    for child in children or []:
        name = child.name
        rel = f"{prefix}/{name}" if prefix else name
        if should_ignore(rel):
            continue
        try:
            if child.type == "folder":
                entries.update(_walk_sync(child, rel))
            else:
                entries[rel] = {
                    "path": rel,
                    "mtime": (
                        child.date_modified.timestamp()
                        if isinstance(child.date_modified, datetime.datetime)
                        else child.date_modified or 0
                    ),
                    "size": child.size or 0,
                    "etag": getattr(child, "etag", None) or "",
                }
        except Exception:
            continue
    return entries


last_force_refresh = 0.0
_force_next = False
_FORCE_TIMEOUT = 60

_EXPLORE_POOL = concurrent.futures.ThreadPoolExecutor(max_workers=4)


def _explore_one(node, name):
    try:
        if getattr(node, "_children", None) is None:
            node.get_children()
        return _walk_sync(node, name)
    except Exception:
        return {}


def invalidate_remote_cache():
    global _force_next
    _force_next = True


def scan_remote(vault_node, force=False):
    global last_force_refresh, _force_next
    now = time.time()
    forced = _force_next
    _force_next = False
    do_force = force or forced or (now - last_force_refresh) > 120
    if do_force and not force and not forced and (now - last_force_refresh) < 60:
        do_force = False
    fresh = False
    if do_force:
        reason = "force" if force else ("invalidated" if forced else "timer")
        _log("INFO", f"Force-refreshing remote scan ({reason})")
        saved = getattr(vault_node, "_children", None)
        pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        try:
            fut = pool.submit(vault_node.get_children, force=True)
            fut.result(timeout=_FORCE_TIMEOUT)
            last_force_refresh = now
            fresh = True
            _log("INFO", "Remote scan force-refresh succeeded")
        except concurrent.futures.TimeoutError:
            vault_node._children = saved
            _log("WARN", f"Remote scan force-refresh timed out after {_FORCE_TIMEOUT}s — using cached data")
            last_force_refresh = now
        except Exception:
            vault_node._children = saved
            _log("WARN", "Remote scan force-refresh failed — using cached data")
            last_force_refresh = now
        finally:
            pool.shutdown(wait=False)

    entries = {}
    futs = []
    for child in vault_node._children or []:
        name = child.name
        if should_ignore(name):
            continue
        try:
            if child.type == "folder":
                futs.append(_EXPLORE_POOL.submit(_explore_one, child, name))
            else:
                entries[name] = {
                    "path": name,
                    "mtime": (
                        child.date_modified.timestamp()
                        if isinstance(child.date_modified, datetime.datetime)
                        else child.date_modified or 0
                    ),
                    "size": child.size or 0,
                    "etag": getattr(child, "etag", None) or "",
                }
        except Exception:
            continue

    for fut in concurrent.futures.as_completed(futs, timeout=180):
        try:
            entries.update(fut.result())
        except Exception:
            continue
    return entries, fresh
