#!/usr/bin/env python3
"""Integration test: tracker_server + protocol (no second physical machine)."""

import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PORT = 6000


def recv_all(sock):
    buf = b""
    while True:
        chunk = sock.recv(4096)
        if not chunk:
            break
        buf += chunk
    return buf


def send_cmd(msg: str) -> bytes:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(5.0)
    s.connect(("127.0.0.1", PORT))
    try:
        if not msg.endswith("\n"):
            msg += "\n"
        s.sendall(msg.encode())
        return recv_all(s)
    finally:
        s.close()


def main():
    srv = None
    os.chdir(ROOT)
    env = os.environ.copy()
    tmp = tempfile.mkdtemp(prefix="torrents_test_")
    cfg = ROOT / "sconfig.cfg"
    bak = None
    if cfg.exists():
        bak = cfg.read_text()
    try:
        cfg.write_text(
            f"[server]\nport = {PORT}\ntorrents_dir = {tmp}\npeer_timeout_seconds = 900\n"
        )

        srv = subprocess.Popen(
            [sys.executable, str(ROOT / "tracker_server.py")],
            cwd=str(ROOT),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        time.sleep(0.4)
        if srv is not None and srv.poll() is not None:
            err = srv.stderr.read().decode() if srv.stderr else ""
            print("Server failed:", err)
            return 1

        name = "demo.txt"
        r = send_cmd(
            f"<createtracker {name} 100 desc1 deadbeef1111111111111111111111 192.168.1.5 4000>"
        )
        assert b"<createtracker succ>" in r, r

        r = send_cmd("<REQ LIST>")
        text = r.decode()
        assert "<REP LIST 1>" in text and "<REP LIST END>" in text, text

        r = send_cmd(f"<GET {name}.track>")
        assert b"<REP GET BEGIN>" in r and b"<REP GET END " in r, r

        from rough_transfer import parse_tracker_get_response

        payload = parse_tracker_get_response(r)
        assert b"Filename: demo.txt" in payload

        r = send_cmd(
            f"<updatetracker {name} 0 50 10.0.0.2 5000>"
        )
        assert b"<updatetracker demo.txt succ>" in r, r

        print("integration OK")
        return 0
    finally:
        if srv is not None and srv.poll() is None:
            srv.send_signal(signal.SIGTERM)
            try:
                srv.wait(timeout=2)
            except subprocess.TimeoutExpired:
                srv.kill()
        if bak is not None:
            cfg.write_text(bak)
        elif cfg.exists():
            cfg.unlink()
        import shutil

        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
