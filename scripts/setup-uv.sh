#!/bin/bash

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)
PROJECT_ROOT_DIR=$(cd -- "$SCRIPT_DIR/.." &> /dev/null && pwd)
LEROBOT_SRC_DIR_REL=$(grep '^lerobot_src:' $PROJECT_ROOT_DIR/configs/config.yaml | awk -F: '{print $2}' | awk '{print $1}')
LEROBOT_DIR_REL=$(grep '^lerobot_dir:' $PROJECT_ROOT_DIR/configs/config.yaml | awk -F: '{print $2}' | awk '{print $1}')

LEROBOT_SRC_DIR=$(cd -- "$LEROBOT_SRC_DIR_REL" &> /dev/null && pwd)
LEROBOT_DIR=$(cd -- "$LEROBOT_DIR_REL" &> /dev/null && pwd)

echo "lerobot_src directory: $LEROBOT_SRC_DIR"

if command -v ffmpeg &> /dev/null; then
    echo "FFmpeg is already installed, proceeding with the setup."
else
    echo "Error: FFmpeg is not installed. Please install FFmpeg to proceed." >&2
    exit 1
fi

if [ ! -d "$LEROBOT_DIR" ] && [ ! -d "./lerobot" ]; then
    git clone https://github.com/huggingface/lerobot.git ${LEROBOT_DIR:-"./lerobot"}
    cd ${LEROBOT_DIR:-"./lerobot"}
    uv venv --python 3.12
    uv pip install -e .
fi

if [ ! -f "$PROJECT_ROOT_DIR/pyproject.toml" ]; then
    uv init $PROJECT_ROOT_DIR --python 3.12 --bare
fi

if [ ! -d $PROJECT_ROOT_DIR/.venv ]; then
    uv venv --python 3.12
fi

cd "$PROJECT_ROOT_DIR"
uv add "${LEROBOT_DIR:-"./lerobot"}[feetech, hardware, dataset]"
uv add -r requirements.txt