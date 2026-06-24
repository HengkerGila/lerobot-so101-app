# Architecture

This document describes the entire system: the processes, who owns the hardware,
how data flows, the ZMQ bridge, the web layer, and the threading model. Read it
to understand *how* the project works end to end.

## The hardware constraint that shapes everything

The SO-101 follower exposes two kinds of devices, each opened over the OS:

- a **motor serial bus** (a Feetech/SCS half-duplex bus, e.g. `/dev/ttyACM0`)
  carrying all six servos, and
- one or more **USB cameras** (e.g. `/dev/video0`).

**Each device can be held by exactly one process at a time.** The serial bus is
also a single-master bus: if two processes write request packets at once, the
replies interleave and corrupt (`Incorrect status packet`). A camera simply
fails to open twice (`Failed to open OpenCVCamera`).

Every architectural decision follows from this: **one process owns the hardware**,
and anything else that needs the data gets it second-hand. That "anything else"
is the web application, and the second-hand path is the ZMQ bridge.

## The processes

```
                       ┌──────────────────────── owns the hardware ───────────────────────┐
                       │                                                                   │
   ┌───────────┐   ┌───┴────────┐   ┌──────────────────┐   ┌───────────┐                  │
   │ teleop.py │   │ record.py  │   │ session_server.py│   │ monitor.py│                   │
   └───────────┘   └────────────┘   └────────┬─────────┘   └─────┬─────┘                  │
   leader→follower  lerobot record  idle/teleop/recording   standalone view               │
                                              │                   │                        │
                                     ZMQ bridge (src/modules/bridge.py)                    │
                                     obs stream  +  command channel                        │
                                              │                   │ (in-process StateBuffer)│
                                              ▼                   ▼                        │
                                     ┌──────────────┐      ┌──────────────┐                │
                                     │   app.py     │      │ FastAPI app  │                │
                                     │ (ZMQ SUB/REQ)│      │(dashboard.py)│                │
                                     └──────┬───────┘      └──────┬───────┘                │
                                            └──────── browser ────┘                        │
```

The hardware can be owned by **one** of these at a time:

| Process | Owns hardware | Purpose |
|---------|---------------|---------|
| `teleop.py` | yes | Real-time teleoperation. Optional `--dashboard` (serve UI in-process) or `--bridge` (publish for `app.py`). |
| `record.py` | yes | Dataset recording via lerobot's built-in recorder (terminal keyboard controls). |
| `session_server.py` | yes | The daemon behind the application: a state machine that does teleop *and* recording on command. |
| `monitor.py` | yes | Standalone read-only dashboard (no teleop). |
| `app.py` | **no** | The browser application. Owns no devices; gets data over the bridge and sends commands back. |

Pick exactly one hardware owner. Running two at once triggers the conflict above
— that's the rule, not a bug.

## Configuration & module layout

Every script begins the same way (`src/cfg/_config.py`):

```python
import _config
cfg = _config.load()        # 1. read configs/config.yaml
                            # 2. prepend cfg["lerobot_src"] to sys.path
# ...only now import lerobot
```

That ordering matters: the local LeRobot checkout must be on `sys.path` before
any `lerobot` import. `_config.py` also builds the typed LeRobot config objects:

| Config section | Built object | Builder |
|----------------|-------------|---------|
| `ports.follower` + `robot` + `cameras` | `SOFollowerRobotConfig` | `build_robot_config` |
| `ports.leader` + `teleop` | `SOLeaderTeleopConfig` | `build_teleop_config` |
| `record` | `DatasetRecordConfig` | `build_dataset_config` |
| `cameras` | `{name: OpenCVCameraConfig}` | `build_camera_configs` |

Shared, hardware-free modules:

- **`src/app/dashboard.py`** — the web UI: a thread-safe `StateBuffer` plus a FastAPI app
  that serves a *view* of it. Owns no hardware. Used by `monitor.py`,
  `teleop.py --dashboard`, and `app.py`.
- **`src/modules/bridge.py`** — the ZMQ transport: `Publisher`/`Subscriber` (observation
  stream) and `CommandServer`/`CommandClient` (command channel).
- **`src/cfg/_config.py`** — the loader and config builders above.

## The ZMQ bridge

The bridge (`src/modules/bridge.py`) decouples the hardware owner from the app over
two independent ZMQ channels, both configured under `bridge:` in the config.

### Channel 1 — observation stream (PUB / SUB)

The hardware owner **publishes** observations; the app **subscribes**. One ZMQ
multipart message per observation:

```
part 0 : b"obs"                          topic
part 1 : JSON header  {"t", "joints", "cameras", "meta"}
part 2.. : raw camera frame buffers      one per entry in header["cameras"]
```

- `joints` — `{name: value}` for the six joints.
- `cameras` — ordered list of `{"name", "shape", "dtype"}`; the matching raw
  frame buffers follow as additional message parts.
- `meta` — an arbitrary JSON blob; the session server puts live **session
  status** here (mode, loop rate, recording info).
- `t` — publish timestamp.

**Frames travel raw (uncompressed).** This is meant for localhost, where it's
cheap, and it keeps JPEG encoding off the control loop — the app encodes to JPEG
only when a browser requests a camera stream. Sending raw over a real network
would be bandwidth-heavy, which is why the bridge defaults to `127.0.0.1`.

**Latest-state semantics:** both sockets use a low high-water-mark (`_HWM`), so a
slow or absent subscriber causes old frames to be **dropped** rather than
queued. Consumers always see fresh data; there's no growing backlog.

The `Publisher` runs its **own thread**. The control loop only calls
`publisher.update(obs, meta)` — a cheap reference store — so serialization and
sending never block it. The thread re-sends the latest observation at
`bridge.publish_fps`, which is decoupled from the control-loop rate.

The `Subscriber` runs a thread that receives messages, reconstructs the
observation (`np.frombuffer(...).reshape(...)` per camera), and fills a
`StateBuffer`. If no message arrives within `stale_after` seconds it marks the
buffer disconnected, so the UI reflects a dead bridge.

### Channel 2 — command channel (REQ / REP)

The app **sends** JSON commands; the session server **replies** with an
ack/result. `CommandServer` (REP, in the server) runs `handler(request)` for each
message and always sends exactly one reply (REQ/REP requires it); handler
exceptions are caught and returned as `{"ok": false, "error": ...}`.

`CommandClient` (REQ, in the app) is thread-safe (one in-flight request via a
lock) and uses the **lazy-pirate** pattern: on timeout it rebuilds the socket so
a lost reply can't wedge the REQ state machine, returning a structured error
instead of raising.

Only the session server binds a command channel. Point `app.py` at
`teleop.py --bridge` instead and the stream still works, but commands time out
and the control panel stays hidden.

## The session server state machine

`session_server.py` is the persistent hardware owner behind the app. It runs one
main loop and holds a mode: `idle`, `teleop`, or `recording`.

```
        start_teleop                     start_recording
  idle ───────────────► teleop ─────────────────────────► recording
   ▲   ◄─────────────── stop_teleop                          │
   └──────────────────────────────── stop_recording ────────┘
                                       (+ save_episode / discard_episode
                                          loop within recording)
```

Per main-loop iteration (at `teleop_loop.fps`, or `record.fps` while recording):

1. **Drain commands** — execute any queued commands (mode changes, dataset ops).
2. **Read** `obs = robot.get_observation()`.
3. **Act** — in `teleop`/`recording`, read the leader action and send it to the
   follower; in `recording`, also `dataset.add_frame(...)`.
4. **Publish** `obs` + current status via the bridge.
5. **Sleep** to hold the target rate; update the measured loop Hz.

### Why commands run in the main loop

All hardware and dataset mutation happens in the **one** main-loop thread. The
`CommandServer` thread doesn't touch them directly — it enqueues a
`(command, Event, result)` tuple and waits. The main loop executes it at the top
of the next iteration (≤ one loop period, ~16 ms in idle) and signals the
`Event`. This makes commands feel instant **and** eliminates races: there is
never concurrent access to the serial bus or the dataset writer.

During a blocking dataset operation (`save_episode`, `finalize`) the main loop is
busy, but the **publisher thread keeps streaming** the last frame + status, so
the UI shows a "saving…" state instead of freezing. This mirrors how lerobot's
own recorder behaves.

## The web layer (dashboard.py)

`StateBuffer` is a thread-safe holder for the latest observation: joints, camera
frames, connection status, the session `meta` blob, and timing (it tracks the
rate observations arrive and their staleness). Whoever owns the hardware feeds it
(`update(obs)` / `set_meta(...)` / `set_status(...)`); the FastAPI app only reads
it.

Endpoints (`make_app`):

| Endpoint | Purpose |
|----------|---------|
| `GET /` | The single-page dashboard (HTML/CSS/JS, embedded). |
| `GET /api/events` | **Server-Sent Events** — full state pushed ~30×/s. The primary live channel. |
| `GET /api/state` | One-shot JSON snapshot (fallback / debugging). |
| `GET /api/config` | Safe config subset (ports, ids, cameras, whether controls are enabled). |
| `GET /stream/{cam}` | MJPEG camera stream (`multipart/x-mixed-replace`); JPEG-encoded on demand. |
| `POST /api/command` | Forward a JSON command to the session server (only present when a command client is wired in). |

The browser opens an `EventSource` on `/api/events` for smooth, low-latency
updates, and points `<img>` tags at `/stream/{cam}`. Control buttons update
**optimistically** (the predicted mode shows immediately; the next SSE frame
reconciles with the server's real state).

## Threading model summary

| Process | Threads |
|---------|---------|
| `session_server.py` | main loop (hardware + dataset) · `Publisher` sender · `CommandServer` REP · (video encoder threads inside lerobot during recording) |
| `app.py` | uvicorn server (+ its worker threadpool: SSE & MJPEG generators) · `Subscriber` receiver · `CommandClient` (called from request threads) |
| `monitor.py` | uvicorn server · `RobotPoller` (reads hardware → buffer) |
| `teleop.py --dashboard` | teleop loop (feeds buffer) · uvicorn server |

The GIL is not a bottleneck here: serial reads and OpenCV JPEG encoding both
release it, so the publisher, SSE, and MJPEG threads make progress while the
control loop does I/O.

## Data flow, end to end (recording via the app)

```
leader arm ─get_action()─┐
                         ▼
follower ─get_observation()→ obs ──► dataset.add_frame()  (parquet + video)
                         │      └──► Publisher.update(obs, status)
                         ▼                     │
              robot.send_action()              ▼  ZMQ PUB
                                        app Subscriber → StateBuffer
                                                       │
                                          SSE /api/events + MJPEG /stream
                                                       ▼
                                                   browser
   browser button ─POST /api/command→ app CommandClient ─ZMQ REQ→ CommandServer
                                                       → queue → main loop executes
```

For exactly what `add_frame` writes and the on-disk result, see
[data-format.md](data-format.md).
