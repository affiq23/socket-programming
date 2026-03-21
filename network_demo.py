#!/usr/bin/env python3
"""Hints for Phase 2 demo: two laptops on LAN (not localhost)."""

import argparse
import socket
import subprocess
import sys


def guess_lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def main():
    p = argparse.ArgumentParser(description="Print LAN IP and demo commands.")
    p.add_argument("--port", type=int, default=6000, help="Tracker port (match sconfig.cfg)")
    args = p.parse_args()
    ip = guess_lan_ip()
    print("Suggested LAN IP (UDP route trick):", ip)
    print("On SERVER laptop: bind tracker to 0.0.0.0 (tracker_server.py already uses '').")
    print("On CLIENT laptop:  python3 client.py <SERVER_IP>", args.port)
    print("Firewall: allow inbound TCP", args.port, "on the server.")
    if sys.platform == "darwin":
        print("macOS: System Settings → Network → Firewall, or `sudo /usr/libexec/ApplicationFirewall/socketfilterfw` …")
    try:
        out = subprocess.check_output(["ifconfig"], text=True, stderr=subprocess.DEVNULL)
        if "inet " in out:
            print("\n--- ifconfig (inet) ---")
            for line in out.splitlines():
                if "inet " in line and "127.0.0.1" not in line:
                    print(line.strip())
    except (FileNotFoundError, subprocess.CalledProcessError):
        pass


if __name__ == "__main__":
    main()
