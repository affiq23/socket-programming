# CS4390 P2P — Python project (no compile step; targets invoke python3).
PYTHON ?= python3

.PHONY: all tracker peer test demo-local clean

all:
	@echo "Targets:"
	@echo "  make tracker    - run tracker_server.py (needs sconfig.cfg in cwd)"
	@echo "  make peer       - run peer.py (needs clientThreadConfig.cfg + serverThreadConfig.cfg)"
	@echo "  make client     - run client.py (tracker menu only)"
	@echo "  make test       - integration test + local two-role simulation"
	@echo "  make demo-local - same as ./simulate_two_laptops.sh"

tracker:
	$(PYTHON) tracker_server.py

peer:
	$(PYTHON) peer.py

client:
	$(PYTHON) client.py

test:
	$(PYTHON) test_integration.py
	./simulate_two_laptops.sh

demo-local:
	./simulate_two_laptops.sh

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
