# Setup

## 1. Install

```bash
make install        # creates .venv and installs requirements.txt
```

This pulls LeRobot (extras: `hardware`, `feetech`, `dataset`) plus the web app
deps (`fastapi`, `uvicorn`, `pyzmq`) and `PyYAML`. Verify:

```bash
.venv/bin/python -c "import lerobot; print(lerobot.__version__)"   # 0.5.2
```

**Local LeRobot checkout (optional):** to run against a clone, point
`lerobot_src` in `config.yaml` at its `src/` dir (the scripts prepend it to
`sys.path`); set it to `null` to use the pip-installed package.

## 2. Plug in the arms

Connect both arms via USB and power the follower's servos. On Linux each appears
as `/dev/ttyUSB*` or `/dev/ttyACM*`. On permission errors, add yourself to the
`dialout` group and re-login:

```bash
sudo usermod -aG dialout $USER
```

## 3. Find your hardware

```bash
make find                          # list ports + cameras (no changes)
make port-leader port-follower     # detect each arm by unplug/replug, save it
make cameras                       # detect cameras, save them
```

The port detection asks you to unplug one arm and watches which port disappears,
then writes it to `config.yaml`. Camera detection writes every `/dev/video*` it
finds (the first becomes `front`).

## 4. Calibrate the arms

Calibration maps each servo's encoder range to joint angles, saved under
`~/.cache/huggingface/lerobot/calibration/` by the config `id`. **Leader first:**

```bash
make calibrate-leader
make calibrate-follower
```

Follow the prompts (move each joint through its full range, then the rest pose).
Recalibrate only if you re-assemble an arm or change its `id`.

Next: [usage.md](usage.md).
