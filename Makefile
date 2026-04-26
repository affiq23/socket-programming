# P2P File Sharing Makefile

.PHONY: all run clean

all:
	@echo "Type 'make tracker' to run tracker server for a multimachine final demo'
	@echo "Type 'make run' to execute automated final demo."
	@echo "Type 'make clean' to wipe generated cache/dummy files."

# run tracker for multimachine final demo
run:
	python3 tracker_server.py


# run final demo
run:
	python3 final_demo.py



# clean up to reset workspace
clean:
	rm -rf Peer* shared torrents __pycache__ peer2 sent_text.txt
