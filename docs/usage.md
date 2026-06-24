# Usage

All commands read `configs/config.yaml` (see [configuration.md](configuration.md)).
Each `make` target runs the matching script in the `scripts/` directory — use either form.

## Teleoperation

```bash
make teleop          # or: ./scripts/teleop.sh
```

Move the leader arm to drive the follower. **Ctrl+C** to stop (torque is
released on disconnect). Set `teleop_loop.display_data: true` to print live motor
values and open the Rerun viewer. Use teleop to confirm the arms move together
**before** recording.

## Recording a dataset

```bash
make record          # or: ./scripts/record.sh
```

Set these under `record:` in the config first:

- `repo_id` — `"<hf-username>/<dataset-name>"`
- `single_task` — short description of the task
- `num_episodes`, `episode_time_s`, `reset_time_s` — how much to record
- `root` — local save dir (e.g. `data/so101_demo`)

Each episode is announced, recorded for `episode_time_s`, then you get
`reset_time_s` to reset the scene. While recording:

| Key | Action |
|-----|--------|
| **→** | Save current episode, start the next |
| **←** | Discard and re-record the current episode |
| **Esc** | Stop (keeps episodes already saved) |

The dataset is written in LeRobot v3 format (parquet + video) to `record.root`.
For exactly what each frame contains and the on-disk layout, see
[data-format.md](data-format.md).

> To record from the browser instead — start/stop episodes with buttons — use
> the application (`make server` + `make app`). See [app.md](app.md).

## Uploading to the Hub

```bash
.venv/bin/huggingface-cli login   # once
make upload                       # uses record.root / record.repo_id
```

Override the defaults if needed:

```bash
./scripts/upload.sh --local_dir data/so101_demo --repo_id you/so101_demo
```

## Live monitoring

`make monitor` serves a browser dashboard at http://localhost:8000. See
[monitor.md](monitor.md) for the ways to view, and [app.md](app.md) for
controlling a session from the page.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `Permission denied: '/dev/ttyUSB0'` | `sudo usermod -aG dialout $USER`, then re-login |
| Wrong arm moves / ports swapped | Re-run `make port-leader` / `make port-follower` |
| `Record loop running slower than target FPS` | Lower camera resolution/FPS or `record.fps` |
| Camera opens but image is black | Check `index_or_path`; re-run `make cameras` |
| Calibration seems off | Re-run `make calibrate-leader` / `calibrate-follower` |
