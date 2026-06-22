# Web monitor

A browser dashboard (http://localhost:8000) showing live camera streams, joint
positions, and connection status for the follower arm.

## One process owns the devices

The cameras and the motor serial bus can each be opened by **one process at a
time**. So pick the right way to feed the dashboard depending on what's running:

| Run | Owns hardware | Use when |
|-----|---------------|----------|
| `make monitor` | the monitor | Nothing else is using the arm — just look. |
| `teleop.py --dashboard` | teleop | You want to watch *while* teleoperating (one process). |
| `make server` + `make app` | the session server | You want a separate UI **and** session control. See [app.md](app.md). |

All serve the identical page; they differ only in who feeds it. Running two
hardware owners at once fails (serial "multiple access on port", or "Failed to
open OpenCVCamera") — that's the rule above, not a bug.

`make monitor` retries every couple of seconds, so it reconnects on its own once
another process releases the hardware.

## How it works

`scripts/dashboard.py` owns no hardware — it holds a thread-safe `StateBuffer`
(latest joints + frames + status) and a FastAPI app that serves a view of it.
Whoever owns the hardware feeds the buffer: `monitor.py` polls it directly,
`teleop.py --dashboard` feeds it from the teleop loop, and `app.py` fills it from
the ZMQ bridge (`scripts/bridge.py`). Endpoints: `/stream/<camera>` (MJPEG),
`/api/events` (Server-Sent Events — live state pushed ~30×/s), `/api/state`
(one-shot JSON), `/api/config`, and `/api/command` (session control).

Camera names come from the `cameras:` config, so whatever you configure (or
`make cameras` detects) shows up automatically. For the bridge protocol and the
full threading model behind all this, see [architecture.md](architecture.md).

## Configuration

Settings live in the `webui:` block of `config.yaml`
(see [configuration.md](configuration.md#webui)). With `host: 0.0.0.0` the page
is reachable at `http://<machine-ip>:8000`; use `127.0.0.1` to keep it local.
There's no auth/TLS — keep it on a trusted LAN.
