#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
NETWORKCLAW_PATH="${NETWORKCLAW_PATH:-$ROOT/../NetworkClaw}"
HARNESS_PATH="${HARNESS_PATH:-$ROOT/../networkclaw-harness}"
export NETWORKCLAW_PATH HARNESS_PATH
WHEELHOUSE="${CI_WHEELHOUSE:-$ROOT/.integration-state/ci/wheelhouse}"
REPORT="${CI_REPORT:-$ROOT/.integration-state/evidence/ubuntu-22.04-ci.json}"
BUNDLE_OUTPUT="${BUNDLE_OUTPUT:-.integration-state/artifacts/networkclaw-bundle.tar.gz}"
CI_OFFLINE="${CI_OFFLINE:-0}"
if [[ "$BUNDLE_OUTPUT" != /* ]]; then
  BUNDLE_PATH="$ROOT/$BUNDLE_OUTPUT"
else
  BUNDLE_PATH="$BUNDLE_OUTPUT"
fi
mkdir -p "$(dirname "$REPORT")" "$ROOT/.integration-state/evidence"
cd "$ROOT"

run_stage() {
  local name="$1"; shift
  local started end code=0 log
  started="$(date +%s)"
  log="$ROOT/.integration-state/evidence/ubuntu-22.04-${name}.log"
  "$@" >"$log" 2>&1 || code=$?
  end="$(date +%s)"
  STAGES+=("{\"name\":\"$name\",\"exit_code\":$code,\"duration_seconds\":$((end-started)),\"log\":\".integration-state/evidence/ubuntu-22.04-$name.log\"}")
  if [ "$code" -ne 0 ]; then tail -40 "$log" >&2; fi
  return 0
}

STAGES=()
if [ "$CI_OFFLINE" = 1 ]; then
  run_stage integration_bootstrap env HARNESS_PATH="$HARNESS_PATH" WHEELHOUSE="$WHEELHOUSE" bash -c 'python3.12 -m venv .venv && .venv/bin/python -m pip install --no-index --find-links "$WHEELHOUSE" setuptools wheel poetry-core==2.2.1 && .venv/bin/python -m pip install --no-index --find-links "$WHEELHOUSE" --no-build-isolation -e .'
  run_stage harness_bootstrap env HARNESS_PATH="$HARNESS_PATH" WHEELHOUSE="$WHEELHOUSE" bash -c 'python3.12 -m venv "$HARNESS_PATH/.venv" && "$HARNESS_PATH/.venv/bin/python" -m pip install --no-index --find-links "$WHEELHOUSE" --require-hashes -r "$HARNESS_PATH/requirements.lock" -r "$HARNESS_PATH/requirements-dev.lock" -r "$HARNESS_PATH/requirements-build.lock" && "$HARNESS_PATH/.venv/bin/python" -m pip install --no-index --find-links "$WHEELHOUSE" --no-build-isolation -e "${HARNESS_PATH}[dev]"'
else
  run_stage integration_bootstrap bash -c 'python3.12 -m venv .venv && .venv/bin/python -m pip install -e .'
  run_stage harness_bootstrap env HARNESS_PATH="$HARNESS_PATH" bash -c 'python3.12 -m venv "$HARNESS_PATH/.venv" && "$HARNESS_PATH/.venv/bin/python" -m pip install -e "${HARNESS_PATH}[dev]"'
fi
run_stage sync_harness_wheelhouse env HARNESS_PATH="$HARNESS_PATH" WHEELHOUSE="$WHEELHOUSE" bash -c 'mkdir -p "$HARNESS_PATH/offline/wheels" && find "$HARNESS_PATH/offline/wheels" -maxdepth 1 -type f -name "*.whl" -delete && find "$WHEELHOUSE" -maxdepth 1 -type f -name "*.whl" -exec cp -f {} "$HARNESS_PATH/offline/wheels/" \;'
run_stage go_test_race go -C "$NETWORKCLAW_PATH" test -race ./...
run_stage source_lock env NETWORKCLAW_PATH="$NETWORKCLAW_PATH" HARNESS_PATH="$HARNESS_PATH" "$ROOT/.venv/bin/python" "$ROOT/tools/verify_sources_lock.py"
run_stage harness_tests env HARNESS_PATH="$HARNESS_PATH" bash -c 'cd "$HARNESS_PATH" && PYTHONPATH="$HARNESS_PATH/src" ./scripts/run_tests.sh'
run_stage capability_release_gates env NETWORKCLAW_PATH="$NETWORKCLAW_PATH" HARNESS_PATH="$HARNESS_PATH" make -C "$ROOT" capability-release-vendor-check capability-release-compile capability-release-check capability-release-diff
run_stage integration_tests make -C "$ROOT" test
run_stage capability_release_acceptance make -C "$ROOT" capability-release-acceptance
run_stage combination_matrix env NETWORKCLAW_PATH="$NETWORKCLAW_PATH" HARNESS_PATH="$HARNESS_PATH" make -C "$ROOT" combination-matrix
run_stage model_snapshot_acceptance make -C "$ROOT" model-snapshot-acceptance
run_stage session_execution_acceptance make -C "$ROOT" session-execution-acceptance
if [ "${CI_ALLOW_DIRTY:-0}" = 1 ]; then
  run_stage bundle make -C "$ROOT" bundle BUNDLE_OUTPUT="$BUNDLE_OUTPUT" BUNDLE_CAPABILITY_RELEASE=1
else
  run_stage bundle make -C "$ROOT" bundle BUNDLE_OUTPUT="$BUNDLE_OUTPUT" BUNDLE_RELEASE=1 BUNDLE_CAPABILITY_RELEASE=1
fi
run_stage verify_bundle make -C "$ROOT" verify-bundle BUNDLE_OUTPUT="$BUNDLE_OUTPUT"
if [ "$CI_OFFLINE" = 1 ]; then
  run_stage bundle_self_test python3.12 "$ROOT/tests/bundle/self_test.py" "$BUNDLE_PATH" --wheelhouse "$WHEELHOUSE" --report "$ROOT/.integration-state/evidence/bundle-self-test.json"
else
  run_stage bundle_self_test python3.12 "$ROOT/tests/bundle/self_test.py" "$BUNDLE_PATH" --report "$ROOT/.integration-state/evidence/bundle-self-test.json"
fi

status=passed
for stage in "${STAGES[@]}"; do case "$stage" in *'"exit_code":0,'*) ;; *) status=failed ;; esac; done
printf '{"schema_version":1,"platform":"ubuntu-22.04","architecture":"amd64","status":"%s","stages":[%s]}\n' "$status" "$(IFS=,; echo "${STAGES[*]}")" > "$REPORT"
echo "CI report: $REPORT"
test "$status" = passed
