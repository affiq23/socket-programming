#!/usr/bin/env bash
# Local "two laptop" demo: tracker + seeder peer + leecher download (same host, two roles).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

# Random defaults avoid collisions with leftover local processes from earlier runs.
TRACKER_PORT="${TRACKER_PORT:-$((6000 + RANDOM % 800))}"
SEEDER_PORT="${SEEDER_PORT:-$((9000 + RANDOM % 800))}"
PY="${PYTHON:-python3}"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/p2p_demo.XXXXXX")"
TORRENTS="$WORK/torrents"
SEED_DIR="$WORK/laptop_a_shared"
LEECH_CACHE="$WORK/laptop_b_track_cache"
LEECH_DL="$WORK/laptop_b_downloads"
CFG="$WORK/sconfig.cfg"
TEST_FILE="$SEED_DIR/demo.bin"
FILENAME="demo.bin"
TRACK_NAME="${FILENAME}.track"

cleanup() {
  [[ -n "${PEER_PID:-}" ]] && kill "$PEER_PID" 2>/dev/null || true
  [[ -n "${TRACKER_PID:-}" ]] && kill "$TRACKER_PID" 2>/dev/null || true
  [[ -n "${PEER_PID:-}" ]] && wait "$PEER_PID" 2>/dev/null || true
  [[ -n "${TRACKER_PID:-}" ]] && wait "$TRACKER_PID" 2>/dev/null || true
  rm -rf "$WORK"
}
trap cleanup EXIT

wait_port() {
  local p="$1" label="$2"
  for _ in $(seq 1 40); do
    if "$PY" -c "import socket; s=socket.socket(); s.settimeout(0.15); s.connect(('127.0.0.1',$p)); s.close()" 2>/dev/null; then
      return 0
    fi
    sleep 0.1
  done
  echo "timeout waiting for $label on port $p"
  return 1
}

mkdir -p "$TORRENTS" "$SEED_DIR" "$LEECH_CACHE" "$LEECH_DL"

# ~1.5 chunks (1024-byte segments) so two P2P segment requests run
dd if=/dev/urandom of="$TEST_FILE" bs=1536 count=1 2>/dev/null

FILESIZE=$(wc -c <"$TEST_FILE" | tr -d ' ')
FILE_MD5=$("$PY" -c "import hashlib,sys; print(hashlib.md5(open(sys.argv[1],'rb').read()).hexdigest())" "$TEST_FILE")

cat >"$CFG" <<EOF
[server]
port = $TRACKER_PORT
torrents_dir = $TORRENTS
peer_timeout_seconds = 900
EOF

echo "=== Paths ==="
echo "Work dir:     $WORK"
echo "Tracker port: $TRACKER_PORT  |  Seeder (laptop A) peer port: $SEEDER_PORT"
echo ""

echo "=== [Laptop A] starting peer chunk server (shares $TEST_FILE) ==="
"$PY" "$ROOT/rough_transfer.py" serve-peer --ip 127.0.0.1 --port "$SEEDER_PORT" --shared-dir "$SEED_DIR" \
  >>"$WORK/peer.log" 2>&1 &
PEER_PID=$!
wait_port "$SEEDER_PORT" "peer" || exit 1

echo "=== [Tracker] starting tracker server (cwd uses isolated sconfig) ==="
(
  cd "$WORK"
  "$PY" "$ROOT/tracker_server.py" >>"$WORK/tracker.log" 2>&1
) &
TRACKER_PID=$!
wait_port "$TRACKER_PORT" "tracker" || exit 1
if ! kill -0 "$TRACKER_PID" 2>/dev/null; then
  echo "tracker process exited (often port already in use). Log:"
  cat "$WORK/tracker.log" 2>/dev/null || true
  exit 1
fi

send_tracker() {
  export TRACKER_MSG="$1"
  "$PY" - <<'PY'
import os
import socket

msg = os.environ["TRACKER_MSG"]
port = int(os.environ["TRACKER_PORT"])
if not msg.endswith("\n"):
    msg += "\n"
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.settimeout(10)
s.connect(("127.0.0.1", port))
s.sendall(msg.encode())
data = b""
while True:
    b = s.recv(65536)
    if not b:
        break
    data += b
s.close()
os.write(1, data)
PY
}

echo "=== [Laptop A] createtracker (register file + this peer as seeder) ==="
export TRACKER_PORT
REPLY=$(send_tracker "<createtracker $FILENAME $FILESIZE simdemo $FILE_MD5 127.0.0.1 $SEEDER_PORT>")
printf '%s' "$REPLY"
echo ""
echo "$REPLY" | grep -q "createtracker succ" || { echo "createtracker failed"; exit 1; }

echo ""
echo "=== [Any] REQ LIST ==="
REPLY=$(send_tracker "<REQ LIST>")
printf '%s' "$REPLY"
echo ""

LAST=$((FILESIZE - 1))
echo ""
echo "=== [Laptop A] updatetracker (peer range 0–$LAST) ==="
REPLY=$(send_tracker "<updatetracker $FILENAME 0 $LAST 127.0.0.1 $SEEDER_PORT>")
printf '%s' "$REPLY"
echo ""
echo "$REPLY" | grep -q "updatetracker $FILENAME succ" || { echo "updatetracker failed"; exit 1; }

echo ""
echo "=== [Laptop B] GET tracker file + P2P download (separate dirs = separate machine) ==="
"$PY" "$ROOT/rough_transfer.py" get-track-and-download \
  --tracker-ip 127.0.0.1 \
  --tracker-port "$TRACKER_PORT" \
  --track-filename "$TRACK_NAME" \
  --cache-dir "$LEECH_CACHE" \
  --downloads-dir "$LEECH_DL"

OUT="$LEECH_DL/$FILENAME"
echo ""
echo "=== Verify downloaded file ==="
if cmp -s "$TEST_FILE" "$OUT"; then
  echo "OK: $OUT matches laptop A copy ($FILESIZE bytes, md5 $FILE_MD5)"
else
  echo "FAIL: bytes differ"
  exit 1
fi

echo ""
echo "=== Optional: direct peer chunk GET (first 64 bytes) ==="
"$PY" - <<PY
import socket
from rough_transfer import build_peer_chunk_get_request, recv_exact

sock = socket.create_connection(("127.0.0.1", $SEEDER_PORT), timeout=5)
sock.sendall(build_peer_chunk_get_request("$FILENAME", 0, 63))
data = recv_exact(sock, 64)
sock.close()
open("$WORK/direct_chunk.bin", "wb").write(data)
PY
cmp -s <(head -c 64 "$TEST_FILE") "$WORK/direct_chunk.bin"
echo "OK: direct chunk matches first 64 bytes of seed file"

echo ""
echo "Done. (Logs: $WORK/tracker.log $WORK/peer.log)"
