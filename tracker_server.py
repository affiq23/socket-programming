import configparser
import hashlib
import os
import socket
import threading
import time

config = configparser.ConfigParser()
config.read("sconfig.cfg")

PORT = int(config.get("server", "port", fallback="5000"))
TORRENTS_DIR = config.get("server", "torrents_dir", fallback="torrents")
PEER_TIMEOUT = int(config.get("server", "peer_timeout_seconds", fallback="900"))

os.makedirs(TORRENTS_DIR, exist_ok=True)
file_lock = threading.Lock()


def md5_of_string(data: str) -> str:
    return hashlib.md5(data.encode()).hexdigest()


def track_path(filename: str) -> str:
    base = filename.replace(".track", "")
    return os.path.join(TORRENTS_DIR, base + ".track")


def read_track_file(filepath: str):
    if not os.path.exists(filepath):
        return None, None

    header = {}
    peers = []

    with open(filepath, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if ":" in line and line[0].isdigit():
                parts = line.split(":")
                if len(parts) == 5:
                    peers.append(
                        {
                            "ip": parts[0],
                            "port": parts[1],
                            "start": parts[2],
                            "end": parts[3],
                            "timestamp": int(parts[4]),
                        }
                    )
            elif line.startswith("Filename:"):
                header["Filename"] = line.split(":", 1)[1].strip()
            elif line.startswith("Filesize:"):
                header["Filesize"] = line.split(":", 1)[1].strip()
            elif line.startswith("Description:"):
                header["Description"] = line.split(":", 1)[1].strip()
            elif line.startswith("MD5:"):
                header["MD5"] = line.split(":", 1)[1].strip()

    return header, peers


def write_track_file(filepath: str, header: dict, peers: list):
    with open(filepath, "w") as f:
        f.write(f"Filename: {header['Filename']}\n")
        f.write(f"Filesize: {header['Filesize']}\n")
        f.write(f"Description: {header.get('Description', '')}\n")
        f.write(f"MD5: {header['MD5']}\n")
        f.write("#list of peers follows next\n")
        for p in peers:
            f.write(f"{p['ip']}:{p['port']}:{p['start']}:{p['end']}:{p['timestamp']}\n")


def purge_dead_peers(peers: list) -> list:
    now = int(time.time())
    return [p for p in peers if (now - p["timestamp"]) <= PEER_TIMEOUT]


def handle_createtracker(parts: list) -> str:
    if len(parts) != 7:
        print("[createtracker] Bad argument count")
        return "<createtracker fail>\n"

    _, filename, filesize, description, md5, ip, port = parts
    path = track_path(filename)

    with file_lock:
        if os.path.exists(path):
            print(f"[createtracker] File already exists: {path}")
            return "<createtracker ferr>\n"

        header = {
            "Filename": filename,
            "Filesize": filesize,
            "Description": description,
            "MD5": md5,
        }
        peer = {
            "ip": ip,
            "port": port,
            "start": "0",
            "end": filesize,
            "timestamp": int(time.time()),
        }
        write_track_file(path, header, [peer])

    print(f"[createtracker] Created {path}")
    return "<createtracker succ>\n"


def handle_updatetracker(parts: list) -> str:
    if len(parts) != 6:
        print("[updatetracker] Bad argument count")
        return f"<updatetracker {parts[1] if len(parts) > 1 else '?'} fail>\n"

    _, filename, start, end, ip, port = parts
    path = track_path(filename)

    with file_lock:
        header, peers = read_track_file(path)
        if header is None:
            # Only print error if it's an actual error, not a successful update
            # print(f"[updatetracker] Track file not found: {path}")
            return f"<updatetracker {filename} ferr>\n"

        peers = purge_dead_peers(peers)
        now = int(time.time())

        # --- BUG 2 FIX: Merge overlapping/adjacent chunks instead of overwriting ---
        intervals = []
        for p in peers:
            if p["ip"] == ip and p["port"] == port:
                intervals.append([int(p["start"]), int(p["end"])])
        
        intervals.append([int(start), int(end)])
        
        intervals.sort(key=lambda x: x[0])
        merged_intervals = []
        for interval in intervals:
            if not merged_intervals or merged_intervals[-1][1] < interval[0] - 1:
                merged_intervals.append(interval)
            else:
                merged_intervals[-1][1] = max(merged_intervals[-1][1], interval[1])
        
        peers = [p for p in peers if not (p["ip"] == ip and p["port"] == port)]
        
        for mi in merged_intervals:
            peers.append({
                "ip": ip,
                "port": port,
                "start": str(mi[0]),
                "end": str(mi[1]),
                "timestamp": now
            })

        write_track_file(path, header, peers)

    # --- Muted to prevent terminal spam ---
    # print(f"[updatetracker] Updated {path} for {ip}:{port}")
    return f"<updatetracker {filename} succ>\n"


def handle_list() -> str:
    track_files = [f for f in os.listdir(TORRENTS_DIR) if f.endswith(".track")]
    count = len(track_files)
    response = f"<REP LIST {count}>\n"

    for i, fname in enumerate(sorted(track_files), start=1):
        path = os.path.join(TORRENTS_DIR, fname)
        header, _ = read_track_file(path)
        if header:
            display_name = header.get("Filename", fname.replace(".track", ""))
            filesize = header.get("Filesize", "0")
            md5 = header.get("MD5", "")
            response += f"<{i} {display_name} {filesize} {md5}>\n"

    response += "<REP LIST END>\n"
    print(f"[LIST] Sending list of {count} files")
    return response


def handle_get(parts: list) -> str:
    if len(parts) != 2:
        print("[GET] Bad argument count")
        return "<GET invalid>\n"

    requested = parts[1]
    path = track_path(requested)

    if not os.path.exists(path):
        print(f"[GET] Track file not found: {path}")
        return "<GET invalid>\n"

    with open(path, "r") as f:
        content = f.read()

    file_md5 = md5_of_string(content)
    response = f"<REP GET BEGIN>\n{content}\n<REP GET END {file_md5}>\n"
    print(f"[GET] Sending {path}")
    return response


def handle_client(conn, addr):
    # --- Muted connection logs for less terminal spam ---
    # print(f"[+] Connection from {addr}")
    try:
        data = b""
        while True:
            chunk = conn.recv(1024)
            if not chunk:
                break
            data += chunk
            if b"\n" in data:
                break

        raw = data.decode(errors="ignore").strip()
        
        # --- Add this check so we stop flooding the terminal! ---
        if not raw.startswith("<updatetracker"):
            print(f"[>] Received: {raw}")

        parts = []
        # --- BUG 3 FIX: Strict check for the exact GET format requested by the spec ---
        if raw.startswith("<GET ") and raw.endswith(" >"):
            filename = raw[5:-2].strip()
            parts = ["get", filename]
            
        elif raw.startswith("<") and raw.endswith(">"):
            inner_raw = raw[1:-1].strip()
            parts = inner_raw.split()
        else:
            parts = raw.split()

        if not parts:
            conn.sendall(b"<error>\n")
            return

        cmd = parts[0].lower()

        if cmd == "createtracker":
            response = handle_createtracker(parts)
        elif cmd == "updatetracker":
            response = handle_updatetracker(parts)
        elif parts[0] == "REQ" and len(parts) > 1 and parts[1] == "LIST":
            response = handle_list()
        elif cmd == "get":
            response = handle_get(parts)
        else:
            print(f"[!] Unknown command: {cmd}")
            response = "<error unknown command>\n"

        conn.sendall(response.encode())
        
        if not raw.startswith("<updatetracker"):
            print(f"[<] Sent response for '{cmd}'")

    except Exception as e:
        print(f"[!] Error handling {addr}: {e}")
    finally:
        conn.close()
        # print(f"[-] Closed connection from {addr}")


def main():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("", PORT))
    server.listen(10)
    print(f"[*] Tracker server listening on port {PORT}")
    print(f"[*] Storing .track files in: {os.path.abspath(TORRENTS_DIR)}")

    while True:
        conn, addr = server.accept()
        t = threading.Thread(target=handle_client, args=(conn, addr), daemon=True)
        t.start()


if __name__ == "__main__":
    main() 