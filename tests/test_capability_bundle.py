from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from tools.capability_bundle import PREFIX, validate

ROOT = Path(__file__).resolve().parents[1]


class CapabilityBundleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.schema = (ROOT / 'schemas/capability-release-v1.schema.json').read_bytes()
        self.manifest = json.loads((ROOT / 'tests/fixtures/capability-release/valid-release-v1.json').read_text())
        hermes = self.manifest['hermes']
        self.bundle = {
            'sources': {name: {
                'tree_sha256': source['tree_hash'][7:], 'commit': source['commit'],
                'dirty': source['dirty'], 'diff_sha256': None,
            } for name, source in self.manifest['sources'].items()},
            'hermes': {
                'upstream_ref': hermes['source_ref'], 'upstream_repository': hermes['source_repository'],
                'vendor_manifest_sha256': hermes['vendor_manifest_hash'][7:],
            },
            'protocol': {'version': self.manifest['protocol']['host_protocol_version']},
            'target': {key: self.manifest['target'][key] for key in ('os', 'version', 'architecture')},
        }
        self.bundle['sources']['harness']['vendor_tree_sha256'] = hermes['vendor_tree_hash'][7:]
        gate = {'status': 'passed', 'hermes': {
            'source_ref': hermes['source_ref'], 'source_repository': hermes['source_repository'],
            'vendor_manifest_sha256': hermes['vendor_manifest_hash'][7:],
            'vendor_tree_sha256': hermes['vendor_tree_hash'][7:],
        }}
        migration = {'source': 'published_release', 'unresolved': []}
        documents = {
            'manifests/capability-release.v1.json': self.manifest,
            'reports/check.json': {'status': 'passed', 'manifest_hash': self.manifest['release_hash'], 'errors': [], 'checks': {'release_hash': True}},
            'reports/diff.json': {'status': 'passed', 'candidate': {key: self.manifest[key] for key in ('release_id', 'release_hash')}, 'migration': migration},
            'provenance/vendor-gate.json': gate, 'migration/plan.json': migration,
        }
        self.payload = {PREFIX + name: json.dumps(document).encode() for name, document in documents.items()}
        self.payload[PREFIX + 'schemas/capability-release-v1.schema.json'] = self.schema
        self.payload[PREFIX + 'migration/session-runbook.md'] = b'# Migration\n'

    def test_release_payload_is_present_and_self_consistent(self) -> None:
        self.assertEqual(validate(self.payload, self.bundle, self.schema, self.schema), {
            'manifest_hash': self.manifest['release_hash'], 'files': sorted(self.payload),
        })

    def test_schema_drift_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, 'capability_schema_drift'):
            validate(self.payload, self.bundle, self.schema, self.schema + b'\n')

    def test_hash_and_provenance_drift_are_rejected(self) -> None:
        for drift, reason in (('hash', 'release_hash_invalid'), ('source', 'capability_source_drift'), ('vendor', 'capability_vendor_drift')):
            with self.subTest(drift=drift):
                payload, bundle = copy.deepcopy(self.payload), copy.deepcopy(self.bundle)
                if drift == 'hash':
                    manifest = copy.deepcopy(self.manifest)
                    manifest['release_id'] = 'cap-tampered'
                    payload[PREFIX + 'manifests/capability-release.v1.json'] = json.dumps(manifest).encode()
                elif drift == 'source':
                    bundle['sources']['integration']['tree_sha256'] = '0' * 64
                else:
                    bundle['sources']['harness']['vendor_tree_sha256'] = '0' * 64
                with self.assertRaisesRegex(ValueError, reason):
                    validate(payload, bundle, self.schema, self.schema)


if __name__ == '__main__':
    unittest.main()
