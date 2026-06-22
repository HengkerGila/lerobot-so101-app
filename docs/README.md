# Documentation

Complete reference for the SO-101 teleoperation & recording system. For a
high-level overview of what the project is and what it records, see the
[root README](../README.md).

## Contents

| Doc | What's in it |
|-----|--------------|
| [architecture.md](architecture.md) | The whole system: processes, hardware ownership, the ZMQ bridge (both channels), the web layer, the threading model, and how every script fits together. Start here to understand *how* it works. |
| [setup.md](setup.md) | Install, detect ports & cameras, calibrate the arms. |
| [usage.md](usage.md) | Run teleoperation, record datasets, upload to the Hub, troubleshooting. |
| [monitor.md](monitor.md) | The web dashboard: the three ways to view it, endpoints, configuration. |
| [app.md](app.md) | The application & session control: modes, controls, the command protocol, responsiveness. |
| [data-format.md](data-format.md) | Exactly what is recorded, the per-frame mechanism, video encoding, the on-disk dataset format, and reading data back. |
| [configuration.md](configuration.md) | Every field in `config.yaml`, grouped by section, and how it maps to code. |

## Conventions

- Everything is driven by **`configs/config.yaml`** — the scripts are never
  edited. See [configuration.md](configuration.md).
- Every workflow has a **`make`** shortcut (`make help`); each just runs the
  matching script in `.venv`.
- All scripts share a loader (`scripts/_config.py`) that reads the YAML and puts
  LeRobot on `sys.path` before importing it.
