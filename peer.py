#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
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
    parser = argparse.ArgumentParser(description="P2P Peer Node")
    parser.add_argument("--mode", choices=["interactive", "seeder", "leecher"], default="interactive", help="Run mode for the peer")
    parser.add_argument("--listen-port", type=int, help="Override server listen port to avoid collisions")
    parser.add_argument("--file", type=str, help="Filename to seed (seeder mode) or download (leecher mode)")
    args = parser.parse_args()

    peer_id = os.environ.get("PEER_ID", "Peer").strip() or "Peer"
    config_listen_port, shared_dir = load_server_thread_config()
    track_port, track_ip, refresh_sec = load_client_thread_config()
    
    # override port if provided (crucial for running 13 peers on one machine)
    listen_port = args.listen_port if args.listen_port else config_listen_port
    
    shared = Path(shared_dir)
    shared.mkdir(parents=True, exist_ok=True)

    # start chunk server
    threading.Thread(
        target=start_peer_chunk_server,
        args=("0.0.0.0", listen_port, str(shared.resolve())),
        daemon=True,
    ).start()
    time.sleep(0.4)

    # start periodic update tracker
    threading.Thread(
        target=_periodic_updatetracker,
        args=(shared, listen_port, track_ip, track_port, refresh_sec, peer_id),
        daemon=True,
    ).start()

    print(f"{peer_id}: chunk listen 0.0.0.0:{listen_port} shared={shared.resolve()}")
    print(f"{peer_id}: tracker {track_ip}:{track_port} refresh {refresh_sec}s")

    # Mode 1: Standard Interactive 
    if args.mode == "interactive":
        run_interactive_menu(track_ip, track_port, peer_id)
        
    # Mode 2: Headless Seeder
    elif args.mode == "seeder":
        if not args.file:
            print(f"{peer_id}: Error: --file is required for seeder mode.")
            return
            
        fp = shared / args.file
        if fp.exists():
            sz = fp.stat().st_size
            md5 = hashlib.md5(fp.read_bytes()).hexdigest()
            msg = f"<createtracker {fp.name} {sz} auto_seeder {md5} {peer_lan_ip()} {listen_port}>"
            try:
                r = send_tracker_command(track_ip, track_port, msg)
                print(f"{peer_id}: [auto createtracker] {r.decode('utf-8').strip()}")
            except Exception as e:
                print(f"{peer_id}: Failed to auto-create tracker: {e}")
        else:
            print(f"{peer_id}: Error: {args.file} not found in {shared_dir}")
            
        print(f"{peer_id}: Running in headless seeder mode. Waiting for connections...")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print(f"\n{peer_id} terminated")
            sys.exit(0)

    # Mode 3: Headless Leecher
    elif args.mode == "leecher":
        if not args.file:
            print(f"{peer_id}: Error: --file is required for leecher mode.")
            return
            
        print(f"{peer_id}: [leecher auto] starting download for {args.file}")
        
        # call rough_transfer silently to handle the download logic
        cmd = [
            sys.executable, "rough_transfer.py", "get-track-and-download",
            "--tracker-ip", track_ip,
            "--tracker-port", str(track_port),
            "--track-filename", f"{args.file}.track",
            "--cache-dir", f"./{peer_id}_cache",
            "--downloads-dir", str(shared.resolve()) # saves directly to shared so it can seed it
        ]
        try:
            subprocess.run(cmd, check=True)
            print(f"{peer_id}: Download complete for {args.file}")
        except subprocess.CalledProcessError as e:
            print(f"{peer_id}: Download failed: {e}")
            
        # keep alive so it seeds the file it just downloaded to other leechers
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print(f"\n{peer_id} terminated")
            sys.exit(0)

if __name__ == "__main__":
    main()