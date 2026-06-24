#!/usr/bin/env python
"""
Auto-detect SO-101 serial ports and USB cameras.

This is the "automation" front-end for configs/config.yaml: it discovers
your hardware and (optionally) writes the discovered values straight back
into the config file so the other scripts pick them up.

Usage:
    # List detected ports and cameras (does not modify anything)
    python scripts/find_hardware.py

    # Detect cameras and write them into configs/config.yaml
    python scripts/find_hardware.py --write-cameras

    # Interactively detect a single arm's port (unplug/replug method) and save
    python scripts/find_hardware.py --detect-port leader --write
    python scripts/find_hardware.py --detect-port follower --write
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import yaml

from cfg import _config  # noqa: E402  (sets up sys.path)


def list_serial_ports() -> list[str]:
    from lerobot.scripts.lerobot_find_port import find_available_ports

    return sorted(find_available_ports())


def detect_port_interactive(label: str) -> str:
    """Identify a single arm's port by the unplug/replug diff method."""
    from lerobot.scripts.lerobot_find_port import find_available_ports

    print(f"\n--- Detecting the {label.upper()} arm port ---")
    before = set(find_available_ports())
    input(f"Make sure ONLY the {label} arm is the device you're about to unplug.\n"
          f"Unplug the {label} arm's USB cable, then press Enter...")
    time.sleep(0.5)
    after = set(find_available_ports())
    diff = list(before - after)

    if len(diff) == 1:
        port = diff[0]
        print(f"Detected {label} port: {port}")
        input("Reconnect the cable and press Enter to continue...")
        return port
    if not diff:
        raise SystemExit("No port disappeared — could not detect. Try again.")
    raise SystemExit(f"Multiple ports changed ({diff}) — unplug only one device.")


def detect_cameras() -> dict[str, dict]:
    """Return a config-shaped cameras dict from detected OpenCV cameras."""
    from lerobot.cameras.opencv import OpenCVCamera

    found = OpenCVCamera.find_cameras()
    cameras: dict[str, dict] = {}
    for i, cam in enumerate(found):
        profile = cam.get("default_stream_profile", {})
        name = "front" if i == 0 else f"cam{i}"
        cameras[name] = {
            "index_or_path": cam["id"],
            "width": int(profile.get("width") or 640),
            "height": int(profile.get("height") or 480),
            "fps": int(profile.get("fps") or 30),
        }
    return cameras


def save_config(cfg: dict) -> None:
    """Write the config dict back to configs/config.yaml, preserving order."""
    with open(_config.DEFAULT_CONFIG_PATH, "w") as f:
        yaml.safe_dump(cfg, f, sort_keys=False, default_flow_style=False)
    print(f"\nWrote updates to {_config.DEFAULT_CONFIG_PATH}")


def main():
    parser = argparse.ArgumentParser(description="Detect SO-101 ports and cameras")
    parser.add_argument(
        "--detect-port",
        choices=["leader", "follower"],
        help="Interactively detect one arm's port via the unplug/replug method",
    )
    parser.add_argument(
        "--write-cameras",
        action="store_true",
        help="Detect cameras and write them into configs/config.yaml",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Persist the result of --detect-port into configs/config.yaml",
    )
    args = parser.parse_args()

    cfg = _config.load()

    # --- Plain listing (default behaviour) -----------------------------------
    if not args.detect_port and not args.write_cameras:
        print("Available serial ports:")
        for p in list_serial_ports():
            print(f"  {p}")
        print("\nDetected cameras:")
        cams = detect_cameras()
        if cams:
            for name, c in cams.items():
                print(f"  {name}: index_or_path={c['index_or_path']} "
                      f"{c['width']}x{c['height']} @ {c['fps']}fps")
        else:
            print("  (none found)")
        print("\nTip: use --detect-port leader/follower --write to save a port,")
        print("     or --write-cameras to save detected cameras.")
        return

    # --- Detect a single arm's port ------------------------------------------
    if args.detect_port:
        port = detect_port_interactive(args.detect_port)
        if args.write:
            cfg.setdefault("ports", {})[args.detect_port] = port
            save_config(cfg)
        else:
            print(f"\n(Use --write to save {args.detect_port}: {port} into config.yaml)")

    # --- Detect cameras ------------------------------------------------------
    if args.write_cameras:
        cams = detect_cameras()
        if not cams:
            print("No cameras detected — leaving config unchanged.")
        else:
            cfg["cameras"] = cams
            save_config(cfg)
            print("Detected cameras written:")
            for name, c in cams.items():
                print(f"  {name}: {c}")


if __name__ == "__main__":
    main()
