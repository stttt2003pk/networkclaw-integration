#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
IMAGE_ARCHIVE="${1:?usage: security-scan.sh image-archive}"
command -v syft >/dev/null || { echo 'missing required scanner: syft' >&2; exit 2; }
command -v trivy >/dev/null || { echo 'missing required scanner: trivy' >&2; exit 2; }
mkdir -p "$ROOT/.integration-state/evidence"
if tar -tf "$IMAGE_ARCHIVE" | grep -qx 'oci-layout'; then
  ARCHIVE_INPUT="oci-archive:$IMAGE_ARCHIVE"
else
  ARCHIVE_INPUT="docker-archive:$IMAGE_ARCHIVE"
fi
syft "$ARCHIVE_INPUT" -o cyclonedx-json > "$ROOT/.integration-state/evidence/image-sbom.cdx.json"
python3 - "$ROOT/.integration-state/evidence/image-sbom.cdx.json" "$ROOT/.integration-state/evidence/image-license-summary.json" <<'PY'
import json, sys
source, target = sys.argv[1:]
document = json.load(open(source, encoding="utf-8"))
components = document.get("components", [])
licensed = sum(bool(component.get("licenses")) for component in components)
if not components or not licensed:
    raise SystemExit("SBOM contains no license metadata")
json.dump({"schema_version": 1, "components": len(components), "licensed_components": licensed}, open(target, "w", encoding="utf-8"), indent=2)
PY
TRIVY_ARGS=(image --input "$IMAGE_ARCHIVE" --scanners vuln,secret,misconfig --severity HIGH,CRITICAL --ignore-unfixed --exit-code 1 --format json)
if [[ "${TRIVY_SKIP_DB_UPDATE:-0}" == 1 ]]; then
  TRIVY_ARGS+=(--skip-db-update)
fi
if [[ "${TRIVY_SKIP_CHECK_UPDATE:-1}" == 1 ]]; then
  TRIVY_ARGS+=(--skip-check-update)
fi
trivy "${TRIVY_ARGS[@]}" > "$ROOT/.integration-state/evidence/trivy.json"
