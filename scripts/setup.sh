#!/bin/bash

# Parse arguments
if [ "$#" -lt 1 ]; then
    echo "Usage: $0 <uv|pip>" >&2
    exit 1
fi

ENV_TYPE=$1

if [ "$ENV_TYPE" != "uv" ] && [ "$ENV_TYPE" != "pip" ]; then
    echo "Error: Invalid environment type '$ENV_TYPE'. Must be 'uv' or 'pip'." >&2
    exit 1
fi

if [ "$ENV_TYPE" = "uv" ]; then
    if ! command -v uv &> /dev/null; then
        echo "Error: 'uv' is not installed or not in PATH." >&2
        exit 1
    fi
else
    if ! command -v python3 &> /dev/null; then
        echo "Error: 'python3' is not installed or not in PATH." >&2
        exit 1
    fi
fi

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
    if [ "$ENV_TYPE" = "uv" ]; then
        uv venv --python 3.12
        uv pip install -e .
    else
        python3 -m venv .venv
        .venv/bin/pip install -e .
    fi
    cd "$PROJECT_ROOT_DIR"
fi

if [ "$ENV_TYPE" = "uv" ]; then
    if [ ! -f "$PROJECT_ROOT_DIR/pyproject.toml" ]; then
        uv init $PROJECT_ROOT_DIR --python 3.12 --bare
    fi

    if [ ! -d $PROJECT_ROOT_DIR/.venv ]; then
        cd "$PROJECT_ROOT_DIR"
        uv venv --python 3.12
    fi

    cd "$PROJECT_ROOT_DIR"
    uv add "${LEROBOT_DIR:-"./lerobot"}[feetech, hardware, dataset]"
    uv add -r requirements.txt
else
    if [ ! -d $PROJECT_ROOT_DIR/.venv ]; then
        cd "$PROJECT_ROOT_DIR"
        python3 -m venv .venv
    fi

    cd "$PROJECT_ROOT_DIR"
    .venv/bin/pip install -e "${LEROBOT_DIR:-"./lerobot"}[feetech, hardware, dataset]"
    .venv/bin/pip install -r requirements.txt
fi