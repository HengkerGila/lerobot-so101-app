# Data format & recording mechanism

This document covers, in full: what a recording contains, how each frame is
built and written, how video is encoded, the on-disk dataset layout, and how the
data is read back. Datasets use the **LeRobot v3** format.

## The hierarchy: dataset → episode → frame

- A **dataset** is one recording session (one call to "start recording" through
  "stop recording"), written to its own timestamped folder.
- A dataset contains one or more **episodes** — each episode is one demonstration
  of the task (one "save episode").
- An episode is a time series of **frames**, captured at a fixed rate
  (`record.fps`, default 30 Hz).

## What a frame contains

Every frame, built once per control-loop iteration while recording:

| Field | Source | Type / shape |
|-------|--------|--------------|
| `observation.state` | follower's **measured** joint angles (`robot.get_observation()`) | vector of 6 floats |
| `observation.images.front` | the camera frame | image `(480, 640, 3)`, uint8 RGB |
| `action` | the **commanded** target joint angles (from the leader, via `teleop.get_action()`) | vector of 6 floats |
| `task` | the natural-language task string | string |
| `timestamp` | `frame_index / fps`, added automatically | float (seconds) |
| `frame_index` | index within the episode, added automatically | int |
| `episode_index` | which episode, added automatically | int |
| `index` | global frame index across the dataset | int |
| `task_index` | index into the task table | int |

The six joints, in order, are `shoulder_pan`, `shoulder_lift`, `elbow_flex`,
`wrist_flex`, `wrist_roll`, `gripper`. With `use_degrees: true`, the five arm
joints are in **degrees**; the gripper is a **0–100** position (closed↔open).

If you configure more cameras, each adds an `observation.images.<name>` field.

### `action` vs `observation.state` — the crucial distinction

They share the same six joint names but come from opposite places:

- **`observation.state`** = where the follower *actually is*, read from its motor
  encoders.
- **`action`** = where it was *told to go*, derived from the leader arm you moved.

This pairing — observation in, action out — is exactly what an imitation-learning
policy trains on: given what the robot sees, predict the action to take.

**Subtlety:** the recorded `action` is the *teleop* action, captured **before**
`robot_action_processor` applies any clipping (e.g. `max_relative_target`). So if
that clamp ever limited the motion sent to the motors, the dataset still stores
the unclamped goal. With `max_relative_target: null` (the default) there's no
clipping, so the recorded action equals what was sent. (LeRobot has a `TODO` to
eventually log the actually-sent action; this project matches its current
behavior.)

### How a frame is assembled (in the session server)

```python
obs           = robot.get_observation()                      # → observation.state + images
raw_action    = teleop.get_action()                          # leader's joint angles
teleop_action = teleop_action_processor((raw_action, obs))   # identity by default
robot_action  = robot_action_processor((teleop_action, obs)) # clipping etc.
robot.send_action(robot_action)                              # command the follower

obs_frame = build_dataset_frame(dataset.features, robot_observation_processor(obs), prefix="observation")
act_frame = build_dataset_frame(dataset.features, teleop_action,                    prefix="action")
dataset.add_frame({**obs_frame, **act_frame, "task": task})
```

`build_dataset_frame` selects exactly the fields declared in `dataset.features`
(built at creation time from `robot.observation_features` and
`robot.action_features`).

## The recording mechanism, tier by tier

Recording is delegated to lerobot's `DatasetWriter`. There are three tiers.

### 1. `add_frame` → in-memory episode buffer

Per frame, almost nothing is written durably — values are appended to an
in-memory buffer, with one exception for video:

| Feature kind | What `add_frame` does |
|--------------|------------------------|
| Low-dim (`observation.state`, `action`) | append the value to a Python list in the buffer |
| Video key, with `streaming_encoding: true` (your config) | feed the frame **straight to a live video encoder**; store `None` as a placeholder |
| Image/video without streaming | write a temporary PNG (async writer threads); store the file path |

So during an episode, RAM holds the numeric time series while camera frames are
already being piped into the H.264 encoder in the background (controlled by
`record.encoder_threads`).

### 2. `save_episode` → flush to disk

When you save an episode (the **Save episode** button, or `→` in `record.py`):

1. stacks the buffered lists into arrays and computes `index`, `episode_index`,
   `task_index`;
2. writes the low-dim data as a **Parquet** file;
3. finalizes the episode's **mp4** video file(s);
4. updates metadata; then
5. **resets the buffer** for the next episode.

This is the step that briefly pauses the control loop while video flushes — the
app shows a "saving…" indicator during it.

`clear_episode_buffer` (the **Discard** button, or `←`) throws the buffer away,
deletes temp images, and resets the frame index — nothing is written.

### 3. `finalize` → write footer metadata

Called on **Stop recording** / shutdown. It flushes the encoders and writes the
Parquet footer metadata. **This is mandatory** — lerobot's docstring is explicit
that without it *"the dataset will be invalid."* The session server calls it in
both `_stop_recording()` and `_shutdown()`.

> **An unsaved (in-progress) episode lives only in RAM** and is dropped on Stop
> or shutdown. Save it first if you want to keep it.

## On-disk layout

Each session gets a unique, timestamped folder so repeated runs never collide:

```
<record.root>_<YYYYMMDD_HHMMSS>/
├── meta/
│   ├── info.json        # fps, the feature schema, robot_type, paths
│   ├── stats.json       # per-feature normalization statistics (min/max/mean/std)
│   ├── tasks.parquet    # task strings ↔ task_index
│   └── episodes/chunk-000/file-000.parquet   # per-episode index (lengths, offsets)
├── data/
│   └── chunk-000/file-000.parquet            # the numeric time series
└── videos/
    └── observation.images.front/chunk-000/file-000.mp4   # one stream per camera
```

- **Parquet** holds the low-dimensional, columnar data: `timestamp`,
  `frame_index`, `episode_index`, `index`, `task_index`, `observation.state`
  (6-vector), `action` (6-vector). Columnar storage compresses these slowly
  varying signals well and lets training read only the columns it needs. See the
  note below on why Parquet.
- **mp4** holds each camera stream, referenced from the table by timestamp, since
  video codecs compress images far better than a generic table.
- Episodes are packed into **chunked** files (`chunk-NNN/file-NNN`) rather than
  one file per episode.

### Why Parquet?

Parquet is an open **columnar** table format: it stores each column's values
together rather than row-by-row. That gives strong compression for slowly varying
signals (a joint angle drifting frame to frame), lets a reader load only the
columns it needs, and carries a self-describing typed schema plus per-column
statistics. It's first-class in pandas, PyArrow, Polars, DuckDB, and HuggingFace
`datasets` — which is why lerobot uses it for the motion signals.

## Naming & uploading

- The dataset's `repo_id` (and its folder) are stamped with the start time, e.g.
  `you/so101_demo_20260622_201500`. This keeps `repo_id` unique on the Hub and
  the folder unique on disk.
- The session server does **not** upload automatically. After a session, push
  with `make upload` (`scripts/upload_dataset.py`), which reads `record.repo_id` /
  `record.root` (override with `--repo_id` / `--local_dir`). Authenticate once
  with `huggingface-cli login`.
- `record.py` (the standalone recorder) *can* auto-push if `record.push_to_hub:
  true`.

## Reading the data back

The same `LeRobotDataset` reads it for training. `dataset[i]` returns one frame
with everything aligned: it pulls the row's numbers from Parquet and **decodes
the matching video frame on demand** by timestamp, applies any image transforms,
and can expand delta-timestamp windows (for models that need a few past/future
frames).

Quick peek at the numeric side after recording:

```python
import pandas as pd
df = pd.read_parquet("data/so101_demo_.../data/chunk-000/file-000.parquet")
print(df.columns.tolist(), len(df))
print(df[["timestamp", "observation.state", "action"]].head())
```

Or load the whole dataset the lerobot way:

```python
from lerobot.datasets import LeRobotDataset
ds = LeRobotDataset("you/so101_demo_...", root="data/so101_demo_...")
print(ds.num_episodes, ds.num_frames, ds.features.keys())
frame = ds[0]   # dict of tensors: observation.state, observation.images.front, action, ...
```

## Where this is configured

All of the above is governed by the `record:` section of `config.yaml` — `fps`,
`repo_id`, `single_task`, `root`, `num_episodes`, `episode_time_s`,
`reset_time_s`, `streaming_encoding`, `encoder_threads`, `push_to_hub`, etc. See
[configuration.md](configuration.md#record) for every field.
