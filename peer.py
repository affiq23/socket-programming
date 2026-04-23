#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
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


def _do_leecher_download(peer_id: str, track_ip: str, track_port: int,
                         filename: str, shared_dir: Path, listen_port: int) -> bool:
    """Download a single file via rough_transfer subprocess, then copy to shared dir."""
    downloads_dir = Path(f"./{peer_id}_downloads")
    cmd = [
        sys.executable, "rough_transfer.py", "get-track-and-download",
        "--tracker-ip", track_ip,
        "--tracker-port", str(track_port),
        "--track-filename", f"{filename}.track",
        "--cache-dir", f"./{peer_id}_cache",
        "--downloads-dir", str(downloads_dir),
        "--peer-listen-port", str(listen_port),
    ]
    try:
        subprocess.run(cmd, check=True)
        print(f"{peer_id}: Download complete for {filename}")
    except subprocess.CalledProcessError as e:
        print(f"{peer_id}: Download failed for {filename}: {e}")
        return False

    # Copy finished file into shared/ so this peer can seed it to later leechers
    dl_path = downloads_dir / filename
    dest = shared_dir / filename
    if dl_path.exists() and not dest.exists():
        shutil.copy2(dl_path, dest)
        print(f"{peer_id}: copied {filename} to shared for seeding")

    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="P2P Peer Node")
    parser.add_argument(
        "--mode",
        choices=["interactive", "seeder", "leecher"],
        default="interactive",
        help="Run mode for the peer",
    )
    parser.add_argument(
        "--listen-port",
        type=int,
        help="Override server listen port (required when running multiple peers on one machine)",
    )
    parser.add_argument(
        "--file",
        type=str,
        help="Comma-separated filenames to seed (seeder) or download (leecher). "
             "E.g. --file small.dat,large.dat",
    )
    args = parser.parse_args()

    peer_id = os.environ.get("PEER_ID", "Peer").strip() or "Peer"
    config_listen_port, shared_dir = load_server_thread_config()
    track_port, track_ip, refresh_sec = load_client_thread_config()

    listen_port = args.listen_port if args.listen_port else config_listen_port

    shared = Path(shared_dir)
    shared.mkdir(parents=True, exist_ok=True)

    # Start chunk server thread
    threading.Thread(
        target=start_peer_chunk_server,
        args=("0.0.0.0", listen_port, str(shared.resolve())),
        daemon=True,
    ).start()
    time.sleep(0.4)

    # Start periodic updatetracker thread
    threading.Thread(
        target=_periodic_updatetracker,
        args=(shared, listen_port, track_ip, track_port, refresh_sec, peer_id),
        daemon=True,
    ).start()

    print(f"{peer_id}: chunk listen 0.0.0.0:{listen_port} shared={shared.resolve()}")
    print(f"{peer_id}: tracker {track_ip}:{track_port} refresh {refresh_sec}s")

    # ------------------------------------------------------------------ #
    # Mode 1: Interactive
    # ------------------------------------------------------------------ #
    if args.mode == "interactive":
        run_interactive_menu(track_ip, track_port, peer_id)

    # ------------------------------------------------------------------ #
    # Mode 2: Headless Seeder
    # ------------------------------------------------------------------ #
    elif args.mode == "seeder":
        if not args.file:
            print(f"{peer_id}: Error: --file is required for seeder mode.")
            return

        for filename in args.file.split(","):
            filename = filename.strip()
            fp = shared / filename
            if not fp.exists():
                print(f"{peer_id}: Warning: {filename} not found in {shared_dir}, skipping.")
                continue
            sz = fp.stat().st_size
            md5 = hashlib.md5(fp.read_bytes()).hexdigest()
            ip = peer_lan_ip()
            msg = f"<createtracker {fp.name} {sz} auto_seeder {md5} {ip} {listen_port}>"
            try:
                r = send_tracker_command(track_ip, track_port, msg)
                reply = r.decode("utf-8").strip()
                print(f"{peer_id}: createtracker {fp.name} {sz} auto_seeder {md5} {ip} {listen_port}")
                print(f"{peer_id}: [tracker reply] {reply}")
            except Exception as e:
                print(f"{peer_id}: Failed to createtracker for {filename}: {e}")

        print(f"{peer_id}: Running in headless seeder mode. Waiting for connections...")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print(f"\n{peer_id} terminated")
            sys.exit(0)

    # ------------------------------------------------------------------ #
    # Mode 3: Headless Leecher — downloads ALL listed files sequentially,
    #          copies each into shared/, then stays alive to seed.
    # ------------------------------------------------------------------ #
    elif args.mode == "leecher":
        if not args.file:
            print(f"{peer_id}: Error: --file is required for leecher mode.")
            return

        files = [f.strip() for f in args.file.split(",") if f.strip()]

        for filename in files:
            # REQ LIST before each GET (per spec)
            print(f"{peer_id}: List")
            try:
                r = send_tracker_command(track_ip, track_port, "<REQ LIST>")
                print(f"{peer_id}: [LIST reply] {r.decode(errors='replace').strip()[:200]}")
            except Exception as e:
                print(f"{peer_id}: LIST failed: {e}")

            print(f"{peer_id}: Get {filename}.track")
            _do_leecher_download(peer_id, track_ip, track_port, filename, shared.resolve(), listen_port)

        # Keep alive so the chunk server can serve what was downloaded
        print(f"{peer_id}: All downloads done. Staying alive to seed...")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print(f"\n{peer_id} terminated")
            sys.exit(0)


if __name__ == "__main__":
    main()