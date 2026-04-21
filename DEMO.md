# Mid-term demo checklist (CS 4390 project spec)

This repo matches the **mid-term demo** requirements in the course PDF: two-machine operation, multithreading, manual tracker commands, GET with MD5 verification, and P2P chunks (max 1024 bytes).

## What the spec requires (demo)

| Requirement | How this repo satisfies it |
|---------------|----------------------------|
| Connection between **two machines** and file download | Tracker on one host; peer chunk server + shared file on another; leecher runs `client.py` or `rough_transfer get-track-and-download`. |
| **Multithreaded** implementation | `tracker_server.py`: thread per connection. `rough_transfer.py`: one thread per segment download; peer chunk server: thread per incoming GET. |
| Manual **createtracker** / **updatetracker** / **LIST** / **GET** | Use `client.py` or `peer.py` menu, or type the exact `<...>\n` strings (see protocol below). |
| GET response **MD5** check | `parse_tracker_get_response()` verifies payload vs `<REP GET END FileMD5>`. |
| Chunk size **≤ 1024** | Enforced in `serve_chunk_to_peer` / `request_chunk_from_peer`. |

### Exact protocol strings (for TA manual testing)

Use a **single line** ending with `\n`. Angle brackets are part of the message.

1. **createtracker**  
   `<createtracker filename filesize description md5 ip-address port-number>\n`  
   Success: `<createtracker succ>\n`

2. **updatetracker**  
   `<updatetracker filename start_bytes end_bytes ip-address port-number>\n`  
   Success: `<updatetracker filename succ>\n`

3. **LIST**  
   `<REQ LIST>\n`  
   Reply: `<REP LIST X>\n` then `<1 name size md5>\n` … `<REP LIST END>\n`

4. **GET** (tracker file)  
   `<GET filename.track >\n` (space before `>`)  
   Reply: `<REP GET BEGIN>\n` … `<REP GET END FileMD5>\n`

### Configuration files (per spec)

- **`sconfig.cfg`** — tracker: port, `torrents_dir`, peer timeout (seconds).  
- **`clientThreadConfig.cfg`** — line 1: tracker **port**, line 2: tracker **IP**, line 3: **updatetracker** interval (seconds). Default **900** = 15 minutes.  
- **`serverThreadConfig.cfg`** — line 1: this peer’s **listen** port for chunk GETs, line 2: **shared** folder path.

Copy the examples and edit:

```bash
cp clientThreadConfig.cfg.example clientThreadConfig.cfg
cp serverThreadConfig.cfg.example serverThreadConfig.cfg
```

---

## A. Local “two laptops” simulation (one computer)

Runs an isolated tracker, a seeder peer, and a leecher download; verifies the file byte-for-byte.

```bash
chmod +x simulate_two_laptops.sh
./simulate_two_laptops.sh
# or: make test
```

---

## B. Real two-laptop test (intended setup)

Assume **Laptop T** = tracker only, **Laptop P** = peer (seeder + menu), **Laptop L** = leecher (optional: P and L can be the same machine if you use different terminals and ports).

### 1. Network

- Same LAN (Wi‑Fi or Ethernet).  
- **Disable** VPN for testing or allow LAN traffic.  
- On **Laptop T**, note the **LAN IPv4** (e.g. macOS: System Settings → Network → Wi‑Fi → Details; or run `python3 network_demo.py`).

### 2. Laptop T — tracker

```bash
cd /path/to/socket-programming
# Edit sconfig.cfg: port = 6000 (or any free port), torrents_dir = torrents
python3 tracker_server.py
```

Firewall: allow **inbound TCP** on the tracker port (e.g. macOS Firewall, Windows Defender, `ufw` on Linux).

### 3. Laptop P — seeder peer

1. Create a folder with the **complete** file to share (e.g. `shared/myfile.dat`).  
2. Compute MD5: `md5 shared/myfile.dat` (macOS) or `md5sum shared/myfile.dat` (Linux).  
3. Configure:

**`serverThreadConfig.cfg`** (on P):

```text
9000
shared
```

**`clientThreadConfig.cfg`** (on P):

```text
6000
<TRACKER_LAN_IP>
900
```

Replace `<TRACKER_LAN_IP>` with Laptop T’s address (not `127.0.0.1`).

4. Start the combined peer (chunk server + menu + periodic updatetracker):

```bash
export PEER_ID=Peer1
python3 peer.py
```

5. In the menu, run **createtracker** with: filename, **byte size**, short description (use underscores instead of spaces if needed), **MD5**, **P’s LAN IP**, and **9000** (listen port).  
6. Leave `peer.py` running so others can download chunks.

### 4. Laptop L — leecher

**`clientThreadConfig.cfg`** on L:

```text
6000
<TRACKER_LAN_IP>
900
```

```bash
export PEER_ID=Peer2
python3 client.py
```

1. **LIST** — confirm `myfile.dat` appears.  
2. **GET** `myfile.dat.track` — saves the tracker file locally.  
3. Download the **payload** from peers using `rough_transfer` (same as `simulate_two_laptops.sh`):

```bash
python3 rough_transfer.py get-track-and-download \
  --tracker-ip <TRACKER_LAN_IP> \
  --tracker-port 6000 \
  --track-filename myfile.dat.track \
  --cache-dir ./leech_cache \
  --downloads-dir ./leech_dl
```

You should see segment lines like `downloading 0 to 1023 bytes of myfile.dat from <P_IP> 9000` and finally `File myfile.dat download complete`.

### 5. Verification

- Compare MD5 of the original on P and the file under `leech_dl` on L.  
- Tracker `.track` files live on **T** under `torrents/` (see `sconfig.cfg`).

---

## Troubleshooting

| Symptom | Things to check |
|--------|------------------|
| Connection refused | Tracker not running, wrong IP/port, firewall blocking TCP. |
| createtracker ferr | Tracker already has that `.track`; use another filename or delete `torrents/<name>.track` on T (only for demos). |
| GET invalid | Wrong `filename.track` spelling; file must exist on tracker. |
| P2P stalls / invalid chunk | Seeder not running; wrong listen port in createtracker; **advertised IP** must be reachable from L (use LAN IP, not 127.0.0.1 on another machine). |
| Description with spaces | Tracker splits on whitespace; use underscores in description for reliability. |

---

## Report screenshots (mid-term)

Capture: tracker terminal, peer terminal showing **createtracker** + chunk server, leecher showing **LIST** / **GET** / download progress, and two different hostnames or IPs visible.
