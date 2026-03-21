# CS 4390 — P2P tracker and peer (Python)

Tracker server (`tracker_server.py`), interactive client (`client.py`), combined peer (`peer.py` with chunk server + periodic updatetracker), and P2P transfer helpers (`rough_transfer.py`).

- **Mid-term demo checklist, exact protocol strings, and two-laptop steps:** see [DEMO.md](DEMO.md).
- **Quick local test (simulates two roles on one machine):** `./simulate_two_laptops.sh` or `make test`.
- **Configs:** `sconfig.cfg` (tracker), `clientThreadConfig.cfg` and `serverThreadConfig.cfg` (peers). Copy from `*.cfg.example` files.

External reference: [Beej's Guide to Network Programming](https://beej.us/guide/bgnet/) (sockets).
