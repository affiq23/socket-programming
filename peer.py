#!/usr/bin/env python3
from __future__ import annotations

import os
import threading
import time
from pathlib import Path

from client import run_interactive_menu
from rough_transfer import start_peer_chunk_server
from tracker_client import (
    load_client_thread_config,
    load_server_thread_config,
    peer_lan_ip,
    send_tracker_command,
)


def _periodic_updatetracker(
    shared: Path,
    listen_port: int,
    track_ip: str,
    track_port: int,
    interval: int,
    peer_id: str,
) -> None:
    time.sleep(2)
    while True:
        time.sleep(interval)
        ip = peer_lan_ip()
        for fp in sorted(shared.iterdir()):
            if not fp.is_file() or fp.name.startswith("."):
                continue
            sz = fp.stat().st_size
            msg = f"<updatetracker {fp.name} 0 {sz} {ip} {listen_port}>"
            try:
                r = send_tracker_command(track_ip, track_port, msg)
                tail = r.decode(errors="replace").strip().replace("\n", " ")[:120]
                print(f"{peer_id}: [periodic updatetracker] {fp.name} -> {tail}")
            except OSError as e:
                print(f"{peer_id}: updatetracker {fp.name} failed: {e}")


def main() -> None:
    peer_id = os.environ.get("PEER_ID", "Peer").strip() or "Peer"
    listen_port, shared_dir = load_server_thread_config()
    track_port, track_ip, refresh_sec = load_client_thread_config()
    shared = Path(shared_dir)
    shared.mkdir(parents=True, exist_ok=True)

    threading.Thread(
        target=start_peer_chunk_server,
        args=("0.0.0.0", listen_port, str(shared.resolve())),
        daemon=True,
    ).start()
    time.sleep(0.4)

    threading.Thread(
        target=_periodic_updatetracker,
        args=(shared, listen_port, track_ip, track_port, refresh_sec, peer_id),
        daemon=True,
    ).start()

    print(f"{peer_id}: chunk listen 0.0.0.0:{listen_port} shared={shared.resolve()}")
    print(f"{peer_id}: tracker {track_ip}:{track_port} refresh {refresh_sec}s")
    run_interactive_menu(track_ip, track_port, peer_id)


if __name__ == "__main__":
    main()
