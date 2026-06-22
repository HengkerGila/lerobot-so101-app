#!/usr/bin/env python
"""
SO-101 application server (decoupled monitor).

Unlike monitor.py, this process owns **no hardware**. It subscribes to the ZMQ
bridge published by ``teleop.py --bridge`` (see scripts/bridge.py), fills a
StateBuffer with the observations it receives, and serves the web dashboard
(scripts/dashboard.py) from that buffer.

This is the "application" half of the bridge architecture:

    publisher  ──ZMQ PUB (observations)──>  app.py (ZMQ SUB)  ──HTTP──>  browser
               <──ZMQ REP (commands)─────   app.py (ZMQ REQ)

Because it never touches the serial bus or the camera, you can start, stop, and
restart the app freely while the publisher keeps running — and vice versa.

Pair it with either publisher:
  - session_server.py  — full session control (start/stop teleop & recording).
    The control panel appears automatically when its status is detected.
  - teleop.py --bridge — live view only; control buttons stay hidden.

Usage:
    # terminal 1: own the hardware and publish (one of these)
    python scripts/session_server.py     # controllable session
    python scripts/teleop.py --bridge    # view-only

    # terminal 2: serve the app
    python scripts/app.py
    # then open http://localhost:8000

Settings come from configs/config.yaml (`webui:` for the server, `bridge:` for
the ZMQ addresses).
"""

from __future__ import annotations

import threading

import _config

cfg = _config.load()  # loads YAML and puts lerobot on sys.path

import bridge
import dashboard

from lerobot.robots import make_robot_from_config
from lerobot.utils.import_utils import register_third_party_plugins

WEBUI = cfg.get("webui") or {}
HOST = WEBUI.get("host", "0.0.0.0")
PORT = int(WEBUI.get("port", 8000))
POLL_FPS = float(WEBUI.get("poll_fps", 30))
JPEG_QUALITY = int(WEBUI.get("jpeg_quality", 80))

BRIDGE = cfg.get("bridge") or {}
ADDRESS = BRIDGE.get("address", "tcp://127.0.0.1:5555")
COMMAND_ADDRESS = BRIDGE.get("command_address", "tcp://127.0.0.1:5556")


def _observation_features():
    """Read joint/camera names from the robot config WITHOUT opening hardware.

    ``make_robot_from_config`` only constructs config objects; ``connect()`` is
    what opens the serial port and camera, and we never call it here.
    """
    robot = make_robot_from_config(_config.build_robot_config(cfg))
    joint_names = [k for k, v in robot.observation_features.items() if v is float]
    camera_names = [
        k for k, v in robot.observation_features.items() if isinstance(v, tuple)
    ]
    return robot.name, joint_names, camera_names


def main():
    register_third_party_plugins()

    robot_name, joint_names, camera_names = _observation_features()
    buffer = dashboard.StateBuffer(
        robot_name=robot_name,
        joint_names=joint_names,
        camera_names=camera_names,
        jpeg_quality=JPEG_QUALITY,
    )

    subscriber = bridge.Subscriber(ADDRESS, buffer)
    subscriber.start()

    command_client = bridge.CommandClient(COMMAND_ADDRESS)

    app = dashboard.make_app(buffer, cfg, poll_fps=POLL_FPS, command_client=command_client)
    print(f"Starting SO-101 app on http://{HOST}:{PORT}")
    print(f"Subscribing to observations at {ADDRESS}")
    print(f"Sending commands to {COMMAND_ADDRESS}")
    print("Start the hardware with: python scripts/session_server.py (or teleop.py --bridge)")
    try:
        dashboard.serve_in_thread(app, HOST, PORT)
        threading.Event().wait()  # block until Ctrl+C
    except KeyboardInterrupt:
        pass
    finally:
        command_client.close()
        subscriber.stop()


if __name__ == "__main__":
    main()
