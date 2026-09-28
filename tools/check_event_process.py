#!/usr/bin/env python3
"""Export and verify the actual web2 parser/reducer/render fixture ledger."""

from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    source = subprocess.run([sys.executable, str(ROOT / 'tools/resolve_sources.py'), '--get', 'networkclaw'],
                            check=True, text=True, capture_output=True)
    report_dir = ROOT / '.integration-state/evidence'
    report_dir.mkdir(parents=True, exist_ok=True)
    ledger_path = report_dir / 'event-e06-frontend-ledger.json'
    ledger_path.unlink(missing_ok=True)
    env = os.environ | {'NETWORKCLAW_INTEGRATION_PATH': str(ROOT),
                        'NETWORKCLAW_EVENT_LEDGER_REPORT': str(ledger_path)}
    web2 = Path(source.stdout.strip()) / 'web2'
    if not (web2 / 'node_modules/.bin/vitest').is_file():
        install = subprocess.run(['npm', 'ci'], cwd=web2, check=False)
        if install.returncode:
            return install.returncode
    result = subprocess.run(['npm', 'test', '--', 'src/components/EventE06.integration.test.tsx'],
                            cwd=web2, env=env, check=False)
    if result.returncode:
        return result.returncode
    ledger = json.loads(ledger_path.read_text())
    fixture = json.loads((ROOT / 'tests/fixtures/events/process-tree-fixture.json').read_text())
    catalog = json.loads((ROOT / 'schemas/events/event-catalog-v1.json').read_text())
    declared = {item['name'] for item in catalog['baseline_events'] + catalog['process_extensions']}
    covered = {item['type'] for item in ledger['catalog_coverage'] if item['envelope_preserved']}
    errors = []
    if ledger['events'] != fixture['events']:
        errors.append('frontend ledger differs from producer contract fixture')
    if covered != declared:
        errors.append('frontend catalog coverage differs from canonical catalog')
    if not ledger['lineage_reconstructed'] or ledger['status'] != 'passed':
        errors.append('frontend lineage reconstruction failed')
    if any(ledger[key] for key in ('loss', 'downgraded', 'renamed')):
        errors.append('frontend ledger reports loss, downgrade or rename')
    report = {
        'schema_version': 1, 'status': 'failed' if errors else 'passed',
        'evidence_kind': 'fixture-parser-reducer-render',
        'runtime_transport_verified': False,
        'canonical_event_count': len(declared), 'fixture_event_count': len(fixture['events']),
        'catalog_coverage': ledger['catalog_coverage'],
        'producer_verification': 'catalog declarations only; runtime emit belongs to transport acceptance',
        'consumer_missing': sorted(declared - covered),
        'loss': ledger['loss'], 'downgraded': ledger['downgraded'], 'renamed': ledger['renamed'],
        'lineage_reconstructed': ledger['lineage_reconstructed'], 'errors': errors,
        'source_sha256': {
            name: hashlib.sha256(path.read_bytes()).hexdigest()
            for name, path in {
                'catalog': ROOT / 'schemas/events/event-catalog-v1.json',
                'fixture': ROOT / 'tests/fixtures/events/process-tree-fixture.json',
                'parser': web2 / 'src/api/chat.ts',
                'process_reducer': web2 / 'src/api/canonicalProjection.ts',
                'semantic_reducer': web2 / 'src/api/semanticProjection.ts',
                'ui_test': web2 / 'src/components/EventE06.integration.test.tsx',
            }.items()
        },
    }
    (report_dir / 'event-e06-process-report.json').write_text(json.dumps(report, indent=2) + '\n')
    for error in errors:
        print(error, file=sys.stderr)
    return 1 if errors else 0


if __name__ == '__main__':
    raise SystemExit(main())
