#!/bin/bash
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)
PROJECT_ROOT_DIR=$(cd -- "$SCRIPT_DIR/.." &> /dev/null && pwd)

if [ ! -d "$PROJECT_ROOT_DIR/.venv" ]; then
    echo "Error: Virtual environment not found at $PROJECT_ROOT_DIR/.venv" >&2
    echo "Please run './scripts/setup.sh <uv|pip>' first to set up the environment." >&2
    exit 1
fi

"$PROJECT_ROOT_DIR/.venv/bin/python" "$PROJECT_ROOT_DIR/src/modules/find_hardware.py" --detect-port leader --write "$@"
