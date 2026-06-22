#!/usr/bin/env python
"""
Calibrate the SO-101 leader or follower arm.

Ports and ids come from configs/config.yaml. Calibrate the leader first,
then the follower. Follow the on-screen prompts to move the arm through
its full range of motion.

Usage:
    python scripts/calibrate.py --device leader
    python scripts/calibrate.py --device follower
"""

import argparse
import logging

import _config

cfg = _config.load()  # loads YAML and puts lerobot on sys.path

from lerobot.utils.import_utils import register_third_party_plugins
from lerobot.utils.utils import init_logging


def main():
    parser = argparse.ArgumentParser(description="Calibrate an SO-101 arm")
    parser.add_argument(
        "--device",
        choices=["leader", "follower"],
        required=True,
        help="Which arm to calibrate",
    )
    args = parser.parse_args()

    register_third_party_plugins()
    init_logging()

    if args.device == "leader":
        from lerobot.teleoperators import make_teleoperator_from_config

        logging.info(f"Calibrating leader arm on {cfg['ports']['leader']}")
        device = make_teleoperator_from_config(_config.build_teleop_config(cfg))
    else:
        from lerobot.robots import make_robot_from_config

        logging.info(f"Calibrating follower arm on {cfg['ports']['follower']}")
        # Cameras aren't needed for calibration.
        device = make_robot_from_config(_config.build_robot_config(cfg, with_cameras=False))

    device.connect(calibrate=False)
    device.calibrate()
    device.disconnect()
    logging.info("Calibration complete.")


if __name__ == "__main__":
    main()
