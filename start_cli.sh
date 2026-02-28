#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

UV_BIN="${UV_BIN:-$ROOT_DIR/.uv/uv}"
if [[ ! -x "$UV_BIN" ]]; then
  UV_BIN="uv"
fi

export PYTHONUNBUFFERED=1
export UV_PYTHON_INSTALL_DIR="${UV_PYTHON_INSTALL_DIR:-$ROOT_DIR/.uv-python}"
export UV_CACHE_DIR="${UV_CACHE_DIR:-$ROOT_DIR/.uv-cache}"

if command -v xvfb-run >/dev/null 2>&1; then
  exec xvfb-run -a --server-args="-screen 0 1920x1080x24 -nolisten tcp" "$UV_BIN" run --python 3.13 -- main.py "$@"
fi

exec "$UV_BIN" run --python 3.13 -- main.py "$@"
