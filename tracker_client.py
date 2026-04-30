from __future__ import annotations
import socket
from pathlib import Path

BUFFER_SIZE = 4096


def recv_all(sock: socket.socket) -> bytes:
    # keep reading until the remote side closes the connection
    # needed for multi-line responses like LIST and GET
    buf = b""
    while True:
        chunk = sock.recv(BUFFER_SIZE)
        if not chunk:
            break
        buf += chunk
    return buf


def send_tracker_command(host: str, port: int, msg: str) -> bytes:
    # open a fresh tcp connection, send one command, read the full response, close
    # each tracker command gets its own connection — tracker closes after replying
    if not msg.endswith("\n"):
        msg += "\n"
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(60)
    sock.connect((host, port))
    try:
        sock.sendall(msg.encode())
        return recv_all(sock)
    finally:
        sock.close()


def _cfg_lines(path: Path) -> list[str]:
    # read a config file and return non-empty, non-comment lines
    if not path.exists():
        return []
    return [
        ln.strip()
        for ln in path.read_text().splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]


def load_client_thread_config(path: str | Path = "clientThreadConfig.cfg"):
    # line 1: tracker port
    # line 2: tracker ip
    # line 3: updatetracker interval in seconds
    p = Path(path)
    lines = _cfg_lines(p)
    if len(lines) < 3:
        return 6000, "127.0.0.1", 900
    return int(lines[0]), lines[1], int(lines[2])


def load_server_thread_config(path: str | Path = "serverThreadConfig.cfg"):
    # line 1: port this peer listens on for incoming chunk requests
    # line 2: path to the shared folder
    p = Path(path)
    lines = _cfg_lines(p)
    if len(lines) < 2:
        return 9000, "shared"
    return int(lines[0]), lines[1]


def peer_lan_ip() -> str:
    # trick to find our outbound interface ip without knowing our own address
    # we open a udp socket toward 8.8.8.8 — no data is actually sent
    # the os picks the right interface and we read which ip it bound to
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()