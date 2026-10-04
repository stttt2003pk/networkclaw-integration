#!/usr/bin/env sh
set -eu

repo_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)

"$repo_dir/.venv/bin/python" "$repo_dir/tools/run-combination-matrix.py"
make -C "$repo_dir" model-snapshot-acceptance
make -C "$repo_dir" session-execution-acceptance
