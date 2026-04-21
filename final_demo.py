#!/usr/bin/env python3
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

def create_demo_files():
    """Generates the test files and forces the 5-second tracker config."""
    print("[*] Setting up demo environment...")
    Path("shared").mkdir(exist_ok=True)
    
    # Force tracker updates to 5 seconds so Wave 1 tells the tracker they are seeders
    with open("clientThreadConfig.cfg", "w") as f:
        f.write("6000\n127.0.0.1\n5\n")
    with open("serverThreadConfig.cfg", "w") as f:
        f.write("9000\nshared\n")
    
    # Small file (5 KB)
    small_path = Path("shared/small.dat")
    if not small_path.exists():
        small_path.write_bytes(os.urandom(1024 * 5))
        
    # Large file (50 MB)
    large_path = Path("shared/large.dat")
    if not large_path.exists():
        print("[*] Generating 50MB large.dat (this takes a few seconds)...")
        large_path.write_bytes(os.urandom(1024 * 1024 * 50))

def launch_peer(peer_id, mode, filename, port):
    """Helper to launch a peer process with the correct environment variables."""
    env = os.environ.copy()
    env["PEER_ID"] = peer_id
    cmd = [
        sys.executable, "peer.py", 
        "--mode", mode, 
        "--file", filename, 
        "--listen-port", str(port)
    ]
    return subprocess.Popen(cmd, env=env)

def main():
    create_demo_files()
    active_processes = []

    print("\n" + "="*50)
    print("P2P demo starting...")
    print("="*50 + "\n")

    # --- T = 0 SECONDS ---
    print("[T=0s] Starting Tracker Server on port 6000...")
    tracker = subprocess.Popen([sys.executable, "tracker_server.py"])
    active_processes.append(tracker)
    time.sleep(2) 
    
    print("[T=0s] Starting Seeder1 (small.dat) and Seeder2 (large.dat)...")
    s1 = launch_peer("Seeder1", "seeder", "small.dat", 9001)
    s2 = launch_peer("Seeder2", "seeder", "large.dat", 9002)
    active_processes.extend([s1, s2])

    # --- T = 30 SECONDS ---
    print("\nWaiting 30 seconds before launching first wave of leechers...\n")
    time.sleep(30)
    
    print("[T=30s] Starting 5 Leechers to download large.dat...")
    for i in range(5):
        port = 9010 + i
        p = launch_peer(f"Leecher_Wave1_{i+1}", "leecher", "large.dat", port)
        active_processes.append(p)

    # --- T = 1 MINUTE 45 SECONDS (Wait 75s) ---
    print("\nWaiting 75 seconds for Wave 1 to finish and report to tracker...\n")
    time.sleep(75)

    print("[T=1m45s] Terminating original seeders (Demonstrating P2P swarm resilience)...")
    s1.send_signal(signal.SIGINT)
    s2.send_signal(signal.SIGINT)
    time.sleep(2) # Give the sockets a second to cleanly detach
    
    print("[T=1m45s] Starting 5 MORE Leechers...")
    for i in range(5):
        port = 9020 + i
        target_file = "small.dat" if i % 2 == 0 else "large.dat"
        p = launch_peer(f"Leecher_Wave2_{i+1}", "leecher", target_file, port)
        active_processes.append(p)

    print("\nAll demo stages triggered! The swarm is fully self-sustaining.")
    print("Press Ctrl+C to terminate the entire simulation when ready.\n")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n\nShutting down all nodes and cleaning up...")
        for p in active_processes:
            try:
                p.send_signal(signal.SIGINT)
                p.wait(timeout=2)
            except:
                p.kill() 
        print("Demo complete!")

if __name__ == "__main__":
    main()