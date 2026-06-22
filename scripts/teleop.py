#!/usr/bin/env python
"""
Teleoperate the SO-101 follower arm with an SO-101 leader arm.

All settings come from configs/config.yaml — edit that file, not this script.

Usage:
    python scripts/teleop.py
    python scripts/teleop.py --dashboard   # also serve the web monitor in-process
    python scripts/teleop.py --bridge      # publish observations for app.py

Controls:
    Move the leader arm to drive the follower arm.
    Ctrl+C to stop.

Two ways to observe teleop live (both reuse teleop's single hardware connection,
since the motor bus and camera each allow only one process at a time):

  --dashboard  Serve the web monitor in this process. Simplest; no extra process.
  --bridge     Publish observations over ZMQ (see scripts/bridge.py) so a
               separate application (scripts/app.py) can subscribe and render
               them. Use this when the UI should be its own process/app.
"""

import argparse
import logging
import time

import _config

cfg = _config.load()  # loads YAML and puts lerobot on sys.path

from lerobot.processor import make_default_processors
from lerobot.robots import make_robot_from_config
from lerobot.teleoperators import make_teleoperator_from_config
from lerobot.utils.import_utils import register_third_party_plugins
from lerobot.utils.robot_utils import precise_sleep
from lerobot.utils.utils import init_logging
from lerobot.utils.visualization_utils import init_rerun, shutdown_rerun


def _teleop_loop(teleop, robot, fps, processors, sinks=()):
    """Mirror of lerobot.teleop_loop, but taps each observation into ``sinks``.

    lerobot's teleop_loop offers no per-iteration hook, so we inline the loop to
    forward observations to consumers (dashboard buffer and/or ZMQ publisher)
    without a second hardware connection. Each sink exposes ``update(obs)``.
    """
    teleop_action_processor, robot_action_processor, _ = processors
    while True:
        loop_start = time.perf_counter()

        obs = robot.get_observation()
        for sink in sinks:
            sink.update(obs)

        raw_action = teleop.get_action()
        teleop_action = teleop_action_processor((raw_action, obs))
        robot_action_to_send = robot_action_processor((teleop_action, obs))
        robot.send_action(robot_action_to_send)

        dt_s = time.perf_counter() - loop_start
        precise_sleep(max(1 / fps - dt_s, 0.0))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dashboard",
        action="store_true",
        help="Serve the web monitor (configs/config.yaml webui:) in this process.",
    )
    parser.add_argument(
        "--bridge",
        action="store_true",
        help="Publish observations over ZMQ (configs/config.yaml bridge:) for app.py.",
    )
    args = parser.parse_args()

    register_third_party_plugins()
    init_logging()

    loop_cfg = cfg.get("teleop_loop", {})
    fps = loop_cfg.get("fps", 60)
    display_data = loop_cfg.get("display_data", False)

    robot = make_robot_from_config(_config.build_robot_config(cfg))
    teleop = make_teleoperator_from_config(_config.build_teleop_config(cfg))
    processors = make_default_processors()

    joint_names = [k for k, v in robot.observation_features.items() if v is float]
    camera_names = [
        k for k, v in robot.observation_features.items() if isinstance(v, tuple)
    ]

    if display_data:
        init_rerun(session_name="teleoperation")

    teleop.connect()
    robot.connect()

    # Observation consumers (each exposes update(obs)); fed every loop iteration.
    sinks = []
    server = None
    publisher = None

    if args.dashboard:
        import dashboard

        webui = cfg.get("webui") or {}
        host = webui.get("host", "0.0.0.0")
        port = int(webui.get("port", 8000))
        poll_fps = float(webui.get("poll_fps", 30))
        buffer = dashboard.StateBuffer(
            robot_name=robot.name,
            joint_names=joint_names,
            camera_names=camera_names,
            jpeg_quality=int(webui.get("jpeg_quality", 80)),
        )
        app = dashboard.make_app(buffer, cfg, poll_fps=poll_fps)
        server = dashboard.serve_in_thread(app, host, port)
        sinks.append(buffer)
        logging.info("Dashboard at http://%s:%d", host, port)

    if args.bridge:
        import bridge

        br = cfg.get("bridge") or {}
        address = br.get("address", "tcp://127.0.0.1:5555")
        publisher = bridge.Publisher(
            address=address,
            joint_names=joint_names,
            camera_names=camera_names,
            publish_fps=float(br.get("publish_fps", 30)),
        )
        sinks.append(publisher)
        logging.info("Publishing observations on %s (run app.py to view)", address)

    logging.info("Teleoperation started — Ctrl+C to stop.")
    try:
        _teleop_loop(teleop, robot, fps, processors, sinks=sinks)
    except KeyboardInterrupt:
        pass
    finally:
        if server is not None:
            server.should_exit = True
        if publisher is not None:
            publisher.close()
        if display_data:
            shutdown_rerun()
        teleop.disconnect()
        robot.disconnect()
        logging.info("Teleoperation stopped.")


if __name__ == "__main__":
    main()
