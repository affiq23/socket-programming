"""
app.py — FastAPI web layer for the P2P file transfer engine.
Drop this file into your SOCKET-PROGRAMMING directory alongside peer.py.

Run: python -m uvicorn app:app --host 0.0.0.0 --port 8080
Then open: http://localhost:8080
"""

import asyncio
import hashlib
import os
import shutil
import threading
import time
from pathlib import Path
from typing import AsyncGenerator

import uvicorn
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

# ── Import your existing engine modules ──────────────────────────────────────
import tracker_client
import rough_transfer

# ── App setup ────────────────────────────────────────────────────────────────
app = FastAPI(title="P2P Transfer")

# ── Config (loaded once at startup) ──────────────────────────────────────────
client_cfg = tracker_client.load_client_thread_config()   # (tracker_port, tracker_ip, update_interval)
server_cfg = tracker_client.load_server_thread_config()   # (chunk_port, shared_dir)

TRACKER_PORT   = int(client_cfg[0])
TRACKER_IP     = client_cfg[1].strip()
UPDATE_INTERVAL = int(client_cfg[2])
CHUNK_PORT     = int(server_cfg[0])
SHARED_DIR     = server_cfg[1].strip()
DOWNLOADS_DIR  = "downloads"
MY_IP          = tracker_client.peer_lan_ip()

os.makedirs(SHARED_DIR, exist_ok=True)
os.makedirs(DOWNLOADS_DIR, exist_ok=True)

# ── Progress tracking (shared across threads) ─────────────────────────────────
# { filename: { "total": int, "done": int, "status": "downloading"|"done"|"error" } }
_progress: dict[str, dict] = {}
_progress_lock = threading.Lock()


def _update_progress(filename: str, done: int, total: int):
    with _progress_lock:
        _progress[filename] = {
            "total": total,
            "done": done,
            "status": "done" if done >= total else "downloading",
        }


# ── Startup: launch chunk server + periodic updatetracker ────────────────────
@app.on_event("startup")
def startup():
    # Chunk server — serves file pieces to other peers
    threading.Thread(
        target=rough_transfer.start_peer_chunk_server,
        args=(MY_IP, CHUNK_PORT, SHARED_DIR),
        daemon=True,
    ).start()
    print(f"[P2P] Chunk server listening on {MY_IP}:{CHUNK_PORT}")

    # Periodic updatetracker — keeps this peer visible on the tracker
    threading.Thread(target=_updatetracker_loop, daemon=True).start()
    print(f"[P2P] Tracker at {TRACKER_IP}:{TRACKER_PORT} | update every {UPDATE_INTERVAL}s")


def _updatetracker_loop():
    while True:
        time.sleep(UPDATE_INTERVAL)
        for fname in os.listdir(SHARED_DIR):
            fpath = os.path.join(SHARED_DIR, fname)
            if not os.path.isfile(fpath):
                continue
            size = os.path.getsize(fpath)
            msg = (
                f"updatetracker {fname} {size} {MY_IP} {CHUNK_PORT} "
                f"0 {size - 1} {int(time.time())}"
            )
            try:
                tracker_client.send_tracker_command(TRACKER_IP, TRACKER_PORT, msg)
            except Exception:
                pass


# ── Routes ───────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def index():
    html_path = Path(__file__).parent / "static" / "index.html"
    return HTMLResponse(content=html_path.read_text())


@app.get("/api/info")
def get_info():
    """Return this peer's IP and chunk port so the UI can display them."""
    return {"ip": MY_IP, "chunk_port": CHUNK_PORT, "tracker_ip": TRACKER_IP}


@app.post("/api/send")
async def send_file(file: UploadFile = File(...)):
    """
    Accept a file upload, move it into shared/, compute MD5,
    and register it on the tracker via createtracker.
    """
    dest = os.path.join(SHARED_DIR, file.filename)

    # Write upload to shared dir
    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)

    size = os.path.getsize(dest)

    # Compute MD5
    md5 = hashlib.md5()
    with open(dest, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            md5.update(chunk)
    md5_hex = md5.hexdigest()

    # Register on tracker
    msg = (
        f"createtracker {file.filename} {size} \"uploaded via web\" "
        f"{md5_hex} {MY_IP} {CHUNK_PORT} 0 {size - 1} {int(time.time())}"
    )
    try:
        resp = tracker_client.send_tracker_command(TRACKER_IP, TRACKER_PORT, msg)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Tracker unreachable: {e}")

    if "error" in resp.lower():
        raise HTTPException(status_code=400, detail=resp.strip())

    return {
        "filename": file.filename,
        "size": size,
        "md5": md5_hex,
        "your_ip": MY_IP,
        "chunk_port": CHUNK_PORT,
        "tracker_msg": resp.strip(),
    }


@app.get("/api/files")
def list_files():
    """Fetch the list of available files from the tracker."""
    try:
        resp = tracker_client.send_tracker_command(TRACKER_IP, TRACKER_PORT, "REQ LIST")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Tracker unreachable: {e}")
    return {"raw": resp, "tracker_ip": TRACKER_IP}


class ReceiveRequest(BaseModel):
    filename: str   # e.g. "large.dat"


@app.post("/api/receive")
def receive_file(req: ReceiveRequest):
    """
    Kick off a background download for the given filename.
    Poll /api/progress/{filename} (or use SSE) for live updates.
    """
    fname = req.filename
    track_name = fname if fname.endswith(".track") else fname + ".track"

    with _progress_lock:
        if fname in _progress and _progress[fname]["status"] == "downloading":
            return {"status": "already_downloading"}
        _progress[fname] = {"total": 1, "done": 0, "status": "downloading"}

    def _run():
        try:
            rough_transfer.auto_download_from_tracker_server(
                tracker_ip=TRACKER_IP,
                tracker_port=TRACKER_PORT,
                track_filename=track_name,
                downloads_dir=DOWNLOADS_DIR,
                my_ip=MY_IP,
                my_port=CHUNK_PORT,
                progress_callback=lambda done, total: _update_progress(fname, done, total),
            )
            # Seed the file after download
            dest = os.path.join(SHARED_DIR, fname)
            src = os.path.join(DOWNLOADS_DIR, fname)
            if os.path.exists(src) and not os.path.exists(dest):
                shutil.copy2(src, dest)
            with _progress_lock:
                if fname in _progress:
                    _progress[fname]["status"] = "done"
        except Exception as e:
            with _progress_lock:
                _progress[fname] = {"total": 1, "done": 0, "status": "error", "error": str(e)}

    threading.Thread(target=_run, daemon=True).start()
    return {"status": "started", "filename": fname}


@app.get("/api/progress/{filename}")
def get_progress(filename: str):
    """Snapshot of current download progress."""
    with _progress_lock:
        p = _progress.get(filename)
    if not p:
        return {"status": "not_started"}
    pct = int((p["done"] / p["total"]) * 100) if p["total"] > 0 else 0
    return {**p, "percent": pct}


@app.get("/api/progress-stream/{filename}")
async def progress_stream(filename: str):
    """
    SSE endpoint — browser subscribes and receives live progress events
    until the download completes or errors out.
    """
    async def _generate() -> AsyncGenerator[dict, None]:
        while True:
            with _progress_lock:
                p = _progress.get(filename, {"total": 1, "done": 0, "status": "waiting"})
            pct = int((p["done"] / p["total"]) * 100) if p["total"] > 0 else 0
            yield {"data": f'{{"percent": {pct}, "status": "{p["status"]}"}}'}
            if p["status"] in ("done", "error"):
                break
            await asyncio.sleep(0.5)

    return EventSourceResponse(_generate())

# ── Dynamic Config Route ─────────────────────────────────────────────────────

class ConfigUpdate(BaseModel):
    tracker_ip: str

@app.post("/api/config")
def update_config(config: ConfigUpdate):
    """Overwrites the tracker IP inside the client configuration file."""
    try:
        with open("clientThreadConfig.cfg", "r") as f:
            lines = f.readlines()
            
        if len(lines) >= 2:
            lines[1] = f"{config.tracker_ip}\n"
        else:
            raise HTTPException(status_code=500, detail="Invalid config file format. Cannot find IP line.")
            
        with open("clientThreadConfig.cfg", "w") as f:
            f.writelines(lines)
            
        return {"status": "success", "message": "Configuration saved"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=8080, reload=False)