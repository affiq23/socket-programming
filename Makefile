# P2P File Sharing Makefile

.PHONY: all run clean

all:
	@echo "Type 'make run' to execute automated final demo."
	@echo "Type 'make clean' to wipe generated cache/dummy files."

# run final demo
run:
	python3 final_demo.py

# clean up to reset workspace
clean:
	rm -rf Peer* shared torrents __pycache__ peer2 sent_text.txt