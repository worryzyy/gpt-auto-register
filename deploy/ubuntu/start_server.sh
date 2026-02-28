#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

export PATH="$HOME/.local/bin:$PATH"
export PYTHONUNBUFFERED=1

exec xvfb-run -a --server-args="-screen 0 1920x1080x24 -nolisten tcp" uv run server.py
