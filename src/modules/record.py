#!/usr/bin/env python
"""
Record teleoperated demonstrations from the SO-101 arm pair.

All settings come from configs/config.yaml — edit that file, not this script.

Usage:
    python scripts/record.py

Keyboard shortcuts during recording:
    Right arrow  — save episode and start the next one early
    Left arrow   — discard the current episode and re-record it
    Escape       — stop recording (saves whatever was completed)
"""

import logging

from cfg import _config

cfg = _config.load()  # loads YAML and puts lerobot on sys.path

from lerobot.scripts.lerobot_record import RecordConfig, record
from lerobot.utils.import_utils import register_third_party_plugins
from lerobot.utils.utils import init_logging


def main():
    register_third_party_plugins()
    init_logging()

    rec = cfg.get("record", {})

    record_cfg = RecordConfig(
        robot=_config.build_robot_config(cfg),
        teleop=_config.build_teleop_config(cfg),
        dataset=_config.build_dataset_config(cfg),
        display_data=rec.get("display_data", False),
        play_sounds=rec.get("play_sounds", True),
    )

    logging.info(
        f"Recording {record_cfg.dataset.num_episodes} episodes × "
        f"{record_cfg.dataset.episode_time_s}s → {record_cfg.dataset.repo_id}"
    )
    record(record_cfg)

if __name__ == "__main__":
    main()
