PYTHON ?= python3

.PHONY: all tracker peer client test demo-local clean

all:
	@echo "make tracker | make peer | make client | make test"

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
