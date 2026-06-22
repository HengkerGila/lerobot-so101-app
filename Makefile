# SO-101 LeRobot — convenience shortcuts.
# Run `make` or `make help` to see all targets. Everything uses the local .venv,
# so you never need to activate it or remember script paths.

PY := .venv/bin/python

.DEFAULT_GOAL := help

.PHONY: help install find port-leader port-follower cameras \
        calibrate-leader calibrate-follower teleop record upload \
        monitor app server

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

# --- setup -------------------------------------------------------------------
install:  ## Create .venv and install dependencies
	python -m venv .venv && $(PY) -m pip install -r requirements.txt

find:  ## List detected serial ports and cameras (no changes)
	$(PY) scripts/find_hardware.py

port-leader:  ## Detect the leader port (unplug/replug) and save it
	$(PY) scripts/find_hardware.py --detect-port leader --write

port-follower:  ## Detect the follower port (unplug/replug) and save it
	$(PY) scripts/find_hardware.py --detect-port follower --write

cameras:  ## Detect cameras and save them to the config
	$(PY) scripts/find_hardware.py --write-cameras

calibrate-leader:  ## Calibrate the leader arm
	$(PY) scripts/calibrate.py --device leader

calibrate-follower:  ## Calibrate the follower arm
	$(PY) scripts/calibrate.py --device follower

# --- run ---------------------------------------------------------------------
teleop:  ## Teleoperate (leader drives follower)
	$(PY) scripts/teleop.py

record:  ## Record a dataset (set record.* in config first)
	$(PY) scripts/record.py

upload:  ## Push a local dataset to the HuggingFace Hub
	$(PY) scripts/upload_dataset.py

# --- watch / control in the browser (http://localhost:8000) ------------------
monitor:  ## Standalone dashboard (run when nothing else owns the arm)
	$(PY) scripts/monitor.py

server:  ## Session server: owns the arm, controllable from the app
	$(PY) scripts/session_server.py

app:  ## The application UI (pair with `make server` in another terminal)
	$(PY) scripts/app.py
