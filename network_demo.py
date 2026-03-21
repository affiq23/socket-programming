#!/usr/bin/env python3
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
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=6000)
    args = p.parse_args()
    ip = guess_lan_ip()
    print("lan ip guess:", ip)
    print("server: python3 tracker_server.py   client: python3 client.py", ip, args.port)
    print("open tcp", args.port, "if firewall blocks")
    if sys.platform == "darwin":
        print("(mac firewall in system settings)")
    try:
        out = subprocess.check_output(["ifconfig"], text=True, stderr=subprocess.DEVNULL)
        if "inet " in out:
            for line in out.splitlines():
                if "inet " in line and "127.0.0.1" not in line:
                    print(line.strip())
    except (FileNotFoundError, subprocess.CalledProcessError):
        pass


if __name__ == "__main__":
    main()
