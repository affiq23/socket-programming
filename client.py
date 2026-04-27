from __future__ import annotations
import os
import socket
import sys

from rough_transfer import ProtocolError, parse_tracker_get_response

from tracker_client import load_client_thread_config, recv_all


def resolve_tracker_addr():
    if len(sys.argv) >= 3:
        return sys.argv[1], int(sys.argv[2])
    t_port, t_ip, _ = load_client_thread_config()
    return t_ip, t_port


def send_msg(sock, msg):
    if not msg.endswith("\n"):
        msg += "\n"
    sock.sendall(msg.encode())


def open_tracker(host, port):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((host, port))
    return sock


def cmd_createtracker(host, port, peer_id: str):
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
        print(f"  -> sent: {msg}")
        reply = recv_all(sock).decode(errors="replace").strip()
        print(f"  <- {reply}")
        if peer_id and "succ" in reply:
            print(
                f"{peer_id}: createtracker {filename} {filesize} {description} {md5} {ip} {port_in}"
            )
    finally:
        sock.close()


def cmd_updatetracker(host, port, peer_id: str):
    filename = input("  Filename    : ").strip()
    start_bytes = input("  Start bytes : ").strip()
    end_bytes = input("  End bytes   : ").strip()
    ip = input("  Your IP     : ").strip()
    port_in = input("  Your port   : ").strip()

    msg = f"<updatetracker {filename} {start_bytes} {end_bytes} {ip} {port_in}>"
    sock = open_tracker(host, port)
    try:
        send_msg(sock, msg)
        print(f"  -> sent: {msg}")
        reply = recv_all(sock).decode(errors="replace").strip()
        print(f"  <- {reply}")
        if peer_id and "succ" in reply:
            print(f"{peer_id}: updatetracker {filename} {start_bytes} {end_bytes} {ip} {port_in}")
    finally:
        sock.close()


def cmd_list(host, port, peer_id: str):
    sock = open_tracker(host, port)
    try:
        send_msg(sock, "<REQ LIST>")
        tag = f"{peer_id}: " if peer_id else ""
        print(f"  {tag}-> <REQ LIST>")
        raw = recv_all(sock).decode(errors="replace")
        lines = [ln.strip() for ln in raw.strip().splitlines() if ln.strip()]
        if not lines:
            print("  (empty)")
            return
        for ln in lines:
            if ln.startswith("<REP LIST") or ln == "<REP LIST END>":
                print(f"  {tag}{ln}")
            else:
                print(f"     {ln}")
    finally:
        sock.close()


def cmd_get(host, port, peer_id: str):
    filename = input("  Track filename (e.g. myfile.track): ").strip()
    save_as = input("  Save received file as              : ").strip()

    track = filename if filename.endswith(".track") else f"{filename}.track"
    msg = f"<GET {track} >"
    sock = open_tracker(host, port)
    try:
        send_msg(sock, msg)
        tag = f"{peer_id}: " if peer_id else ""
        print(f"  {tag}-> {msg}")
        raw = recv_all(sock)
        if b"<REP GET BEGIN>" not in raw:
            print(f"  <- {raw.decode(errors='replace').strip()}")
            print("  bad response")
            return
        payload = parse_tracker_get_response(raw)
        with open(save_as, "wb") as f:
            f.write(payload)
        if peer_id:
            print(f"{peer_id}: Get {track}")
        print(f"  saved {save_as} ({len(payload)} bytes)")
    except ProtocolError as e:
        print(f"  err: {e}")
    finally:
        sock.close()


def run_interactive_menu(host: str, port: int, peer_id: str = "") -> None:
    print(f"\ntracker: {host}:{port} (new tcp connect per cmd)\n")

    MENU = """
  1 createtracker  2 updatetracker  3 LIST  4 GET  q quit
> """

    try:
        while True:
            choice = input(MENU).strip().lower()
            if choice in ("1", "createtracker"):
                cmd_createtracker(host, port, peer_id)
            elif choice in ("2", "updatetracker"):
                cmd_updatetracker(host, port, peer_id)
            elif choice in ("3", "list"):
                cmd_list(host, port, peer_id)
            elif choice in ("4", "get"):
                cmd_get(host, port, peer_id)
            elif choice in ("q", "quit", "exit"):
                print("bye")
                break
            else:
                print("?")
    except KeyboardInterrupt:
        print("\n^C")


def main():
    peer_id = os.environ.get("PEER_ID", "").strip()
    host, port = resolve_tracker_addr()
    run_interactive_menu(host, port, peer_id)


if __name__ == "__main__":
    main()
