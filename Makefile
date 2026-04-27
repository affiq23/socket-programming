# P2P File Sharing Makefile

.PHONY: all tracker peer run clean test

all:
	@echo "Usage:"
	@echo "  make tracker  - Run the tracker server"
	@echo "  make peer     - Run a peer in interactive mode"
	@echo "  make run      - Run the full automated final demo"
	@echo "  make test     - Run integration tests"
	@echo "  make clean    - Wipe generated cache/dummy files"

# Run tracker server (reads port/dir from sconfig.cfg)
tracker:
	python3 tracker_server.py

# Run a peer in interactive mode (reads config from clientThreadConfig.cfg / serverThreadConfig.cfg)
peer:
	python3 peer.py --mode interactive

# Run full automated final demo
run:
	python3 final_demo.py

# Run integration tests
test:
	python3 test_integration.py

# Clean up to reset workspace
clean:
	rm -rf Peer* shared torrents __pycache__ peer2 sent_text.txt *.parts