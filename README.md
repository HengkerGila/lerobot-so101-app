# SO-101 Teleoperation & Data Recording

This project turns a pair of **SO-101 robot arms** into a teleoperation and
demonstration-recording rig, with a browser application for live monitoring and
session control. It's a thin, configuration-driven layer on top of
[HuggingFace LeRobot](https://github.com/huggingface/lerobot).

> **This file is the overview.** For the complete, detailed documentation of
> every part of the system, see **[docs/](docs/README.md)**.

## What is this about?

You have two identical arms:

- a **leader** arm you move by hand, and
- a **follower** arm that mirrors it in real time.

By moving the leader, you drive the follower (**teleoperation**). When you do
this to perform a task — picking something up, placing it in a bin — you can
**record** the motion and camera footage into a dataset. Collect enough of these
demonstrations and you can train a robot policy to perform the task on its own
(imitation learning). This project handles the teleoperation, the recording, and
the dataset upload — plus a web app to watch and control it all.

Everything is driven by one file, **`configs/config.yaml`**; the scripts never
need editing. Run anything with `make <target>` (see `make help`).

```
  ┌──────────┐  move by hand   ┌──────────┐
  │  LEADER  │ ──────────────► │ FOLLOWER │ ──► cameras + joint sensors
  │   arm    │                 │   arm    │
  └──────────┘                 └────┬─────┘
                                    │ observations + your commands
                                    ▼
                          recorded as a dataset  ──►  HuggingFace Hub
                                    │
                                    ▼
                           live web app (watch + control)
```

## What data does it record?

A recording is a **dataset** of one or more **episodes** (one demonstration =
one episode). Each episode is a time series of **frames** captured at a fixed
rate (`record.fps`, default 30 Hz). Every frame holds:

| Field | What it is | Shape |
|-------|-----------|-------|
| `observation.state` | the follower's **measured** joint angles | 6 floats |
| `observation.images.front` | the camera frame at that instant | 480×640×3 image |
| `action` | the **commanded** target joint angles (from the leader) | 6 floats |
| `task` | the natural-language task description | string |
| `timestamp`, `frame_index`, `episode_index`, `index`, `task_index` | bookkeeping added automatically | ints/float |

The six joints are `shoulder_pan`, `shoulder_lift`, `elbow_flex`, `wrist_flex`,
`wrist_roll`, `gripper`. The five arm joints are in **degrees**; the gripper is a
0–100 position.

**`action` vs `observation.state` is the key distinction:**

- **`observation.state`** — where the follower *actually is* (measured from its
  motors).
- **`action`** — where it was *told to go*, derived from the leader arm you were
  moving.

Pairing "what the robot saw" (`observation.*`) with "what you commanded"
(`action`) is exactly what an imitation-learning policy trains on.

### How it's stored on disk

Datasets are written in **LeRobot v3 format** under `record.root` (a timestamped
folder per session). Data is split by type for efficiency:

```
<root>/
├── meta/                       # info.json, stats.json, tasks, episode index
├── data/  chunk-000/file-000.parquet      # the numeric time series (state, action, timestamps)
└── videos/ observation.images.front/chunk-000/file-000.mp4   # the camera stream
```

- **Low-dimensional signals** (joint state, action, timestamps) → **Parquet**
  (compact columnar tables, fast to load for training).
- **Camera frames** → **mp4 video** (codecs compress images far better than a
  table), referenced by timestamp.

Full details — the per-frame mechanism, the episode buffer, video encoding, and
how the data is read back — are in
**[docs/data-format.md](docs/data-format.md)**.

## The pieces

| Script | Role |
|--------|------|
| `scripts/teleop.py` | Real-time teleoperation (leader → follower) |
| `scripts/record.py` | Record a dataset with lerobot's recorder |
| `scripts/session_server.py` | Hardware daemon: idle / teleop / recording, controlled by the app |
| `scripts/app.py` | The browser application: live view + session control |
| `scripts/monitor.py` | Standalone live dashboard |
| `scripts/calibrate.py`, `scripts/find_hardware.py` | One-time setup |
| `scripts/upload_dataset.py` | Push a dataset to the HuggingFace Hub |
| `scripts/dashboard.py`, `scripts/bridge.py`, `scripts/_config.py` | Shared internals (web UI, ZMQ bridge, config loader) |

## Installation

This project targets **LeRobot 0.5.2**, which was never published to PyPI (PyPI
tops out at 0.5.1). You therefore need a **local LeRobot source checkout**, which
`make install` installs in editable mode. The path to that checkout is set in
**one place — `lerobot_src` in `configs/config.yaml`** — and nowhere else:

```bash
# 1. Clone LeRobot somewhere
git clone https://github.com/huggingface/lerobot.git /path/to/lerobot

# 2. Set lerobot_src in configs/config.yaml to that checkout's src/ dir, e.g.
#    lerobot_src: /path/to/lerobot/src

# 3. Create the .venv and install all dependencies (LeRobot + web app + bridge)
make install
```

`make install` reads `lerobot_src` from `config.yaml`, then installs:

- `<checkout>[hardware,feetech,dataset]` (editable) — LeRobot 0.5.2 plus the
  SO-101 extras (`hardware` → pyserial/pynput, `feetech` → the servo SDK,
  `dataset` → datasets/pandas/pyarrow/torchcodec). This also pulls in torch,
  numpy and `opencv-python-headless`.
- everything in `requirements.txt`: `fastapi` + `uvicorn` (web monitor / app),
  `pyzmq` (the teleop↔app bridge) and `PyYAML` (the config loader).

So to point at a different checkout, you only edit `lerobot_src` in
`config.yaml` — the Makefile derives the editable-install path from it. Verify:

```bash
.venv/bin/python -c "import lerobot; print(lerobot.__version__)"   # 0.5.2
```

> Do **not** add `opencv-python` to `requirements.txt` — LeRobot installs
> `opencv-python-headless`, and having both causes import conflicts.

## Quick start

```bash
make install                              # create .venv + install deps (see above)
make port-leader port-follower cameras    # detect hardware → config (once)
make calibrate-leader calibrate-follower  # calibrate both arms (once)

make teleop                               # drive the follower with the leader
make record                               # record a dataset (set record.* first)

# or run the full browser application:
make server                               # terminal 1 (owns the hardware)
make app                                  # terminal 2 → http://localhost:8000
```

## Documentation

The `docs/` folder is the complete reference — architecture, every script,
the data format, configuration, and the web app:

| Doc | Contents |
|-----|----------|
| [docs/README.md](docs/README.md) | Documentation index |
| [docs/architecture.md](docs/architecture.md) | Full system architecture, processes, the ZMQ bridge, threading model |
| [docs/setup.md](docs/setup.md) | Install, hardware detection, calibration |
| [docs/usage.md](docs/usage.md) | Teleoperation, recording, uploading |
| [docs/monitor.md](docs/monitor.md) | Web dashboard and the ways to view it |
| [docs/app.md](docs/app.md) | The application and session control |
| [docs/data-format.md](docs/data-format.md) | What is recorded, the dataset format, on-disk layout |
| [docs/configuration.md](docs/configuration.md) | Every field in `config.yaml` |
