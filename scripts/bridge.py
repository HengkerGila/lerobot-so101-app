#!/usr/bin/env python
"""
ZMQ bridge between the hardware-owning process and the application.

Two independent channels, both defined here:

1. **Observation stream** (PUB/SUB) — the hardware owner publishes each
   observation (joints + camera frames) plus an optional ``meta`` blob (used to
   carry live session status). Consumers subscribe read-only. Latest-state
   semantics: a low high-water-mark drops stale frames instead of queueing.

2. **Command channel** (REQ/REP) — the application sends JSON commands to the
   hardware owner and gets a JSON reply (ack/result). Used for session control
   (start/stop teleop, recording, save/discard episode).

Observation wire format (one ZMQ multipart message):

    part 0 : b"obs"                       topic
    part 1 : JSON header (utf-8 bytes)    {"t", "joints", "cameras", "meta"}
    part 2.. : raw camera frame buffers   one per entry in header["cameras"]

Frames travel raw (uncompressed) — meant for localhost, where that is cheap and
keeps JPEG encoding off the control loop (the app encodes only for the browser).
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any, Callable

import numpy as np
import zmq

TOPIC = b"obs"
_HWM = 4  # bound in-flight messages -> drop stale frames instead of queueing


# =============================================================================
# Observation stream (PUB / SUB)
# =============================================================================


class Publisher:
    """Owns a PUB socket; a background thread sends the latest observation.

    The hardware loop only calls :meth:`update` (a cheap reference store), so
    serialization and sending never block the control loop. ``meta`` is an
    optional JSON-serializable blob sent alongside each message (session status).
    """

    def __init__(
        self,
        address: str,
        joint_names: list[str],
        camera_names: list[str],
        publish_fps: float = 30.0,
    ) -> None:
        self.address = address
        self.joint_names = list(joint_names)
        self.camera_names = list(camera_names)
        self.period = 1.0 / max(publish_fps, 1.0)

        self._ctx = zmq.Context.instance()
        self._sock = self._ctx.socket(zmq.PUB)
        self._sock.set_hwm(_HWM)
        self._sock.bind(address)

        self._lock = threading.Lock()
        self._latest: dict[str, Any] | None = None
        self._meta: Any = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def update(self, obs: dict[str, Any], meta: Any = None) -> None:
        """Hand the latest observation (+ optional meta) to the sender thread."""
        with self._lock:
            self._latest = obs
            self._meta = meta

    def _run(self) -> None:
        while not self._stop.is_set():
            with self._lock:
                obs = self._latest
                meta = self._meta
            if obs is not None:
                self._send(obs, meta)
            self._stop.wait(self.period)

    def _send(self, obs: dict[str, Any], meta: Any) -> None:
        joints = {k: float(obs[k]) for k in self.joint_names if k in obs}
        cams: list[dict] = []
        frames: list[np.ndarray] = []
        for name in self.camera_names:
            arr = obs.get(name)
            if arr is None:
                continue
            arr = np.ascontiguousarray(arr)
            cams.append({"name": name, "shape": list(arr.shape), "dtype": str(arr.dtype)})
            frames.append(arr)
        header = {"t": time.time(), "joints": joints, "cameras": cams, "meta": meta}
        parts: list = [TOPIC, json.dumps(header).encode("utf-8"), *frames]
        try:
            # copy=False: zero-copy send of the numpy buffers.
            self._sock.send_multipart(parts, copy=False)
        except zmq.ZMQError:
            pass

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=1.0)
        self._sock.close(linger=0)


class Subscriber:
    """Owns a SUB socket; a background thread fills a buffer with each message.

    ``buffer`` must expose ``update(obs)``, ``set_meta(meta)`` and
    ``set_status(connected, error)`` (see ``dashboard.StateBuffer``). If no
    message arrives within ``stale_after`` seconds the buffer is marked
    disconnected so the UI reflects a dead bridge.
    """

    def __init__(self, address: str, buffer, stale_after: float = 2.0) -> None:
        self.address = address
        self.buffer = buffer
        self.stale_after = stale_after

        self._ctx = zmq.Context.instance()
        self._sock = self._ctx.socket(zmq.SUB)
        self._sock.set_hwm(_HWM)
        self._sock.setsockopt(zmq.SUBSCRIBE, TOPIC)
        self._sock.connect(address)
        self._poller = zmq.Poller()
        self._poller.register(self._sock, zmq.POLLIN)

        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self.buffer.set_status(False, f"waiting for publisher at {self.address}")
        self._thread.start()

    def _run(self) -> None:
        timeout_ms = int(self.stale_after * 1000)
        while not self._stop.is_set():
            events = dict(self._poller.poll(timeout_ms))
            if self._sock not in events:
                self.buffer.set_status(
                    False, "no data from teleop (is the publisher running?)"
                )
                self.buffer.set_meta(None)
                continue
            try:
                parts = self._sock.recv_multipart()
            except zmq.ZMQError:
                continue
            decoded = self._decode(parts)
            if decoded is not None:
                obs, meta = decoded
                self.buffer.update(obs)
                self.buffer.set_meta(meta)

    @staticmethod
    def _decode(parts: list[bytes]):
        if len(parts) < 2 or parts[0] != TOPIC:
            return None
        header = json.loads(parts[1].decode("utf-8"))
        obs: dict[str, Any] = dict(header.get("joints", {}))
        frames = parts[2:]
        for i, meta in enumerate(header.get("cameras", [])):
            if i >= len(frames):
                break
            arr = np.frombuffer(frames[i], dtype=meta["dtype"])
            obs[meta["name"]] = arr.reshape(meta["shape"])
        return obs, header.get("meta")

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=1.0)
        self._sock.close(linger=0)


# =============================================================================
# Command channel (REQ / REP)
# =============================================================================


class CommandServer:
    """Owns a REP socket; a background thread runs ``handler`` for each request.

    ``handler(request: dict) -> dict`` is supplied by the session server. Every
    request gets exactly one reply (REQ/REP requirement); handler exceptions are
    caught and returned as ``{"ok": False, "error": ...}``.
    """

    def __init__(self, address: str, handler: Callable[[dict], dict]) -> None:
        self.address = address
        self.handler = handler

        self._ctx = zmq.Context.instance()
        self._sock = self._ctx.socket(zmq.REP)
        self._sock.bind(address)
        self._poller = zmq.Poller()
        self._poller.register(self._sock, zmq.POLLIN)

        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            events = dict(self._poller.poll(200))
            if self._sock not in events:
                continue
            try:
                req = json.loads(self._sock.recv().decode("utf-8"))
            except (zmq.ZMQError, ValueError):
                continue
            try:
                resp = self.handler(req)
            except Exception as e:  # noqa: BLE001
                resp = {"ok": False, "error": str(e)}
            try:
                self._sock.send(json.dumps(resp).encode("utf-8"))
            except zmq.ZMQError:
                pass

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=1.0)
        self._sock.close(linger=0)


class CommandClient:
    """Owns a REQ socket; ``request`` sends a command and returns the reply.

    Thread-safe (one in-flight request at a time). On timeout the socket is
    rebuilt (the "lazy pirate" pattern) so a missed reply can't wedge the REQ
    state machine, and a structured error is returned instead of raising.
    """

    def __init__(self, address: str, timeout_s: float = 300.0) -> None:
        self.address = address
        self.timeout_ms = int(timeout_s * 1000)
        self._ctx = zmq.Context.instance()
        self._lock = threading.Lock()
        self._sock = None
        self._connect()

    def _connect(self) -> None:
        self._sock = self._ctx.socket(zmq.REQ)
        self._sock.setsockopt(zmq.RCVTIMEO, self.timeout_ms)
        self._sock.setsockopt(zmq.SNDTIMEO, 1000)
        self._sock.setsockopt(zmq.LINGER, 0)
        self._sock.connect(self.address)

    def _reset(self) -> None:
        try:
            self._sock.close(linger=0)
        except Exception:  # noqa: BLE001
            pass
        self._connect()

    def request(self, cmd: dict) -> dict:
        with self._lock:
            try:
                self._sock.send(json.dumps(cmd).encode("utf-8"))
                reply = self._sock.recv()
                return json.loads(reply.decode("utf-8"))
            except zmq.ZMQError:
                self._reset()
                return {"ok": False, "error": "session server not responding"}

    def close(self) -> None:
        with self._lock:
            self._sock.close(linger=0)
