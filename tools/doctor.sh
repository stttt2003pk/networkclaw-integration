#!/usr/bin/env sh
set -eu

repo_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
workspace_file="$repo_dir/workspace.local.yaml"

networkclaw_path="${NETWORKCLAW_PATH:-$repo_dir/../NetworkClaw}"
harness_path="${HARNESS_PATH:-$repo_dir/../networkclaw-harness}"

if [ -f "$workspace_file" ]; then
  configured_networkclaw=$(sed -n 's/^[[:space:]]*networkclaw_path:[[:space:]]*//p' "$workspace_file" | tail -n 1)
  configured_harness=$(sed -n 's/^[[:space:]]*harness_path:[[:space:]]*//p' "$workspace_file" | tail -n 1)
  case "$configured_networkclaw" in
    /*) [ -z "$configured_networkclaw" ] || networkclaw_path=$configured_networkclaw ;;
    *) [ -z "$configured_networkclaw" ] || networkclaw_path="$repo_dir/$configured_networkclaw" ;;
  esac
  case "$configured_harness" in
    /*) [ -z "$configured_harness" ] || harness_path=$configured_harness ;;
    *) [ -z "$configured_harness" ] || harness_path="$repo_dir/$configured_harness" ;;
  esac
fi

networkclaw_path=$(CDPATH= cd -- "$networkclaw_path" 2>/dev/null && pwd || true)
harness_path=$(CDPATH= cd -- "$harness_path" 2>/dev/null && pwd || true)

failed=0

check_repo() {
  label=$1
  path=$2
  marker=$3

  if [ -z "$path" ] || [ ! -d "$path/.git" ] || [ ! -f "$path/$marker" ]; then
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
check_command Go go
check_command Python3 python3

if [ "$failed" -ne 0 ]; then
  exit 1
fi

printf '%s\n' 'Integration workspace is ready for local tooling.'
