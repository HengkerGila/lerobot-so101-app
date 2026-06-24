#!/usr/bin/env python
"""
Central configuration loader for the SO-101 LeRobot scripts.

Every script imports from here so that all settings live in one place:
``configs/config.yaml``.  This module reads that YAML, puts the lerobot
source checkout on ``sys.path``, and builds the typed lerobot config
objects (robot, teleoperator, dataset) that the scripts consume.

Usage from a script::

    from _config import load, build_robot_config, build_teleop_config

    cfg = load()
    robot_cfg = build_robot_config(cfg)
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml

# Repo layout:  <repo>/scripts/_config.py  ->  <repo>/configs/config.yaml
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = REPO_ROOT / "configs" / "config.yaml"


def load(path: str | Path | None = None) -> dict[str, Any]:
    """Load ``configs/config.yaml`` and put the lerobot source on ``sys.path``.

    Returns the parsed config dict.  Call this once at the top of every script
    *before* importing anything from ``lerobot``.
    """
    config_path = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    if not config_path.exists():
        raise FileNotFoundError(
            f"Config file not found at {config_path}. "
            f"Copy/edit configs/config.yaml to match your setup."
        )

    with open(config_path) as f:
        cfg = yaml.safe_load(f)

    lerobot_src = cfg.get("lerobot_src")
    if lerobot_src and lerobot_src not in sys.path:
        sys.path.insert(0, lerobot_src)

    return cfg


def lerobot_checkout_root(cfg: dict[str, Any]) -> str | None:
    """Return the LeRobot checkout root (the dir holding ``pyproject.toml``).

    Derived from ``lerobot_src`` (which points at ``<root>/src``) so that
    ``configs/config.yaml`` is the single place defining where LeRobot lives —
    used both for ``sys.path`` here and for the editable ``pip install`` that
    ``make install`` runs.
    """
    src = cfg.get("lerobot_src")
    return str(Path(src).resolve().parent) if src else None


def build_camera_configs(cfg: dict[str, Any]) -> dict[str, Any]:
    """Build ``{name: OpenCVCameraConfig}`` from the ``cameras`` section."""
    from lerobot.cameras.opencv import OpenCVCameraConfig

    cameras = cfg.get("cameras") or {}
    return {
        name: OpenCVCameraConfig(
            index_or_path=cam["index_or_path"],
            fps=cam.get("fps", 30),
            width=cam.get("width", 640),
            height=cam.get("height", 480),
        )
        for name, cam in cameras.items()
    }


def build_robot_config(cfg: dict[str, Any], with_cameras: bool = True):
    """Build the SO-101 follower ``SOFollowerRobotConfig``."""
    from lerobot.robots.so_follower.config_so_follower import SOFollowerRobotConfig

    robot = cfg.get("robot", {})
    return SOFollowerRobotConfig(
        port=cfg["ports"]["follower"],
        id=robot.get("id"),
        cameras=build_camera_configs(cfg) if with_cameras else {},
        max_relative_target=robot.get("max_relative_target"),
        use_degrees=robot.get("use_degrees", True),
    )


def build_teleop_config(cfg: dict[str, Any]):
    """Build the SO-101 leader ``SOLeaderTeleopConfig``."""
    from lerobot.teleoperators.so_leader.config_so_leader import SOLeaderTeleopConfig

    teleop = cfg.get("teleop", {})
    return SOLeaderTeleopConfig(
        port=cfg["ports"]["leader"],
        id=teleop.get("id"),
        use_degrees=teleop.get("use_degrees", True),
    )


def build_dataset_config(cfg: dict[str, Any]):
    """Build the ``DatasetRecordConfig`` from the ``record`` section."""
    from lerobot.configs.dataset import DatasetRecordConfig

    rec = cfg.get("record", {})
    return DatasetRecordConfig(
        repo_id=rec["repo_id"],
        single_task=rec["single_task"],
        root=rec.get("root"),
        fps=rec.get("fps", 30),
        episode_time_s=rec.get("episode_time_s", 60),
        reset_time_s=rec.get("reset_time_s", 10),
        num_episodes=rec.get("num_episodes", 10),
        push_to_hub=rec.get("push_to_hub", False),
        private=rec.get("private", False),
        tags=rec.get("tags"),
        streaming_encoding=rec.get("streaming_encoding", True),
        encoder_threads=rec.get("encoder_threads", 2),
    )


if __name__ == "__main__":
    # Tiny CLI used by `make install`:
    #   python scripts/_config.py lerobot-root  -> prints the checkout dir
    # so the LeRobot path is defined only in configs/config.yaml. Only needs
    # PyYAML (no lerobot import), so it runs before lerobot is installed.
    import argparse

    parser = argparse.ArgumentParser(description="Read paths from config.yaml")
    parser.add_argument("key", choices=["lerobot-root"])
    args = parser.parse_args()

    if args.key == "lerobot-root":
        root = lerobot_checkout_root(load())
        if not root:
            raise SystemExit("lerobot_src is not set in configs/config.yaml")
        print(root)
