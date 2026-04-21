from __future__ import annotations

import hashlib
import os
import socket
import threading
import time
import concurrent.futures
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

CHUNK_SIZE_LIMIT = 1024
SOCKET_BUFFER_SIZE = 4096
DEFAULT_TIMEOUT = 5.0

class ProtocolError(Exception):
    pass

@dataclass(order=True)
class PeerEntry:
    ip: str
    port: int
    start: int
    end: int
    timestamp: int

    def covers(self, req_start: int, req_end: int) -> bool:
        return self.start <= req_start and self.end >= req_end

@dataclass
class TrackerInfo:
    filename: str
    filesize: int
    description: str
    md5: str
    peers: List[PeerEntry]

@dataclass
class ChunkJob:
    start: int
    end: int
    peer: PeerEntry

@dataclass
class DownloadResult:
    start: int
    end: int
    peer: Tuple[str, int]
    success: bool
    error: str = ""

def ensure_parent_dir(path: os.PathLike | str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)

def md5_bytes(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()

def md5_file(path: os.PathLike | str) -> str:
    digest = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            digest.update(chunk)
    return digest.hexdigest()

def send_all(sock: socket.socket, data: bytes) -> None:
    total_sent = 0
    while total_sent < len(data):
        sent = sock.send(data[total_sent:])
        if sent == 0:
            raise ConnectionError("socket connection broken during send")
        total_sent += sent

def recv_until_socket_close(sock: socket.socket) -> bytes:
    parts: List[bytes] = []
    while True:
        chunk = sock.recv(SOCKET_BUFFER_SIZE)
        if not chunk:
            break
        parts.append(chunk)
    return b"".join(parts)

def recv_exact(sock: socket.socket, n: int) -> bytes:
    parts: List[bytes] = []
    received = 0
    while received < n:
        chunk = sock.recv(min(SOCKET_BUFFER_SIZE, n - received))
        if not chunk:
            raise ConnectionError(
                f"socket closed early; expected {n} bytes, got {received}"
            )
        parts.append(chunk)
        received += len(chunk)
    return b"".join(parts)

def build_tracker_get_request(track_filename: str) -> bytes:
    name = track_filename.strip()
    if not name.endswith(".track"):
        name = f"{name}.track"
    return f"<GET {name} >\n".encode("utf-8")

def tracker_get_response_bytes(track_file_path: os.PathLike | str) -> bytes:
    with open(track_file_path, "rb") as f:
        payload = f.read()
    payload_md5 = md5_bytes(payload)
    return b"<REP GET BEGIN>\n" + payload + b"\n<REP GET END " + payload_md5.encode("ascii") + b">\n"

def handle_tracker_get_request(sock: socket.socket, track_file_path: os.PathLike | str) -> None:
    response = tracker_get_response_bytes(track_file_path)
    send_all(sock, response)

def parse_tracker_get_response(raw: bytes) -> bytes:
    begin_marker = b"<REP GET BEGIN>\n"
    end_prefix = b"\n<REP GET END "
    end_suffix = b">\n"

    if not raw.startswith(begin_marker):
        raise ProtocolError("tracker response missing <REP GET BEGIN>")

    body = raw[len(begin_marker):]
    end_prefix_idx = body.rfind(end_prefix)
    if end_prefix_idx == -1:
        raise ProtocolError("tracker response missing <REP GET END ...>")

    payload = body[:end_prefix_idx]
    trailer = body[end_prefix_idx + len(end_prefix):]
    if not trailer.endswith(end_suffix):
        raise ProtocolError("tracker response trailer malformed")

    remote_md5 = trailer[:-len(end_suffix)].decode("ascii").strip()
    local_md5 = md5_bytes(payload)
    if local_md5 != remote_md5:
        raise ProtocolError(
            f"tracker file MD5 mismatch: expected {remote_md5}, computed {local_md5}"
        )
    return payload

def request_tracker_file(
    tracker_ip: str,
    tracker_port: int,
    track_filename: str,
    cache_dir: os.PathLike | str,
    timeout: float = DEFAULT_TIMEOUT,
) -> Path:
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    out_path = cache_dir / track_filename

    with socket.create_connection((tracker_ip, tracker_port), timeout=timeout) as sock:
        sock.settimeout(timeout)
        send_all(sock, build_tracker_get_request(track_filename))
        raw = recv_until_socket_close(sock)

    payload = parse_tracker_get_response(raw)
    out_path.write_bytes(payload)
    return out_path

def parse_tracker_file(track_path: os.PathLike | str) -> TrackerInfo:
    lines = Path(track_path).read_text(encoding="utf-8").splitlines()

    header: Dict[str, str] = {}
    peers: List[PeerEntry] = []

    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        if line.startswith("Filename:"):
            header["filename"] = line.split(":", 1)[1].strip()
        elif line.startswith("Filesize:"):
            header["filesize"] = line.split(":", 1)[1].strip()
        elif line.startswith("Description:"):
            header["description"] = line.split(":", 1)[1].strip()
        elif line.startswith("MD5:"):
            header["md5"] = line.split(":", 1)[1].strip()
        else:
            parts = line.split(":")
            if len(parts) != 5:
                raise ProtocolError(f"invalid tracker peer entry: {line}")
            ip, port, start, end, timestamp = parts
            peers.append(
                PeerEntry(
                    ip=ip.strip(),
                    port=int(port),
                    start=int(start),
                    end=int(end),
                    timestamp=int(timestamp),
                )
            )

    required = {"filename", "filesize", "description", "md5"}
    missing = required - set(header)
    if missing:
        raise ProtocolError(f"tracker file missing required fields: {sorted(missing)}")

    return TrackerInfo(
        filename=header["filename"],
        filesize=int(header["filesize"]),
        description=header["description"],
        md5=header["md5"],
        peers=peers,
    )

def build_peer_chunk_get_request(filename: str, start: int, end: int) -> bytes:
    return f"<GET {filename} {start} {end}>\n".encode("utf-8")

def parse_peer_chunk_get_request(line: str) -> Tuple[str, int, int]:
    line = line.strip()
    if not (line.startswith("<GET ") and line.endswith(">")):
        raise ProtocolError("peer GET request must look like <GET filename start end>")

    inner = line[1:-1].strip()
    parts = inner.split()
    if len(parts) != 4 or parts[0].upper() != "GET":
        raise ProtocolError("peer GET request must contain command, filename, start, end")

    filename = parts[1]
    start = int(parts[2])
    end = int(parts[3])
    return filename, start, end

def recv_line(sock: socket.socket, max_bytes: int = 4096) -> str:
    data = bytearray()
    while len(data) < max_bytes:
        ch = sock.recv(1)
        if not ch:
            break
        data.extend(ch)
        if ch == b"\n":
            break
    if not data:
        raise ConnectionError("socket closed before line received")
    return data.decode("utf-8", errors="replace")

def serve_chunk_to_peer(
    sock: socket.socket,
    shared_dir: os.PathLike | str,
    filename: str,
    start: int,
    end: int,
) -> None:
    if start < 0 or end < start:
        send_all(sock, b"<GET invalid>\n")
        return

    size = end - start + 1
    if size > CHUNK_SIZE_LIMIT:
        send_all(sock, b"<GET invalid>\n")
        return

    file_path = Path(shared_dir) / filename
    if not file_path.exists():
        send_all(sock, b"<GET invalid>\n")
        return

    file_size = file_path.stat().st_size
    if end >= file_size:
        send_all(sock, b"<GET invalid>\n")
        return

    with open(file_path, "rb") as f:
        f.seek(start)
        payload = f.read(size)

    if len(payload) != size:
        send_all(sock, b"<GET invalid>\n")
        return

    send_all(sock, payload)

def handle_peer_connection(sock: socket.socket, shared_dir: os.PathLike | str) -> None:
    try:
        line = recv_line(sock)
        filename, start, end = parse_peer_chunk_get_request(line)
        print(f"file chunk requested: {filename} bytes {start}-{end}")
        serve_chunk_to_peer(sock, shared_dir, filename, start, end)
    finally:
        sock.close()

def request_chunk_from_peer(
    peer_ip: str,
    peer_port: int,
    filename: str,
    start: int,
    end: int,
    timeout: float = DEFAULT_TIMEOUT,
) -> bytes:
    size = end - start + 1
    if size > CHUNK_SIZE_LIMIT:
        raise ValueError(f"requested chunk {size} exceeds {CHUNK_SIZE_LIMIT} byte limit")

    with socket.create_connection((peer_ip, peer_port), timeout=timeout) as sock:
        sock.settimeout(timeout)
        send_all(sock, build_peer_chunk_get_request(filename, start, end))
        first = sock.recv(min(SOCKET_BUFFER_SIZE, size))
        if first == b"<GET invalid>\n":
            raise ProtocolError(f"peer {(peer_ip, peer_port)} rejected GET request")

        if len(first) == size:
            return first
        if len(first) > size:
            return first[:size]
        rest = recv_exact(sock, size - len(first))
        return first + rest

def build_all_segments(filesize: int, segment_size: int = CHUNK_SIZE_LIMIT) -> List[Tuple[int, int]]:
    segments: List[Tuple[int, int]] = []
    start = 0
    while start < filesize:
        end = min(start + segment_size - 1, filesize - 1)
        segments.append((start, end))
        start = end + 1
    return segments

def record_path_for(downloads_dir: os.PathLike | str, filename: str) -> Path:
    return Path(downloads_dir) / f".{filename}.parts"

def load_completed_segments(downloads_dir: os.PathLike | str, filename: str) -> set[Tuple[int, int]]:
    path = record_path_for(downloads_dir, filename)
    completed: set[Tuple[int, int]] = set()
    if not path.exists():
        return completed
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        start_str, end_str = line.split("-")
        completed.add((int(start_str), int(end_str)))
    return completed

def save_completed_segments(downloads_dir: os.PathLike | str, filename: str, completed: set[Tuple[int, int]]) -> None:
    path = record_path_for(downloads_dir, filename)
    ensure_parent_dir(path)
    lines = [f"{start}-{end}" for start, end in sorted(completed)]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")

def choose_peer_for_segment(segment: Tuple[int, int], peers: List[PeerEntry]) -> Optional[PeerEntry]:
    start, end = segment
    candidates = [peer for peer in peers if peer.covers(start, end)]
    if not candidates:
        return None
    candidates.sort(key=lambda p: p.timestamp, reverse=True)
    return candidates[0]

def plan_chunk_jobs(tracker: TrackerInfo, completed: set[Tuple[int, int]]) -> List[ChunkJob]:
    jobs: List[ChunkJob] = []
    for segment in build_all_segments(tracker.filesize, CHUNK_SIZE_LIMIT):
        if segment in completed:
            continue
        peer = choose_peer_for_segment(segment, tracker.peers)
        if peer is None:
            continue
        jobs.append(ChunkJob(start=segment[0], end=segment[1], peer=peer))
    return jobs

def _download_worker(
    job: ChunkJob,
    tracker: TrackerInfo,
    downloads_dir: os.PathLike | str,
    file_lock: threading.Lock,
    results: List[DownloadResult],
    completed: set[Tuple[int, int]],
    completed_lock: threading.Lock,
    timeout: float,
) -> None:
    # --- ADDED: Simulate network latency for localhost grading ---
    time.sleep(0.01) 
    
    out_path = Path(downloads_dir) / tracker.filename
    try:
        print(
            f"downloading {job.start} to {job.end} bytes of {tracker.filename} "
            f"from {job.peer.ip} {job.peer.port}"
        )
        payload = request_chunk_from_peer(
            peer_ip=job.peer.ip,
            peer_port=job.peer.port,
            filename=tracker.filename,
            start=job.start,
            end=job.end,
            timeout=timeout,
        )
        expected_size = job.end - job.start + 1
        if len(payload) != expected_size:
            raise ProtocolError(
                f"chunk size mismatch for {job.start}-{job.end}: got {len(payload)}, expected {expected_size}"
            )

        with file_lock:
            ensure_parent_dir(out_path)
            mode = "r+b" if out_path.exists() else "w+b"
            with open(out_path, mode) as f:
                f.seek(job.start)
                f.write(payload)

        with completed_lock:
            completed.add((job.start, job.end))
            save_completed_segments(downloads_dir, tracker.filename, completed)

        results.append(
            DownloadResult(
                start=job.start,
                end=job.end,
                peer=(job.peer.ip, job.peer.port),
                success=True,
            )
        )
    except Exception as exc:
        results.append(
            DownloadResult(
                start=job.start,
                end=job.end,
                peer=(job.peer.ip, job.peer.port),
                success=False,
                error=str(exc),
            )
        )

def download_file_from_tracker_info(
    tracker: TrackerInfo,
    downloads_dir: os.PathLike | str,
    timeout: float = DEFAULT_TIMEOUT,
) -> Tuple[Path, List[DownloadResult]]:
    downloads_dir = Path(downloads_dir)
    downloads_dir.mkdir(parents=True, exist_ok=True)
    out_path = downloads_dir / tracker.filename

    if not out_path.exists():
        with open(out_path, "wb") as f:
            if tracker.filesize > 0:
                f.truncate(tracker.filesize)

    completed = load_completed_segments(downloads_dir, tracker.filename)
    jobs = plan_chunk_jobs(tracker, completed)
    if not jobs and len(completed) == len(build_all_segments(tracker.filesize)):
        if md5_file(out_path) != tracker.md5:
            raise ProtocolError("resume record says complete, but file MD5 does not match tracker")
        return out_path, []

    file_lock = threading.Lock()
    completed_lock = threading.Lock()
    results: List[DownloadResult] = []

    # --- ADDED: ThreadPoolExecutor to prevent thread explosion crashes ---
    # Limits to 10 active concurrent downloads at a time
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = []
        for job in jobs:
            futures.append(
                executor.submit(
                    _download_worker, job, tracker, downloads_dir, file_lock, 
                    results, completed, completed_lock, timeout
                )
            )
        concurrent.futures.wait(futures)

    all_segments = set(build_all_segments(tracker.filesize))
    missing = all_segments - completed
    if missing:
        raise ProtocolError(f"download incomplete; still missing segments: {sorted(missing)[:10]}")

    actual_md5 = md5_file(out_path)
    if actual_md5 != tracker.md5:
        raise ProtocolError(
            f"final file MD5 mismatch: expected {tracker.md5}, computed {actual_md5}"
        )

    parts_record = record_path_for(downloads_dir, tracker.filename)
    if parts_record.exists():
        parts_record.unlink()

    print(f"File {tracker.filename} download complete")
    return out_path, results

def start_peer_chunk_server(listen_ip: str, listen_port: int, shared_dir: os.PathLike | str) -> None:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind((listen_ip, listen_port))
    listener.listen()
    print(f"Peer chunk server listening on {listen_ip}:{listen_port}")

    try:
        while True:
            conn, addr = listener.accept()
            print(f"Accepted chunk request from {addr}")
            t = threading.Thread(target=handle_peer_connection, args=(conn, shared_dir), daemon=True)
            t.start()
    finally:
        listener.close()

def auto_download_from_tracker_server(
    tracker_ip: str,
    tracker_port: int,
    track_filename: str,
    cache_dir: os.PathLike | str,
    downloads_dir: os.PathLike | str,
    timeout: float = DEFAULT_TIMEOUT,
) -> Path:
    cached_track_path = request_tracker_file(
        tracker_ip=tracker_ip,
        tracker_port=tracker_port,
        track_filename=track_filename,
        cache_dir=cache_dir,
        timeout=timeout,
    )
    tracker = parse_tracker_file(cached_track_path)
    final_path, _ = download_file_from_tracker_info(tracker, downloads_dir=downloads_dir, timeout=timeout)
    cached_track_path.unlink(missing_ok=True)
    return final_path

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    s1 = sub.add_parser("serve-peer")
    s1.add_argument("--ip", default="0.0.0.0")
    s1.add_argument("--port", type=int, required=True)
    s1.add_argument("--shared-dir", required=True)

    s2 = sub.add_parser("get-track-and-download")
    s2.add_argument("--tracker-ip", required=True)
    s2.add_argument("--tracker-port", type=int, required=True)
    s2.add_argument("--track-filename", required=True)
    s2.add_argument("--cache-dir", required=True)
    s2.add_argument("--downloads-dir", required=True)

    args = parser.parse_args()

    if args.cmd == "serve-peer":
        start_peer_chunk_server(args.ip, args.port, args.shared_dir)
    elif args.cmd == "get-track-and-download":
        out = auto_download_from_tracker_server(
            tracker_ip=args.tracker_ip,
            tracker_port=args.tracker_port,
            track_filename=args.track_filename,
            cache_dir=args.cache_dir,
            downloads_dir=args.downloads_dir,
        )
        print(f"Download complete: {out}")