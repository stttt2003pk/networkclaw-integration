#!/usr/bin/env sh
set -eu

repo_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
resolved=$(python3 "$repo_dir/tools/resolve_sources.py" --json)
networkclaw_path=$(printf '%s' "$resolved" | python3 -c 'import json,sys; print(json.load(sys.stdin)["networkclaw"]["path"])')
harness_path=$(printf '%s' "$resolved" | python3 -c 'import json,sys; print(json.load(sys.stdin)["harness"]["path"])')
networkclaw_tree=$(printf '%s' "$resolved" | python3 -c 'import json,sys; print(json.load(sys.stdin)["networkclaw"]["tree_sha256"])')
harness_tree=$(printf '%s' "$resolved" | python3 -c 'import json,sys; print(json.load(sys.stdin)["harness"]["tree_sha256"])')
networkclaw_commit=$(printf '%s' "$resolved" | python3 -c 'import json,sys; print(json.load(sys.stdin)["networkclaw"]["commit"] or "no-git")')
networkclaw_dirty=$(printf '%s' "$resolved" | python3 -c 'import json,sys; print(json.load(sys.stdin)["networkclaw"]["dirty"])')
harness_commit=$(printf '%s' "$resolved" | python3 -c 'import json,sys; print(json.load(sys.stdin)["harness"]["commit"] or "no-git")')
harness_dirty=$(printf '%s' "$resolved" | python3 -c 'import json,sys; print(json.load(sys.stdin)["harness"]["dirty"])')
python_bin=$(printf '%s' "$resolved" | python3 -c 'import json,sys; print(json.load(sys.stdin)["python"])')
go_binary=$(printf '%s' "$resolved" | python3 -c 'import json,sys; print(json.load(sys.stdin)["go_binary"])')
state_dir=$(printf '%s' "$resolved" | python3 -c 'import json,sys; print(json.load(sys.stdin)["state_dir"])')
provider_env_file=$(printf '%s' "$resolved" | python3 -c 'import json,sys; print(json.load(sys.stdin)["provider_env_file"] or "")')

failed=0

check_repo() {
  label=$1
  path=$2
  marker=$3

  if [ -z "$path" ] || [ ! -d "$path" ] || [ ! -f "$path/$marker" ]; then
    printf '%s\n' "FAIL $label repository is unavailable or invalid: ${path:-<unresolved>}" >&2
    failed=1
    return
  fi
  printf '%s\n' "OK   $label: $path"
}

check_command() {
  label=$1
  command_name=$2
  if command -v "$command_name" >/dev/null 2>&1; then
    printf '%s\n' "OK   $label: $(command -v "$command_name")"
  else
    printf '%s\n' "FAIL $label command is unavailable: $command_name" >&2
    failed=1
  fi
}

check_repo NetworkClaw "$networkclaw_path" go.mod
check_repo Harness "$harness_path" pyproject.toml
check_command Git git
check_command Go "$go_binary"
check_command Python3 python3
check_command ConfiguredPython "$python_bin"
integration_python="$repo_dir/.venv/bin/python"
check_command IntegrationPython "$integration_python"
if [ -n "$provider_env_file" ]; then
  printf '%s\n' 'OK   Provider environment file configured (values suppressed)'
else
  printf '%s\n' 'INFO No provider .env found; shell environment will be used'
fi

if command -v "$python_bin" >/dev/null 2>&1; then
  python_version=$($python_bin -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
elif [ -x "$python_bin" ]; then
  python_version=$($python_bin -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
else
  python_version=unavailable
fi
case "$python_version" in
  3.12) printf '%s\n' "OK   CPython $python_version" ;;
  *) printf '%s\n' "FAIL Harness requires CPython 3.12, found $python_version" >&2; failed=1 ;;
esac

if [ "$python_version" = 3.12 ]; then
  if "$python_bin" -c 'import yaml, networkclaw_harness.host' >/dev/null 2>&1; then
    printf '%s\n' 'OK   Harness runtime imports and PyYAML dependency'
  else
    printf '%s\n' 'FAIL Harness runtime/dependencies are unavailable in configured Python' >&2
    failed=1
  fi
fi

if [ -x "$integration_python" ]; then
  if "$integration_python" -c 'import dotenv, jsonschema, yaml' >/dev/null 2>&1; then
    printf '%s\n' 'OK   Integration Python dependencies'
  else
    printf '%s\n' 'FAIL Integration dependencies are unavailable; run make bootstrap' >&2
    failed=1
  fi
else
  printf '%s\n' 'FAIL Integration Python environment is missing; run make bootstrap' >&2
  failed=1
fi

printf '%s\n' "NetworkClaw source: commit=$networkclaw_commit dirty=$networkclaw_dirty tree_sha256=$networkclaw_tree"
printf '%s\n' "Harness source: commit=$harness_commit dirty=$harness_dirty tree_sha256=$harness_tree"

if [ -e "$state_dir/sockets/chatsvc.sock" ]; then
  printf '%s\n' "WARN integration socket exists: $state_dir/sockets/chatsvc.sock" >&2
fi
if command -v docker >/dev/null 2>&1; then
  printf '%s\n' "OK   Docker: $(command -v docker)"
elif command -v podman >/dev/null 2>&1; then
  printf '%s\n' "OK   Podman: $(command -v podman)"
else
  printf '%s\n' 'INFO Docker/Podman unavailable; local source development remains available'
fi
if [ "$failed" -ne 0 ]; then
  exit 1
fi

printf '%s\n' 'Integration workspace diagnostics completed.'
