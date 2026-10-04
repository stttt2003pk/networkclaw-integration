"""Integration validation of the Session execution contract and immutable digest."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from jsonschema import Draft202012Validator

SCHEMA = json.loads((Path(__file__).resolve().parents[1] / 'schemas/session-execution-v1.schema.json').read_text())

def snapshot_hash(snapshot: dict) -> str:
    return 'sha256:' + hashlib.sha256(json.dumps({k: v for k, v in snapshot.items() if k != 'snapshot_hash'}, ensure_ascii=True, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()

def validate(snapshot: dict, *, session_id: str | None = None) -> None:
    if isinstance(snapshot, dict) and 'contract_version' in snapshot and snapshot['contract_version'] != 'session-execution.v1':
        raise ValueError('execution_contract_unsupported')
    if list(Draft202012Validator(SCHEMA).iter_errors(snapshot)):
        raise ValueError('execution_snapshot_invalid')
    if session_id is not None and snapshot['session_id'] != session_id:
        raise ValueError('execution_snapshot_identity_invalid')
    if snapshot['snapshot_hash'] != snapshot_hash(snapshot):
        raise ValueError('execution_snapshot_hash_invalid')
    tools = [item['name'] for item in snapshot['tools']]
    sets = [item['name'] for item in snapshot['requested_toolsets']]
    skills = [item['skill_id'] for item in snapshot['skills']]
    if any(len(names) != len(set(names)) for names in (tools, sets, skills)):
        raise ValueError('execution_asset_duplicate')
    for skill in snapshot['skills']:
        if skill['mode'] != 'disabled' and (not set(skill['resolved_dependencies']['tools']) <= set(tools) or not set(skill['resolved_dependencies']['toolsets']) <= set(sets)):
            raise ValueError('execution_dependency_denied')
    policy = snapshot['policy']['delegation_policy']
    if policy['enabled'] and ('delegate_task' not in tools or policy['max_depth'] == 0 or policy['max_concurrent_children'] == 0):
        raise ValueError('execution_delegation_denied')


def validate_mirrors(integration: Path, networkclaw: Path, harness: Path) -> None:
    """Check deployed schema and golden inputs through configured source roots."""
    schema = integration / 'schemas/session-execution-v1.schema.json'
    fixtures = integration / 'tests/fixtures/session-execution'
    for schema_copy, fixture_dir in (
        (networkclaw / 'api/chatrtmgr/v1/session-execution-v1.schema.json', networkclaw / 'internal/shared/sessionexecution/testdata'),
        (harness / 'src/networkclaw_harness/protocol/schema/v1/session-execution-v1.schema.json', harness / 'tests/fixtures/session-execution'),
    ):
        if schema_copy.read_bytes() != schema.read_bytes():
            raise ValueError('execution_contract_mirror_drift: schema')
        expected = {p.name for p in fixtures.glob('*.json')}
        if {p.name for p in fixture_dir.glob('*.json')} != expected:
            raise ValueError('execution_contract_mirror_drift: fixtures')
        for name in sorted(expected):
            if (fixture_dir / name).read_bytes() != (fixtures / name).read_bytes():
                raise ValueError('execution_contract_mirror_drift: ' + name)
