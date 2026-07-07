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

| Running Script | Makefile Target | Command Executed / File Location | Role |
|---|---|---|---|
| `./scripts/find.sh` | `make find` | `src/modules/find_hardware.py` | Detect serial ports and cameras |
| `./scripts/port-leader.sh` | `make port-leader` | `src/modules/find_hardware.py --detect-port leader --write` | Detect the leader port (unplug/replug) and save it |
| `./scripts/port-follower.sh`| `make port-follower` | `src/modules/find_hardware.py --detect-port follower --write`| Detect the follower port (unplug/replug) and save it |
| `./scripts/cameras.sh` | `make cameras` | `src/modules/find_hardware.py --write-cameras` | Detect cameras and save them to the config |
| `./scripts/calibrate-leader.sh`| `make calibrate-leader`| `src/modules/calibrate.py --device leader` | Calibrate the leader arm |
| `./scripts/calibrate-follower.sh`| `make calibrate-follower`| `src/modules/calibrate.py --device follower` | Calibrate the follower arm |
| `./scripts/teleop.sh` | `make teleop` | `src/modules/teleop.py` | Real-time teleoperation (leader → follower) |
| `./scripts/record.sh` | `make record` | `src/modules/record.py` | Record a dataset with LeRobot's recorder |
| `./scripts/upload.sh` | `make upload` | `src/modules/upload_dataset.py` | Push a local dataset to the HuggingFace Hub |
| `./scripts/monitor.sh` | `make monitor` | `src/modules/monitor.py` | Standalone dashboard (run when nothing else owns the arm) |
| `./scripts/server.sh` | `make server` | `src/app/session_server.py` | Session server: owns the arm, controllable from the app |
| `./scripts/app.sh` | `make app` | `src/app/app.py` | The application UI (pair with `make server` in another terminal) |

*Shared Internals:* `src/modules/bridge.py` (ZMQ bridge) and `src/cfg/_config.py` (config loader).

## Installation

This project targets **LeRobot 0.5.2**, which was never published to PyPI (PyPI
tops out at 0.5.1). You therefore need a **local LeRobot source checkout**, which
the setup script installs in editable mode. The path to that checkout is set in
**one place — `lerobot_src` in `configs/config.yaml`** — and nowhere else:

```bash
# 1. Clone LeRobot repository (optional)
# Skip step 1 and step 2 and jump to step 3 to default the LeRobot repository installation to repository_root/lerobot
git clone https://github.com/huggingface/lerobot.git /path/to/lerobot

# 2. Set lerobot_src in configs/config.yaml to that checkout's src/ dir (optional) 
# e.g. lerobot_src: /path/to/lerobot/src

# 3. Run setup with your preferred environment manager ('uv' or 'pip')
make install ENV=uv   # using uv (under the hood: ./scripts/setup.sh uv)
# or
make install ENV=pip  # using pip (under the hood: ./scripts/setup.sh pip)
```

The setup script reads `lerobot_src` from `config.yaml`, then installs:

- `<checkout>[hardware,feetech,dataset]` (editable) — LeRobot 0.5.2 plus the
  SO-101 extras (`hardware` → pyserial/pynput, `feetech` → the servo SDK,
  `dataset` → datasets/pandas/pyarrow/torchcodec). This also pulls in torch,
  numpy and `opencv-python-headless`.
- everything in `requirements.txt`: `fastapi` + `uvicorn` (web monitor / app),
  `pyzmq` (the teleop↔app bridge) and `PyYAML` (the config loader).

So to point at a different checkout, you only edit `lerobot_src` in
`config.yaml` — the setup script derives the editable-install path from it. Verify:

```bash
.venv/bin/python -c "import lerobot; print(lerobot.__version__)"   # 0.5.2
```

> Do **not** add `opencv-python` to `requirements.txt` — LeRobot installs
> `opencv-python-headless`, and having both causes import conflicts.

## Quick start

```bash
# 1. Setup (choose uv or pip), uv is recommended
make install ENV=uv                       # create .venv + install deps using uv

# 2. Hardware setup (once)
make port-leader port-follower cameras    # detect hardware → config
make calibrate-leader calibrate-follower  # calibrate both arms

# 3. Usage
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
