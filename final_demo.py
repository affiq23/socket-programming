#!/usr/bin/env python3
"""
CS 4390 – Final Demo Automation Script

Timeline (per spec):
  T=0s      : Start tracker + Peer1 (small.dat seeder) + Peer2 (large.dat seeder)
  T=30s     : Start Peers 3-8  (6 leechers, download BOTH files)
  T=1m30s   : Start Peers 9-13 (5 leechers, download BOTH files)
              AND terminate Peer1 + Peer2
"""

import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

# ------------------------------------------------------------------ #
# Config
# ------------------------------------------------------------------ #
TRACKER_PORT    = 6000
SEEDER1_PORT    = 9001   # Peer1 – small.dat
SEEDER2_PORT    = 9002   # Peer2 – large.dat
WAVE1_BASE_PORT = 9010   # Peers 3-8  (6 peers)
WAVE2_BASE_PORT = 9020   # Peers 9-13 (5 peers)

SMALL_FILE = "small.dat"
LARGE_FILE = "large.dat"

SMALL_SIZE_BYTES = 1024 * 5              # 5 KB
LARGE_SIZE_BYTES = 1024 * 1024 * 10     # 10 MB

# Per-chunk sleep injected into leecher workers via CHUNK_SLEEP env var.
# With 10MB (10240 chunks) and 10 parallel workers:
#   Each worker sleeps 0.08s per chunk -> ~82s for the full file download.
# Adjust this knob to meet the ">= 1 min 20 sec" requirement.
CHUNK_SLEEP = 0.08


# ------------------------------------------------------------------ #
# Setup
# ------------------------------------------------------------------ #
def create_demo_files():
    if Path("torrents").exists():  # wipe old tracker files if any
        shutil.rmtree("torrents")
    Path("torrents").mkdir()

    # Clean up leftover peer directories from previous runs
    import glob
    for d in glob.glob("Peer*_downloads") + glob.glob("Peer*_cache"):
        shutil.rmtree(d, ignore_errors=True)

    print("[*] Setting up demo environment...")
    Path("shared").mkdir(exist_ok=True)

    # 5-second refresh so Wave 1 leechers report back as seeders in time for Wave 2
    with open("clientThreadConfig.cfg", "w") as f:
        f.write(f"{TRACKER_PORT}\n127.0.0.1\n5\n")
    with open("serverThreadConfig.cfg", "w") as f:
        f.write("9000\nshared\n")

    small_path = Path(f"shared/{SMALL_FILE}")
    if not small_path.exists():
        small_path.write_bytes(os.urandom(SMALL_SIZE_BYTES))
        print(f"[*] Created {SMALL_FILE} ({SMALL_SIZE_BYTES} bytes)")

    large_path = Path(f"shared/{LARGE_FILE}")
    if not large_path.exists():
        print(f"[*] Generating {LARGE_FILE} ({LARGE_SIZE_BYTES // (1024*1024)} MB) ...")
        large_path.write_bytes(os.urandom(LARGE_SIZE_BYTES))
        print(f"[*] {LARGE_FILE} ready.")


# ------------------------------------------------------------------ #
# Process helpers
# ------------------------------------------------------------------ #
def launch_peer(peer_id: str, mode: str, files: str, port: int) -> subprocess.Popen:
    """
    files: comma-separated filenames, e.g. "small.dat,large.dat"
    """
    env = os.environ.copy()
    env["PEER_ID"] = peer_id
    # Only inject sleep for leechers (seeders serve chunks, don't need delay)
    if mode == "leecher":
        env["CHUNK_SLEEP"] = str(CHUNK_SLEEP)
    cmd = [
        sys.executable, "peer.py",
        "--mode", mode,
        "--file", files,
        "--listen-port", str(port),
    ]
    return subprocess.Popen(cmd, env=env)


def wait_for_tracker(port: int, retries: int = 20, delay: float = 0.5):
    import socket
    for _ in range(retries):
        try:
            s = socket.create_connection(("127.0.0.1", port), timeout=1)
            s.close()
            return True
        except OSError:
            time.sleep(delay)
    return False


def terminate(proc: subprocess.Popen, label: str):
    try:
        proc.send_signal(signal.SIGINT)
        proc.wait(timeout=3)
    except Exception:
        proc.kill()
    


# ------------------------------------------------------------------ #
# Main
# ------------------------------------------------------------------ #
def main():
    create_demo_files()
    active_processes: list[subprocess.Popen] = []
    t_start = time.time()

    def elapsed():
        return time.time() - t_start

    print("\n" + "=" * 55)
    print("  CS 4390 – P2P File Sharing Final Demo")
    print("=" * 55 + "\n")

    # ---- T = 0s --------------------------------------------------- #
    print(f"[T={elapsed():.0f}s] Starting Tracker Server on port {TRACKER_PORT}...")
    tracker = subprocess.Popen([sys.executable, "tracker_server.py"])
    active_processes.append(tracker)

    if not wait_for_tracker(TRACKER_PORT):
        print("ERROR: tracker did not come up in time.")
        sys.exit(1)
    print(f"[T={elapsed():.0f}s] Tracker is up.")

    print(f"[T={elapsed():.0f}s] Starting Peer1 ({SMALL_FILE} seeder) on port {SEEDER1_PORT}...")
    p1 = launch_peer("Peer1", "seeder", SMALL_FILE, SEEDER1_PORT)
    active_processes.append(p1)
    time.sleep(1)  # let seeder register with tracker before wave 1

    print(f"[T={elapsed():.0f}s] Starting Peer2 ({LARGE_FILE} seeder) on port {SEEDER2_PORT}...")
    p2 = launch_peer("Peer2", "seeder", LARGE_FILE, SEEDER2_PORT)
    active_processes.append(p2)
    time.sleep(1)

    # ---- T = 30s -------------------------------------------------- #
    remaining = 30 - elapsed()
    if remaining > 0:
        print(f"\n[*] Waiting {remaining:.0f}s before Wave 1...\n")
        time.sleep(remaining)

    print(f"[T={elapsed():.0f}s] Starting Peers 3-8 (6 leechers, downloading both files)...")
    wave1 = []
    for i in range(6):                              # peers 3-8
        peer_id = f"Peer{3 + i}"
        port = WAVE1_BASE_PORT + i
        p = launch_peer(peer_id, "leecher", f"{SMALL_FILE},{LARGE_FILE}", port)
        active_processes.append(p)
        wave1.append(p)
        print(f"  launched {peer_id} on port {port}")

    # ---- T = 1m30s ------------------------------------------------ #
    remaining = 90 - elapsed()
    if remaining > 0:
        print(f"\n[*] Waiting {remaining:.0f}s for Wave 1 to download + seed...\n")
        time.sleep(remaining)

    print(f"[T={elapsed():.0f}s] Terminating Peer1 and Peer2 (original seeders)...")
    terminate(p1, "Peer1")
    terminate(p2, "Peer2")

    print(f"[T={elapsed():.0f}s] Starting Peers 9-13 (5 leechers, downloading both files)...")
    for i in range(5):                              
        peer_id = f"Peer{9 + i}"
        port = WAVE2_BASE_PORT + i
        p = launch_peer(peer_id, "leecher", f"{SMALL_FILE},{LARGE_FILE}", port)
        active_processes.append(p)
        print(f"  launched {peer_id} on port {port}")

    # ---- Hold ----------------------------------------------------- #
    print(f"\n[T={elapsed():.0f}s] All stages triggered. Swarm is running.")
    print("Press Ctrl+C to shut everything down when done.\n")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n\n[*] Shutting down all nodes...")
        for p in reversed(active_processes):
            try:
                p.send_signal(signal.SIGINT)
                p.wait(timeout=2)
            except Exception:
                p.kill()
        print("[*] Demo complete.")


if __name__ == "__main__":
    main()