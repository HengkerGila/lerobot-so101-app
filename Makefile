# SO-101 LeRobot — convenience shortcuts.
# Run `make` or `make help` to see all targets. Everything uses the local .venv,
# so you never need to activate it or remember script paths.

.DEFAULT_GOAL := help

.PHONY: help install find port-leader port-follower cameras \
        calibrate-leader calibrate-follower teleop record upload \
        monitor app server

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

# --- setup -------------------------------------------------------------------
install:  ## Create .venv and install dependencies using setup.sh (Usage: make install ENV=uv or ENV=pip)
	./scripts/setup.sh $(ENV)

find:  ## List detected serial ports and cameras
	./scripts/find.sh

port-leader:  ## Detect the leader port (unplug/replug) and save it
	./scripts/port-leader.sh

port-follower:  ## Detect the follower port (unplug/replug) and save it
	./scripts/port-follower.sh

cameras:  ## Detect cameras and save them to the config
	./scripts/cameras.sh

calibrate-leader:  ## Calibrate the leader arm
	./scripts/calibrate-leader.sh

calibrate-follower:  ## Calibrate the follower arm
	./scripts/calibrate-follower.sh

# --- run ---------------------------------------------------------------------
teleop:  ## Teleoperate (leader drives follower)
	./scripts/teleop.sh

record:  ## Record a dataset (set record.* in config first)
	./scripts/record.sh

upload:  ## Push a local dataset to the HuggingFace Hub
	./scripts/upload.sh

# --- watch / control in the browser (http://localhost:8000) ------------------
monitor:  ## Standalone dashboard (run when nothing else owns the arm)
	./scripts/monitor.sh

server:  ## Session server: owns the arm, controllable from the app
	./scripts/server.sh

app:  ## The application UI (pair with `make server` in another terminal)
	./scripts/app.sh
