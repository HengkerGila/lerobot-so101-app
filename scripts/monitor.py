#!/usr/bin/env python
"""
Standalone read-only web dashboard for the SO-101 follower arm.

Opens the follower arm + its cameras (using configs/config.yaml) and serves a
browser dashboard (see scripts/dashboard.py) with live camera streams, joint
positions, and connection status.

IMPORTANT: the cameras and the motor serial bus can each be opened by only one
process at a time. Run this monitor when teleop.py / record.py are NOT running.
To watch the dashboard *while* teleoperating, use `teleop.py --dashboard`
instead — that shares teleop's single hardware connection.

Usage:
    python scripts/monitor.py
    # then open http://localhost:8000

Settings come from configs/config.yaml. Optional `webui:` section:
    webui:
      host: 0.0.0.0
      port: 8000
      poll_fps: 30
      jpeg_quality: 80
"""

from __future__ import annotations

import threading

import _config

cfg = _config.load()  # loads YAML and puts lerobot on sys.path

import dashboard

from lerobot.robots import make_robot_from_config
from lerobot.utils.import_utils import register_third_party_plugins

WEBUI = cfg.get("webui") or {}
HOST = WEBUI.get("host", "0.0.0.0")
PORT = int(WEBUI.get("port", 8000))
POLL_FPS = float(WEBUI.get("poll_fps", 30))
JPEG_QUALITY = int(WEBUI.get("jpeg_quality", 80))


class RobotPoller:
    """Background thread that owns the follower arm and feeds a StateBuffer."""

    def __init__(self) -> None:
        self.robot = make_robot_from_config(_config.build_robot_config(cfg))
        camera_names = [
            k for k, v in self.robot.observation_features.items() if isinstance(v, tuple)
        ]
        joint_names = [
            k for k, v in self.robot.observation_features.items() if v is float
        ]
        self.buffer = dashboard.StateBuffer(
            robot_name=self.robot.name,
            joint_names=joint_names,
            camera_names=camera_names,
            jpeg_quality=JPEG_QUALITY,
        )

        self._connected = False
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2.0)
        try:
            if self.robot.is_connected:
                self.robot.disconnect()
        except Exception:
            pass

    def _run(self) -> None:
        period = 1.0 / POLL_FPS
        while not self._stop.is_set():
            if not self._connected:
                try:
                    # calibrate=False: never block on interactive calibration.
                    self.robot.connect(calibrate=False)
                    self._connected = True
                except Exception as e:  # noqa: BLE001
                    self.buffer.set_status(False, str(e))
                    self._stop.wait(2.0)
                    continue

            try:
                self.buffer.update(self.robot.get_observation())
            except Exception as e:  # noqa: BLE001
                self._connected = False
                self.buffer.set_status(False, str(e))

            self._stop.wait(period)


def main():
    register_third_party_plugins()
    poller = RobotPoller()
    poller.start()
    app = dashboard.make_app(poller.buffer, cfg, poll_fps=POLL_FPS)
    print(f"Starting SO-101 monitor on http://{HOST}:{PORT}")
    print("Note: stop teleop.py / record.py first — devices allow one process at a time.")
    try:
        dashboard.serve_in_thread(app, HOST, PORT)
        threading.Event().wait()  # block until Ctrl+C
    except KeyboardInterrupt:
        pass
    finally:
        poller.stop()


if __name__ == "__main__":
    main()
