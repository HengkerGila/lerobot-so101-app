# Application & session control

Run a whole teleop + recording session from the browser, instead of launching
scripts by hand. Two processes:

```bash
make server     # terminal 1: owns the arm, runs the session state machine
make app        # terminal 2: serves the UI + control panel at :8000
```

`app.py` owns no hardware, so you can restart it freely while the server keeps
running (and vice versa). They talk over two ZMQ channels (configured under
`bridge:`): an observation **stream** (server → app, carries the live view +
session status) and a **command** channel (app → server, for button clicks).
For the full internals — the bridge protocol, the state machine, and the
threading model — see [architecture.md](architecture.md).

## Modes & controls

The server is always in one mode; the live view works in all of them. The
control panel shows the relevant buttons per mode:

| Mode | What it does | Buttons |
|------|--------------|---------|
| `idle` | View only; follower holds position | Start teleop, Start recording |
| `teleop` | Leader drives the follower | Stop teleop, Start recording |
| `recording` | Teleop **+** every frame saved to a dataset | Save episode, Discard episode, Stop recording |

- **Start recording** asks for a task description (defaults to
  `record.single_task`) and creates a fresh dataset.
- **Save episode** saves the current episode and begins the next;
  **Discard** re-records it; **Stop recording** finalizes the dataset → idle.

The panel shows the dataset name, episodes saved vs. `record.num_episodes`, and
the in-progress frame count.

## Recording notes

- Each session gets a unique, timestamped dataset folder (e.g.
  `…/so101_demo_20260622_201500`), so sessions never collide on disk. Encoding
  and fps come from the `record:` config.
- An **unsaved** episode is dropped on Stop / shutdown — Save it first.
- Save/Stop briefly pause the loop to flush video (the UI shows "saving…").
- Upload isn't automatic — push afterward with `make upload`.

## Pairing & limitations

- Point `app.py` at `teleop.py --bridge` instead for a **view-only** app (no
  command channel → the control panel stays hidden).
- No per-joint jogging from the browser — control is session-level. The leader
  arm is still how you move the follower.
- Single client, no auth/TLS — keep it on `127.0.0.1` or a trusted LAN.

## Command protocol

To script the server directly, send JSON over the command channel
(`bridge.command_address`); each reply is `{"ok": true, "status": {…}}` or
`{"ok": false, "error": "…"}`:

`get_status` · `start_teleop` · `stop_teleop` ·
`start_recording {single_task?, num_episodes?, repo_id?}` · `save_episode` ·
`discard_episode` · `stop_recording`
