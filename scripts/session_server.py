#!/usr/bin/env python
"""
SO-101 session server — the hardware-owning daemon behind the application.

This is the persistent process that owns the arm + cameras and runs a session
state machine. It always publishes observations over the ZMQ bridge (so the app
shows a live view in every mode) and listens on the command channel so the app
can drive the workflow:

    modes:  idle  <->  teleop  <->  recording

    commands (from app.py over ZMQ):
        start_teleop / stop_teleop
        start_recording {single_task?, num_episodes?, repo_id?}
        save_episode          save current episode, begin the next
        discard_episode       drop current episode, re-record it
        stop_recording        finalize the dataset, return to idle
        get_status            return the current session status

All hardware and dataset mutations happen in the main loop; commands are queued
and executed there, so there are no races. The ZMQ publisher runs in its own
thread and keeps streaming the latest frame + status even while a blocking
save/finalize runs.

Run it instead of teleop.py when you want the app to control the session:

    python scripts/session_server.py
    python scripts/app.py          # in another terminal; open http://localhost:8000

Settings come from configs/config.yaml (`bridge:`, `teleop_loop:`, `record:`).
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from copy import deepcopy
from datetime import datetime

import _config

cfg = _config.load()  # loads YAML and puts lerobot on sys.path

import bridge

from lerobot.datasets import (
    LeRobotDataset,
    VideoEncodingManager,
    aggregate_pipeline_dataset_features,
    create_initial_features,
)
from lerobot.processor import make_default_processors
from lerobot.robots import make_robot_from_config
from lerobot.teleoperators import make_teleoperator_from_config
from lerobot.utils.constants import ACTION, OBS_STR
from lerobot.utils.feature_utils import build_dataset_frame, combine_feature_dicts
from lerobot.utils.import_utils import register_third_party_plugins
from lerobot.utils.robot_utils import precise_sleep
from lerobot.utils.utils import init_logging

IDLE, TELEOP, RECORDING = "idle", "teleop", "recording"


class SessionServer:
    def __init__(self) -> None:
        loop_cfg = cfg.get("teleop_loop", {})
        self.teleop_fps = float(loop_cfg.get("fps", 60))
        self.record_fps = float(cfg.get("record", {}).get("fps", 30))

        self.robot = make_robot_from_config(_config.build_robot_config(cfg))
        self.teleop = make_teleoperator_from_config(_config.build_teleop_config(cfg))
        self.processors = make_default_processors()  # (teleop_action, robot_action, robot_obs)

        self.joint_names = [
            k for k, v in self.robot.observation_features.items() if v is float
        ]
        self.camera_names = [
            k for k, v in self.robot.observation_features.items() if isinstance(v, tuple)
        ]

        br = cfg.get("bridge") or {}
        self.publisher = bridge.Publisher(
            address=br.get("address", "tcp://127.0.0.1:5555"),
            joint_names=self.joint_names,
            camera_names=self.camera_names,
            publish_fps=float(br.get("publish_fps", 30)),
        )
        self.command_server = bridge.CommandServer(
            address=br.get("command_address", "tcp://127.0.0.1:5556"),
            handler=self._handle_command,
        )

        # Shared status (read by the publisher thread, mutated in the main loop).
        self._status_lock = threading.Lock()
        self._mode = IDLE
        self._loop_hz = 0.0
        self._error: str | None = None
        self._recording: dict | None = None

        # Recording state (main-loop only).
        self._dataset: LeRobotDataset | None = None
        self._vem: VideoEncodingManager | None = None
        self._task: str = ""
        self._last_obs: dict = {}

        # Command queue: (cmd_dict, Event, result_holder) executed in main loop.
        self._cmd_queue: "queue.Queue" = queue.Queue()
        self._stop = threading.Event()

    # --- status --------------------------------------------------------------
    def _status(self) -> dict:
        with self._status_lock:
            return {
                "mode": self._mode,
                "fps": self.record_fps if self._mode == RECORDING else self.teleop_fps,
                "loop_hz": round(self._loop_hz, 1),
                "error": self._error,
                "recording": deepcopy(self._recording),
            }

    def _set(self, **kw) -> None:
        with self._status_lock:
            for k, v in kw.items():
                setattr(self, f"_{k}", v)

    # --- command handling ----------------------------------------------------
    def _handle_command(self, cmd: dict) -> dict:
        """Runs in the CommandServer thread. Queues work for the main loop."""
        name = cmd.get("cmd")
        if name == "get_status":
            return {"ok": True, "status": self._status()}

        event = threading.Event()
        holder: dict = {}
        self._cmd_queue.put((cmd, event, holder))
        if not event.wait(timeout=290):
            return {"ok": False, "error": f"'{name}' timed out"}
        return holder["result"]

    def _drain_commands(self) -> None:
        while True:
            try:
                cmd, event, holder = self._cmd_queue.get_nowait()
            except queue.Empty:
                return
            try:
                holder["result"] = self._execute(cmd)
            except Exception as e:  # noqa: BLE001
                logging.exception("command failed: %s", cmd)
                self._set(error=str(e))
                holder["result"] = {"ok": False, "error": str(e)}
            finally:
                event.set()

    def _execute(self, cmd: dict) -> dict:
        """Runs in the main loop. Mutates mode / dataset state."""
        name = cmd.get("cmd")
        if name == "start_teleop":
            if self._mode == RECORDING:
                return {"ok": False, "error": "stop recording first"}
            self._set(mode=TELEOP, error=None)
        elif name == "stop_teleop":
            if self._mode == RECORDING:
                return {"ok": False, "error": "use stop_recording while recording"}
            self._set(mode=IDLE)
        elif name == "start_recording":
            if self._mode == RECORDING:
                return {"ok": False, "error": "already recording"}
            self._start_recording(cmd)
        elif name in ("save_episode", "discard_episode", "stop_recording"):
            if self._mode != RECORDING:
                return {"ok": False, "error": "not recording"}
            if name == "save_episode":
                self._save_episode()
            elif name == "discard_episode":
                self._discard_episode()
            else:
                self._stop_recording()
        else:
            return {"ok": False, "error": f"unknown command '{name}'"}
        return {"ok": True, "status": self._status()}

    # --- recording lifecycle (main loop only) --------------------------------
    def _start_recording(self, cmd: dict) -> None:
        rec = cfg.get("record", {})
        self._task = cmd.get("single_task") or rec.get("single_task", "")
        num_episodes = int(cmd.get("num_episodes") or rec.get("num_episodes", 0))
        repo_id = cmd.get("repo_id") or rec.get("repo_id", "so101_demo")
        root = rec.get("root")

        # Per-session unique names so repeated sessions never collide on disk.
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        repo_id = f"{repo_id}_{stamp}"
        if root:
            root = f"{root}_{stamp}"

        teleop_action_processor, _, robot_observation_processor = self.processors
        use_videos = bool(rec.get("video", True))
        features = combine_feature_dicts(
            aggregate_pipeline_dataset_features(
                pipeline=teleop_action_processor,
                initial_features=create_initial_features(action=self.robot.action_features),
                use_videos=use_videos,
            ),
            aggregate_pipeline_dataset_features(
                pipeline=robot_observation_processor,
                initial_features=create_initial_features(observation=self.robot.observation_features),
                use_videos=use_videos,
            ),
        )
        num_cameras = len(getattr(self.robot, "cameras", {}) or {})
        self._dataset = LeRobotDataset.create(
            repo_id,
            int(self.record_fps),
            root=root,
            robot_type=self.robot.name,
            features=features,
            use_videos=use_videos,
            image_writer_processes=int(rec.get("num_image_writer_processes", 0)),
            image_writer_threads=4 * num_cameras,
            streaming_encoding=bool(rec.get("streaming_encoding", True)),
            encoder_threads=int(rec.get("encoder_threads", 2)),
        )
        self._vem = VideoEncodingManager(self._dataset)
        self._vem.__enter__()

        self._set(
            mode=RECORDING,
            error=None,
            recording={
                "repo_id": repo_id,
                "root": root,
                "task": self._task,
                "episodes_saved": 0,
                "num_episodes": num_episodes,
                "episode_frames": 0,
                "saving": False,
            },
        )
        logging.info("Recording started: %s (target %d episodes)", repo_id, num_episodes)

    def _save_episode(self) -> None:
        self._update_recording(saving=True)
        self.publisher.update(self._last_obs, meta=self._status())  # surface 'saving' now
        self._dataset.save_episode()
        with self._status_lock:
            self._recording["episodes_saved"] += 1
            self._recording["episode_frames"] = 0
            self._recording["saving"] = False
        logging.info("Saved episode (%d total)", self._recording["episodes_saved"])

    def _discard_episode(self) -> None:
        self._dataset.clear_episode_buffer()
        self._update_recording(episode_frames=0)
        logging.info("Discarded current episode")

    def _stop_recording(self) -> None:
        if self._vem is not None:
            self._vem.__exit__(None, None, None)
            self._vem = None
        if self._dataset is not None:
            self._dataset.finalize()
        n = self._recording["episodes_saved"] if self._recording else 0
        self._dataset = None
        self._set(mode=IDLE, recording=None)
        logging.info("Recording stopped (%d episodes saved)", n)

    def _update_recording(self, **kw) -> None:
        with self._status_lock:
            if self._recording is not None:
                self._recording.update(kw)

    # --- main loop -----------------------------------------------------------
    def run(self) -> None:
        self.teleop.connect()
        self.robot.connect()
        teleop_action_processor, robot_action_processor, robot_observation_processor = self.processors

        logging.info("Session server ready (idle). Drive it from app.py — Ctrl+C to stop.")
        try:
            while not self._stop.is_set():
                loop_start = time.perf_counter()
                self._drain_commands()

                mode = self._mode
                obs = self.robot.get_observation()
                self._last_obs = obs

                if mode in (TELEOP, RECORDING):
                    raw_action = self.teleop.get_action()
                    teleop_action = teleop_action_processor((raw_action, obs))
                    robot_action = robot_action_processor((teleop_action, obs))
                    self.robot.send_action(robot_action)

                    if mode == RECORDING and self._dataset is not None:
                        obs_proc = robot_observation_processor(obs)
                        obs_frame = build_dataset_frame(self._dataset.features, obs_proc, prefix=OBS_STR)
                        act_frame = build_dataset_frame(self._dataset.features, teleop_action, prefix=ACTION)
                        self._dataset.add_frame(
                            {**obs_frame, **act_frame, "task": self._task}
                        )
                        self._update_recording(
                            episode_frames=self._recording["episode_frames"] + 1
                        )

                self.publisher.update(obs, meta=self._status())

                target_fps = self.record_fps if mode == RECORDING else self.teleop_fps
                dt = time.perf_counter() - loop_start
                precise_sleep(max(1.0 / target_fps - dt, 0.0))
                loop_s = time.perf_counter() - loop_start
                if loop_s > 0:
                    self._set(loop_hz=1.0 / loop_s)
        except KeyboardInterrupt:
            pass
        finally:
            self._shutdown()

    def _shutdown(self) -> None:
        logging.info("Shutting down session server…")
        try:
            if self._mode == RECORDING:
                self._stop_recording()
        except Exception:  # noqa: BLE001
            logging.exception("error finalizing dataset on shutdown")
        self.command_server.stop()
        self.publisher.close()
        try:
            self.teleop.disconnect()
            self.robot.disconnect()
        except Exception:  # noqa: BLE001
            logging.exception("error disconnecting hardware")


def main():
    register_third_party_plugins()
    init_logging()
    SessionServer().run()


if __name__ == "__main__":
    main()
