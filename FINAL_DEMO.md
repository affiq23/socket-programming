# CS 4390 – P2P File Sharing Project Documentation

---

## Component Overview

### `tracker_server.py`
The centralized tracker. Listens on a TCP port (default 6000, read from `sconfig.cfg`) and spawns a new daemon thread for every incoming peer connection. Each thread handles exactly one request then closes the connection.

**Commands handled:**
- `createtracker` — Creates a new `.track` file in `torrents/` if it doesn't already exist. Stores filename, filesize, description, MD5, and the seeder's IP/port/byte range/timestamp.
- `updatetracker` — Updates an existing `.track` file with new byte range info for a peer. Merges overlapping/adjacent intervals for the same IP:port so a peer's coverage is accurately represented as it downloads more of a file. Purges dead peers (those whose last timestamp exceeds `peer_timeout_seconds`).
- `REQ LIST` — Returns a formatted list of all `.track` files currently on the server including filename, filesize, and MD5.
- `GET <filename.track>` — Returns the full contents of a specific `.track` file along with an MD5 checksum of the response for integrity verification.

**Config:** `sconfig.cfg` — port, torrents directory path, peer timeout in seconds.

---

### `tracker_client.py`
Utility module shared by `peer.py`, `client.py`, and `rough_transfer.py`. Not a standalone program.

**Functions:**
- `send_tracker_command(host, port, msg)` — Opens a TCP connection, sends a message, reads the full response, closes the socket. Used everywhere a peer needs to talk to the tracker.
- `recv_all(sock)` — Reads from a socket until it closes. Used to collect complete multi-line responses.
- `load_client_thread_config()` — Reads `clientThreadConfig.cfg`: tracker port (line 1), tracker IP (line 2), updatetracker interval in seconds (line 3).
- `load_server_thread_config()` — Reads `serverThreadConfig.cfg`: this peer's chunk-server listen port (line 1), shared folder path (line 2).
- `peer_lan_ip()` — Detects this machine's LAN IP by opening a UDP socket toward 8.8.8.8 and reading which interface it uses.

---

### `rough_transfer.py`
The core file transfer engine. Handles everything below the tracker protocol level — actually fetching chunks from peers and serving chunks to other peers.

**Key functions:**

- `start_peer_chunk_server(ip, port, shared_dir)` — Starts a TCP listener that accepts connections from other peers requesting file chunks. Each connection is handed to a daemon thread.
- `serve_chunk_to_peer(sock, shared_dir, filename, start, end)` — Validates a chunk request (size ≤ 1024 bytes, file exists, byte range valid) and sends the raw bytes. Returns `<GET invalid>` on any violation.
- `request_chunk_from_peer(peer_ip, peer_port, filename, start, end)` — Connects to another peer's chunk server and requests a specific byte range.
- `parse_tracker_file(track_path)` — Parses a `.track` file into a `TrackerInfo` object containing filename, filesize, MD5, and a list of `PeerEntry` objects.
- `plan_chunk_jobs(tracker, completed)` — Splits the file into 1024-byte segments, skips already-completed ones, and assigns each remaining segment to the best available peer (newest timestamp).
- `download_file_from_tracker_info(tracker, downloads_dir, ...)` — Runs up to 10 rounds of parallel chunk downloads using a `ThreadPoolExecutor` with 10 workers. Maintains a `bad_peers` blacklist so dead peers are skipped instantly on subsequent rounds. After each successful chunk, sends an `updatetracker` to the tracker so this peer becomes visible to later downloaders.
- `auto_download_from_tracker_server(...)` — The top-level download function. Fetches the `.track` file from the tracker, parses it, downloads the file, and retries up to 5 times (re-fetching the tracker each time) if a round completes with missing segments due to stale peer info.
- `build_all_segments(filesize)` — Divides a file into a list of `(start, end)` tuples of at most 1024 bytes each.
- `load_completed_segments / save_completed_segments` — Persists download progress to a hidden `.filename.parts` file so an interrupted download can be resumed from where it left off.

**Protocol (peer-to-peer chunk GET):**
```
Request:  <GET filename start end>\n
Response: <raw bytes>  (or <GET invalid>\n on error)
```

---

### `peer.py`
The main peer process. Launched once per peer, reads config files, and runs in one of three modes.

**Startup (all modes):**
1. Reads `serverThreadConfig.cfg` and `clientThreadConfig.cfg`.
2. Starts the chunk server thread (`start_peer_chunk_server`) so this peer can serve chunks to others immediately.
3. Starts the periodic `updatetracker` thread, which wakes every N seconds and sends an `updatetracker` message for each file in the shared folder.

**Modes:**
- `--mode interactive` — Launches the manual command menu from `client.py`. Used for manual TA testing of `createtracker`, `updatetracker`, `LIST`, and `GET` commands.
- `--mode seeder` — Headless. Reads `--file`, computes MD5, sends `createtracker` to the tracker for each file, then loops forever waiting for chunk requests.
- `--mode leecher` — Headless. For each file in `--file`: sends `REQ LIST`, sends `GET <filename.track>`, then calls `rough_transfer.py get-track-and-download` as a subprocess. After download, copies the file into `shared/` so this peer can seed it to subsequent leechers. Then loops forever.

**Config files:**
- `clientThreadConfig.cfg` — tracker port, tracker IP, updatetracker interval
- `serverThreadConfig.cfg` — this peer's chunk listen port, shared folder path

---

### `client.py`
Interactive menu for manually issuing tracker commands. Used by `peer.py --mode interactive` and useful for TA-driven manual testing.

**Menu options:**
1. `createtracker` — prompts for all fields and sends the message
2. `updatetracker` — prompts for filename, byte range, IP, port
3. `LIST` — sends `<REQ LIST>` and prints the response
4. `GET` — sends `<GET filename.track >` and saves the received `.track` file locally

Each command opens a fresh TCP connection, sends the message, reads the response, and closes. The `PEER_ID` environment variable is prepended to output lines for identification.

---

### `final_demo.py`
Automation script for the final demo. Manages all process lifecycles and timing.

**Timeline:**
- `T=0s` — Wipes `torrents/`, writes config files, generates `small.dat` and `large.dat`, starts tracker, starts Peer1 (small.dat seeder) and Peer2 (large.dat seeder).
- `T=30s` — Launches Peers 3–8 as leechers downloading both files.
- `T=90s` — Terminates Peer1 and Peer2. Launches Peers 9–13 as leechers downloading both files (from wave 1 peers, since original seeders are gone).
- `Ctrl+C` — Sends SIGINT to all processes in reverse launch order, waits up to 2 seconds each, kills any that don't respond.

---

### Config Files

| File | Used by | Contents |
|---|---|---|
| `sconfig.cfg` | `tracker_server.py` | port, torrents_dir, peer_timeout_seconds |
| `clientThreadConfig.cfg` | `peer.py`, `client.py` | tracker port, tracker IP, updatetracker interval (seconds) |
| `serverThreadConfig.cfg` | `peer.py` | this peer's chunk listen port, shared folder name |

---
