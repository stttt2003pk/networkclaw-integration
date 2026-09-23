#!/usr/bin/env sh
set -eu

repo_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
harness_path=$(python3 "$repo_dir/tools/resolve_sources.py" --get harness)
python_bin=${NETWORKCLAW_PYTHON:-$(python3 "$repo_dir/tools/resolve_sources.py" --get python)}
if ! command -v "$python_bin" >/dev/null 2>&1 && [ ! -x "$python_bin" ]; then
  printf '%s\n' "harness-launcher: Python executable unavailable: $python_bin" >&2
  exit 127
fi
export PYTHONPATH="$harness_path/src${PYTHONPATH:+:$PYTHONPATH}"
exec "$python_bin" -m networkclaw_harness.host "$@"
