# Setup

## 1. Install

This project targets **LeRobot 0.5.2**, which is not on PyPI (latest there is
0.5.1), so it is installed from a **local source checkout** in editable mode.
Clone LeRobot, set its path in `config.yaml`, then install:

```bash
git clone https://github.com/huggingface/lerobot.git /path/to/lerobot
# set lerobot_src: /path/to/lerobot/src in configs/config.yaml
make install ENV=uv        # creates .venv, installs LeRobot + requirements.txt using uv
# or
make install ENV=pip       # creates .venv, installs LeRobot + requirements.txt using pip
```

`make install` calls `scripts/setup.sh` with the specified environment manager to read `lerobot_src` from `config.yaml` and install
`<checkout>[hardware,feetech,dataset]` editable (LeRobot 0.5.2 + the SO-101
extras `hardware`, `feetech`, `dataset`), then the web app deps from
`requirements.txt` (`fastapi`, `uvicorn`, `pyzmq`) and `PyYAML`. Verify:

```bash
.venv/bin/python -c "import lerobot; print(lerobot.__version__)"   # 0.5.2
```

The checkout path lives in **one place** — `lerobot_src` in `config.yaml` (the
scripts also prepend it to `sys.path`). Change it there to use a different
checkout; nothing else references the path.

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
