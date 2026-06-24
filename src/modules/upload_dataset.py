#!/usr/bin/env python
"""
Upload a locally-saved LeRobot dataset to the HuggingFace Hub.

By default it reads the dataset location (``record.root``) and target
(``record.repo_id``, ``record.tags``, ``record.private``) from
configs/config.yaml. Override any of them with command-line flags.

Usage:
    # Use the values from configs/config.yaml
    python scripts/upload_dataset.py

    # Override the local dir and repo id
    python scripts/upload_dataset.py \
        --local_dir /path/to/data/my_dataset \
        --repo_id your_hf_username/so101_demo

Requires (run once):
    huggingface-cli login
"""

import argparse
import logging

from cfg import _config

cfg = _config.load()  # loads YAML and puts lerobot on sys.path

from lerobot.datasets import LeRobotDataset
from lerobot.utils.utils import init_logging


def main():
    rec = cfg.get("record", {})

    parser = argparse.ArgumentParser(description="Upload a local LeRobot dataset to the Hub")
    parser.add_argument("--local_dir", default=rec.get("root"),
                        help="Path to the local dataset (default: record.root from config)")
    parser.add_argument("--repo_id", default=rec.get("repo_id"),
                        help="HuggingFace repo id (default: record.repo_id from config)")
    parser.add_argument("--private", action="store_true", default=rec.get("private", False),
                        help="Upload as a private repository")
    parser.add_argument("--tags", nargs="*", default=rec.get("tags"),
                        help="Optional tags to attach on the Hub")
    args = parser.parse_args()

    if not args.local_dir:
        raise SystemExit("No local dataset dir given. Set record.root in config or pass --local_dir.")
    if not args.repo_id:
        raise SystemExit("No repo id given. Set record.repo_id in config or pass --repo_id.")

    init_logging()
    logging.info(f"Loading dataset from {args.local_dir}")
    dataset = LeRobotDataset(repo_id=args.repo_id, root=args.local_dir)

    logging.info(f"Pushing {dataset.num_episodes} episodes to {args.repo_id}")
    dataset.push_to_hub(tags=args.tags, private=args.private)
    logging.info("Upload complete.")


if __name__ == "__main__":
    main()
