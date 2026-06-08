// ── Log WebSocket ────────────────────────────────

let logSocket = null;
let logView = null;
let logBuffer = [];

function connectLogWs() {
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    logSocket = new WebSocket(`${proto}//${location.host}/ws/logs`);
    logSocket.onmessage = (e) => {
        const data = JSON.parse(e.data);
        if (data.type === "ping") return;
        appendLog(data);
    };
    logSocket.onclose = () => {
        setTimeout(connectLogWs, 2000);
    };
}

function appendLog(entry) {
    logBuffer.push(entry);
    if (logBuffer.length > 500) logBuffer.shift();

    const el = document.getElementById("logView");
    if (!el) return;

    const cls = (entry.level || "info").toLowerCase();
    const line = document.createElement("div");
    line.innerHTML = `<span class="${cls}">[${entry.timestamp}] [${entry.level}]</span> ${escapeHtml(entry.message)}`;
    el.appendChild(line);
    el.scrollTop = el.scrollHeight;
}

function clearLogView() {
    const el = document.getElementById("logView");
    if (el) el.innerHTML = "";
    logBuffer = [];
}

function escapeHtml(s) {
    const div = document.createElement("div");
    div.textContent = s;
    return div.innerHTML;
}

// ── Status WebSocket ─────────────────────────────

let statusSocket = null;

function connectStatusWs() {
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    statusSocket = new WebSocket(`${proto}//${location.host}/ws/status`);
    statusSocket.onmessage = (e) => {
        const s = JSON.parse(e.data);
        updateStatus(s);
    };
    statusSocket.onclose = () => {
        setTimeout(connectStatusWs, 2000);
    };
}

function updateStatus(s) {
    const badge = document.getElementById("statusBadge");
    if (badge) {
        if (s.paused) {
            badge.className = "status-badge paused";
            badge.textContent = "● Paused";
        } else if (s.running) {
            badge.className = "status-badge running";
            badge.textContent = "● Syncing…";
        } else {
            badge.className = "status-badge running";
            badge.textContent = "● Running";
        }
    }

    const lastSync = document.getElementById("lastSync");
    if (lastSync && s.last_sync) {
        lastSync.textContent = `Last sync: ${s.last_sync}`;
    }

    setStat("statFiles", s.files);
    setStat("statUploaded", s.uploaded);
    setStat("statDownloaded", s.downloaded);
    setStat("statConflicts", s.conflicts);
    setStat("statErrors", s.errors);
    setStat("statDeleted", s.deleted);

    const card = document.getElementById("pendingDeletionsCard");
    const countEl = document.getElementById("pendingDeletionsCount");
    const listEl = document.getElementById("pendingDeletionsList");
    if (card && countEl && listEl) {
        if (s.pending_deletions > 0) {
            card.style.display = "block";
            countEl.textContent = s.pending_deletions;
            if (s.pending_list && s.pending_list.length > 0) {
                listEl.textContent = s.pending_list.join(", ");
            }
        } else {
            card.style.display = "none";
            listEl.innerHTML = "";
        }
    }
}

function setStat(id, val) {
    const el = document.getElementById(id);
    if (el) el.textContent = val != null ? val.toLocaleString() : "—";
}

// ── Actions ──────────────────────────────────────

async function triggerSync() {
    await fetch("/api/sync", { method: "POST" });
}

function setPendingBusy(btnId, busy, label) {
    const btn = document.getElementById(btnId);
    if (!btn) return;
    const all = [document.getElementById("btnConfirmDel"), document.getElementById("btnUploadDel"), document.getElementById("btnSkipDel")];
    if (busy) {
        all.forEach(b => { if (b) b.disabled = true; });
        btn.textContent = label;
    } else {
        all.forEach(b => { if (b) b.disabled = false; });
        btn.textContent = label;
    }
}

async function confirmDeletions() {
    setPendingBusy("btnConfirmDel", true, "Confirming...");
    try {
        const r = await fetch("/api/pending-deletions/confirm", { method: "POST" });
        const data = await r.json();
        if (!data.ok) { alert("Error: " + (data.message || "unknown")); setPendingBusy("btnConfirmDel", false, "Confirm Deletions"); return; }
        triggerSync();
    } catch (e) {
        alert("Request failed: " + e.message);
    } finally {
        setPendingBusy("btnConfirmDel", false, "Confirm Deletions");
    }
}

async function cancelDeletions() {
    setPendingBusy("btnSkipDel", true, "Skipping...");
    try {
        await fetch("/api/pending-deletions/cancel", { method: "POST" });
    } catch (e) {
        alert("Request failed: " + e.message);
    } finally {
        setPendingBusy("btnSkipDel", false, "Skip this batch");
    }
}

async function uploadDeletions() {
    setPendingBusy("btnUploadDel", true, "Uploading...");
    try {
        const r = await fetch("/api/pending-deletions/upload", { method: "POST" });
        const data = await r.json();
        if (!data.ok) { alert("Error: " + (data.message || "unknown")); setPendingBusy("btnUploadDel", false, "Upload local copies back to iCloud"); return; }
        triggerSync();
    } catch (e) {
        alert("Request failed: " + e.message);
    } finally {
        setPendingBusy("btnUploadDel", false, "Upload local copies back to iCloud");
    }
}

// ── Conflicts page ───────────────────────────────

async function loadConflicts() {
    const container = document.getElementById("conflictList");
    if (!container) return;

    const resp = await fetch("/api/conflicts");
    const conflicts = await resp.json();

    if (conflicts.length === 0) {
        container.innerHTML = '<div class="card" style="color:#7ee787">No unresolved conflicts</div>';
        return;
    }

    container.innerHTML = conflicts.map((c, i) => `
        <div class="card">
            <div style="font-weight:600;margin-bottom:8px">${escapeHtml(c.path)}</div>
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;font-size:12px">
                <div>
                    <div style="color:#8b949e;margin-bottom:4px">Local (${new Date(c.local_mtime * 1000).toLocaleString()})</div>
                    <div class="preview-box">${escapeHtml(c.local_preview || "(binary)")}</div>
                </div>
                <div>
                    <div style="color:#8b949e;margin-bottom:4px">Remote (${new Date(c.remote_mtime * 1000).toLocaleString()})</div>
                    <div class="preview-box">${escapeHtml(c.remote_preview || "(binary)")}</div>
                </div>
            </div>
            <div class="conflict-actions">
                <button class="btn btn-sm" onclick="resolveConflict('${encodeURIComponent(c.path)}','local')">Keep Local</button>
                <button class="btn btn-sm" onclick="resolveConflict('${encodeURIComponent(c.path)}','remote')">Keep Remote</button>
                <button class="btn btn-sm" onclick="resolveConflict('${encodeURIComponent(c.path)}','keep-both')">Keep Both</button>
            </div>
        </div>
    `).join("");
}

async function resolveConflict(path, action) {
    await fetch(`/api/conflicts/${path}?action=${action}`, { method: "POST" });
    loadConflicts();
}

// ── Config page ──────────────────────────────────

async function saveConfig(event) {
    event.preventDefault();
    const form = event.target;
    const data = {};
    new FormData(form).forEach((v, k) => {
        if (k === "poll_interval") v = parseInt(v);
        if (k === "sync_deletes") v = v === "true";
        data[k] = v;
    });
    const resp = await fetch("/api/config", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
    });
    const result = await resp.json();
    const status = document.getElementById("configStatus");
    if (status) {
        status.textContent = result.ok ? "Saved ✓" : "Error!";
        setTimeout(() => { status.textContent = ""; }, 3000);
    }
}

// ── Init ─────────────────────────────────────────

document.addEventListener("DOMContentLoaded", () => {
    if (document.getElementById("logView")) {
        connectLogWs();
        const el = document.getElementById("logView");
        const tail = el.getAttribute("data-tail") || "50";
        fetch("/api/logs?tail=" + tail)
            .then(r => r.json())
            .then(logs => {
                const el = document.getElementById("logView");
                if (el) el.innerHTML = "";
                logs.forEach(appendLog);
            });
    }
    if (document.getElementById("statusBadge")) {
        connectStatusWs();
        fetch("/api/status")
            .then(r => r.json())
            .then(s => updateStatus(s));
    }
    if (document.getElementById("conflictList")) {
        loadConflicts();
    }
});
