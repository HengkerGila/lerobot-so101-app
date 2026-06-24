# Configuration reference

All scripts read **`configs/config.yaml`**. This is the only file you should
need to edit. Below is every field, grouped by section.

The loader (`scripts/_config.py`) reads this YAML, puts `lerobot_src` on the
Python path, and builds the typed LeRobot config objects the scripts consume.

---

## `lerobot_src`

```yaml
lerobot_src: /path/to/lerobot/src
```

Path to the LeRobot source checkout's `src/` dir. This is the **single source**
for the checkout location: it is added to `sys.path` before any `lerobot` import,
**and** `make install` derives the checkout root from it (the parent dir) to run
the editable `pip install <checkout>[hardware,feetech,dataset]`. Change it here
and nowhere else if you move the checkout.

## `ports`

```yaml
ports:
  leader: /dev/ttyUSB0
  follower: /dev/ttyUSB1
```

Serial ports for the two arms. Auto-fill with:

```bash
python scripts/find_hardware.py --detect-port leader --write
python scripts/find_hardware.py --detect-port follower --write
```

## `robot` (follower)

```yaml
robot:
  id: so101_follower
  max_relative_target: null
  use_degrees: true
```

| Field | Meaning |
|-------|---------|
| `id` | Calibration profile name (under `~/.cache/huggingface/lerobot`). |
| `max_relative_target` | Safety cap (degrees) on how far any motor may move in one command. `null` = no cap. Set e.g. `15` while testing. |
| `use_degrees` | Report/accept joint values in degrees. Keep `true` for SO-101. |

## `teleop` (leader)

```yaml
teleop:
  id: so101_leader
  use_degrees: true
```

| Field | Meaning |
|-------|---------|
| `id` | Calibration profile name for the leader arm. |
| `use_degrees` | Keep `true` to match the follower. |

## `cameras`

```yaml
cameras:
  front:
    index_or_path: 0
    width: 640
    height: 480
    fps: 30
```

A map of `name → camera settings`. The names become the observation keys in the
recorded dataset (e.g. `observation.images.front`). Set to `{}` to disable
cameras. Auto-fill with `python scripts/find_hardware.py --write-cameras`.

| Field | Meaning |
|-------|---------|
| `index_or_path` | `/dev/videoN` index (or a path). |
| `width`, `height` | Capture resolution. |
| `fps` | Capture frame rate (should be ≥ `record.fps`). |

> All cameras are OpenCV/USB. For Intel RealSense you'd swap in
> `RealSenseCameraConfig` inside `_config.build_camera_configs`.

## `teleop_loop`

```yaml
teleop_loop:
  fps: 60
  display_data: false
```

| Field | Meaning |
|-------|---------|
| `fps` | Control-loop rate for `teleop.py`. |
| `display_data` | `true` prints live motor values and opens the Rerun viewer. |

## `webui`

```yaml
webui:
  host: 0.0.0.0
  port: 8000
  poll_fps: 30
  jpeg_quality: 80
```

Settings for the web monitor — used by both `scripts/monitor.py` and
`scripts/teleop.py --dashboard`. All optional — sensible defaults are used if
the section is missing.

| Field | Meaning |
|-------|---------|
| `host` | Bind address. `0.0.0.0` = reachable from other machines; `127.0.0.1` = local only. |
| `port` | HTTP port for the dashboard. |
| `poll_fps` | How often the monitor reads the arm/cameras (also caps stream FPS). |
| `jpeg_quality` | JPEG quality (1–100) for the MJPEG camera streams. |

## `bridge`

```yaml
bridge:
  address: tcp://127.0.0.1:5555
  command_address: tcp://127.0.0.1:5556
  publish_fps: 30
```

Settings for the ZMQ bridge that connects the hardware owner
(`teleop.py --bridge` or `session_server.py`) to `app.py`. All optional.

| Field | Meaning |
|-------|---------|
| `address` | Observation stream endpoint (PUB/SUB). The hardware owner binds it, the app connects to it. `127.0.0.1` keeps it local; use a routable address (e.g. `tcp://0.0.0.0:5555`) only on a trusted LAN. |
| `command_address` | Command channel endpoint (REQ/REP). `session_server.py` binds it; `app.py` sends control commands to it. Only used for session control. |
| `publish_fps` | How often observations are published. Decoupled from the control-loop rate — publishing is throttled in a background thread. |

> Frames are sent **raw** (uncompressed) over the bridge, which is cheap on
> localhost and keeps JPEG encoding off the control loop; the app encodes to
> JPEG only when a browser requests a stream. Sending raw over a network link
> would be bandwidth-heavy — that's why the bridge defaults to localhost.

## `record`

```yaml
record:
  repo_id: your_hf_username/so101_demo
  single_task: pick up the object and place it in the bin
  num_episodes: 10
  episode_time_s: 60
  reset_time_s: 10
  fps: 30
  display_data: false
  play_sounds: true
  root: data/so101_demo   # relative to the repo root, or an absolute path
  push_to_hub: false
  private: false
  tags: null
  streaming_encoding: true
  encoder_threads: 2
```

| Field | Meaning |
|-------|---------|
| `repo_id` | `"<username>/<dataset-name>"` — dataset identity on the Hub. |
| `single_task` | Natural-language task description stored with each frame. |
| `num_episodes` | How many episodes to record. |
| `episode_time_s` | Seconds recorded per episode. |
| `reset_time_s` | Seconds between episodes to reset the scene. |
| `fps` | Control + dataset frequency. Cameras must keep up with this. |
| `display_data` | `true` opens the Rerun viewer during recording. |
| `play_sounds` | Speak episode/reset prompts aloud. |
| `root` | Local directory for the dataset. `null` = HF cache. |
| `push_to_hub` | Upload automatically when recording finishes. |
| `private` | Make the uploaded repo private. |
| `tags` | Optional list of Hub tags, e.g. `[so101, manipulation]`. |
| `streaming_encoding` | Encode video while recording (faster saves). |
| `encoder_threads` | Threads for the video encoder. |

---

## How it maps to code

`scripts/_config.py` turns the YAML into LeRobot objects:

| YAML section | Built object |
|--------------|--------------|
| `ports.follower` + `robot` + `cameras` | `SOFollowerRobotConfig` |
| `ports.leader` + `teleop` | `SOLeaderTeleopConfig` |
| `cameras` | `{name: OpenCVCameraConfig}` |
| `record` | `DatasetRecordConfig` |
| `webui` | read directly by `scripts/monitor.py`, `scripts/app.py`, and `scripts/teleop.py --dashboard` |
| `bridge` | read directly by `scripts/app.py`, `scripts/session_server.py`, and `scripts/teleop.py --bridge` |

If you need a field not exposed here, add it to the relevant `build_*` function
in `_config.py` and to this document.
