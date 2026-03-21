import socket
import sys

from rough_transfer import ProtocolError, parse_tracker_get_response

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 6000
BUFFER_SIZE = 4096


def send_msg(sock, msg):
    if not msg.endswith("\n"):
        msg += "\n"
    sock.sendall(msg.encode())


def recv_all(sock):
    buf = b""
    while True:
        chunk = sock.recv(BUFFER_SIZE)
        if not chunk:
            break
        buf += chunk
    return buf


def open_tracker(host, port):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((host, port))
    return sock


def cmd_createtracker(host, port):
    filename = input("  Filename      : ").strip()
    filesize = input("  File size     : ").strip()
    description = input("  Description   : ").strip()
    md5 = input("  MD5 hash      : ").strip()
    ip = input("  Your IP       : ").strip()
    port_in = input("  Your port     : ").strip()

    msg = f"<createtracker {filename} {filesize} {description} {md5} {ip} {port_in}>"
    sock = open_tracker(host, port)
    try:
        send_msg(sock, msg)
        print(f"  → Sent : {msg}")
        print(f"  ← Reply: {recv_all(sock).decode(errors='replace').strip()}")
    finally:
        sock.close()


def cmd_updatetracker(host, port):
    filename = input("  Filename    : ").strip()
    start_bytes = input("  Start bytes : ").strip()
    end_bytes = input("  End bytes   : ").strip()
    ip = input("  Your IP     : ").strip()
    port_in = input("  Your port   : ").strip()

    msg = f"<updatetracker {filename} {start_bytes} {end_bytes} {ip} {port_in}>"
    sock = open_tracker(host, port)
    try:
        send_msg(sock, msg)
        print(f"  → Sent : {msg}")
        print(f"  ← Reply: {recv_all(sock).decode(errors='replace').strip()}")
    finally:
        sock.close()


def cmd_list(host, port):
    sock = open_tracker(host, port)
    try:
        send_msg(sock, "<REQ LIST>")
        print("  → Sent : <REQ LIST>")
        raw = recv_all(sock).decode(errors="replace")
        lines = [ln.strip() for ln in raw.strip().splitlines() if ln.strip()]
        if not lines:
            print("  ← (empty)")
            return
        for ln in lines:
            if ln.startswith("<REP LIST") or ln == "<REP LIST END>":
                print(f"  ← {ln}")
            else:
                print(f"     {ln}")
    finally:
        sock.close()


def cmd_get(host, port):
    filename = input("  Track filename (e.g. myfile.track): ").strip()
    save_as = input("  Save received file as              : ").strip()

    msg = f"<GET {filename}>"
    sock = open_tracker(host, port)
    try:
        send_msg(sock, msg)
        print(f"  → Sent : {msg}")
        raw = recv_all(sock)
        if b"<REP GET BEGIN>" not in raw:
            print(f"  ← {raw.decode(errors='replace').strip()}")
            print("  [!] Unexpected response.")
            return
        payload = parse_tracker_get_response(raw)
        with open(save_as, "wb") as f:
            f.write(payload)
        print(f"  ✓ Saved '{save_as}' ({len(payload)} bytes)")
    except ProtocolError as e:
        print(f"  [!] {e}")
    finally:
        sock.close()


def main():
    host = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_HOST
    port = int(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_PORT

    print(f"\n  Tracker commands use a new TCP connection each time (server closes after reply).")
    print(f"  Target: {host}:{port}\n")

    MENU = """
  ┌────────────────────────────────┐
  │  Commands                      │
  │  1  createtracker              │
  │  2  updatetracker              │
  │  3  LIST                       │
  │  4  GET (download .track)      │
  │  q  Quit                       │
  └────────────────────────────────┘
  > """

    try:
        while True:
            choice = input(MENU).strip().lower()
            if choice in ("1", "createtracker"):
                cmd_createtracker(host, port)
            elif choice in ("2", "updatetracker"):
                cmd_updatetracker(host, port)
            elif choice in ("3", "list"):
                cmd_list(host, port)
            elif choice in ("4", "get"):
                cmd_get(host, port)
            elif choice in ("q", "quit", "exit"):
                print("\n  Goodbye!\n")
                break
            else:
                print("  [!] Unknown command. Try 1–4 or q.")
    except KeyboardInterrupt:
        print("\n\n  Interrupted.")


if __name__ == "__main__":
    main()
