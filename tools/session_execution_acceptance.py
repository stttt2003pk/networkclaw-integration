"""Public no-Profile execution against two real Lobbies/managers and native Hermes."""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from deployment_smoke import request_json


def run_public_sessions(args, report, *, work, go, common, base, lobby_ports, token, manifest,
                        models, providers, admin, sql, read_json, converge, status_urls,
                        diagnostic, real_config, private_values, origin, restart_manager, grpc_ports):
    import runpy
    import uuid
    admin_tools = runpy.run_path(str(Path(__file__).parent / 'capability-release-admin.py'))
    public_bodies = []

    def wait(check, reason, timeout=45):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if check():
                return
            time.sleep(.1)
        raise RuntimeError(reason)

    for operation in ('import', 'publish'):
        payload = admin_tools['build_request'](operation, 'session-acceptance-' + operation,
            manifest if operation == 'import' else None, release_id=manifest['release_id'],
            release_hash=manifest['release_hash'], expected_published_hash=None)
        status, receipt = admin_tools['send'](base, token, payload, origin=origin)
        if not 200 <= status < 300:
            diagnostic(json.dumps(receipt))
            raise RuntimeError('session_release_' + operation + '_failed')
    if sql('SELECT count(*) FROM agent_profiles') != '0':
        raise RuntimeError('ordinary_fixture_has_profiles')
    report['release_hash'] = manifest['release_hash']
    report['checks'].append('published_release_without_profiles')

    def api(node, route, method='GET', body=None, authorization=token):
        status, value = request_json(f'http://127.0.0.1:{lobby_ports[node]}' + route,
                                    method, body, authorization, origin, 180)
        public_bodies.append(value)
        if any(secret in json.dumps(value) for secret in private_values):
            raise RuntimeError('public_execution_credential_leak')
        return status, value

    def create(node, authorization):
        status, value = api(node, '/api/v1/sessions', 'POST', {}, authorization)
        if status != 201:
            diagnostic(json.dumps(value))
            raise RuntimeError('ordinary_empty_create_failed')
        identity = value.get('session', {}).get('id')
        if not identity:
            raise RuntimeError('ordinary_session_id_missing')
        return identity

    def send(session, text, model, *, node=0, authorization=token, expect=200, effort='low'):
        parameters = {'max_output_tokens': 256}
        if effort:
            parameters['reasoning_effort'] = effort
        status, value = api(node, f'/api/v1/sessions/{session}/messages', 'POST',
                           {'message': text, 'model_config_id': model['id'], 'model_parameters': parameters}, authorization)
        if status != expect:
            report['failed_turn'] = {'http_status': status, 'public_code': value.get('code'),
                                     'public_reason': value.get('message')}
            native_diagnostics = []
            for path in work.rglob('*.log'):
                for line in path.read_text(errors='replace').splitlines():
                    if any(message in line for message in ('Hermes native turn failed:',
                           'Native turn outcome diagnostic:', 'Native binding publication rejected:')):
                        native_diagnostics.append(line)
            diagnostic(json.dumps(value) + '\n' + '\n'.join(native_diagnostics) + '\n' +
                       '\n'.join(p.read_text(errors='replace') for p in work.glob('*.log')))
            raise RuntimeError('ordinary_turn_http_' + str(status))
        if expect == 200 and (not value.get('reply') or str(value['reply']).startswith('[ERROR]')):
            diagnostic(json.dumps(value))
            raise RuntimeError('ordinary_reply_missing')
        return value

    first = create(0, token)
    send(first, 'ordinary-first-turn', models[0])
    raw = sql(f"SELECT binding FROM harness_run_admissions WHERE session_id='{first}' ORDER BY created_at DESC LIMIT 1")
    binding = json.loads(raw)
    if binding['host_grant'].get('agent_snapshot') or binding['host_grant']['execution_snapshot'].get('profile_source'):
        raise RuntimeError('ordinary_grant_has_profile')
    frozen_execution = binding['host_grant']['execution_snapshot']
    workspace = Path(binding['workspace_root'])
    (workspace / 'fixture.txt').write_text('session-workspace-ok')
    send(first, 'session-skill read the frozen skill and authorized workspace file', models[0])
    send(first, 'session-delegate delegate a child to read the frozen skill', models[0])
    # Cross-Lobby lookup/admission uses the same durable ownership.
    send(first, 'ordinary-cross-lobby-turn', models[1], node=1)
    report['checks'].extend(['public_empty_session_create_no_profile', 'complete_independent_host_grant',
        'public_sync_native_skill_and_workspace_tool', 'public_sync_native_child_delegation', 'cross_lobby_same_session_model_switch'])

    email = 'execution-user-' + uuid.uuid4().hex + '@fixture.invalid'
    password = 'disposable-fixture-password'
    code, value = api(0, '/api/v1/auth/register', 'POST', {'email': email, 'password': password})
    if code not in (200, 201):
        raise RuntimeError('second_fixture_user_registration_failed')
    code, value = request_json(base + '/api/v1/auth/login', 'POST', {'email': email, 'password': password}, None, origin, 10)
    if code != 200 or not value.get('access_token'):
        raise RuntimeError('second_fixture_user_login_failed')
    second_token = value['access_token']
    private_values.append(second_token)
    # Observe actual load registration before scheduling the next user's process.
    registry = work / 'manager-0.registry.json'
    wait(lambda: any(int(v.get('metadata', {}).get('load', '0')) > 0 for v in
                     json.loads(registry.read_text()).get('services', {}).values()), 'manager_load_not_registered')
    # The file update precedes each Lobby's asynchronous discovery cache update.
    wait(lambda: any(int(v.get('load', 0)) > 0 for v in
                     api(1, '/api/v1/runtime-managers/')[1].get('managers', [])),
         'lobby_manager_load_not_converged')
    second = create(1, second_token)
    send(second, 'ordinary-second-manager', models[0], node=1, authorization=second_token)
    managers = sql(f"SELECT count(DISTINCT runtime_manager_id) FROM sessions WHERE id IN ('{first}','{second}')")
    if managers != '2':
        diagnostic(json.dumps(api(1, '/api/v1/runtime-managers/')[1]))
        raise RuntimeError('ordinary_sessions_not_on_two_managers')
    admissions_before = sql(f"SELECT count(*) FROM harness_run_admissions WHERE session_id='{first}'")
    code, value = api(1, f'/api/v1/sessions/{first}/messages', 'POST',
                      {'message': 'forbidden-other-owner', 'model_config_id': models[0]['id']}, second_token)
    # A different tenant receives 404 to avoid disclosing Session existence;
    # an owner mismatch in the same tenant receives 403.
    if code not in (403, 404) or sql(f"SELECT count(*) FROM harness_run_admissions WHERE session_id='{first}'") != admissions_before:
        diagnostic(json.dumps(value))
        raise RuntimeError('ordinary_foreign_owner_not_denied')
    report['foreign_owner_status'] = code
    report['checks'].extend(['two_distinct_managers_publicly_routed', 'foreign_owner_denied'])

    # Exercise actual Web2-compatible WS admission and canonical frames.
    ws_input, ws_output = work / 'ordinary-ws-input.json', work / 'ordinary-ws-output.json'
    ws_input.write_text(json.dumps({'session_id': first, 'message': 'ordinary-ws-model-switch',
                                  'model_config_id': models[2]['id'], 'model_parameters': {'max_output_tokens': 256}}))
    result = subprocess.run([str(work / 'probe'), '-test.run=^TestModelSnapshotWebSocketProbe$'], cwd=go,
        env=dict(common, MODEL_SNAPSHOT_PROBE_ORIGIN=origin, MODEL_SNAPSHOT_PROBE_WS=base.replace('http:', 'ws:') + '/ws',
                 MODEL_SNAPSHOT_PROBE_TOKEN=token, MODEL_SNAPSHOT_PROBE_INPUT=str(ws_input), MODEL_SNAPSHOT_PROBE_OUTPUT=str(ws_output)),
        capture_output=True, timeout=150)
    if result.returncode:
        diagnostic((result.stdout + result.stderr).decode('utf-8', 'replace'))
        raise RuntimeError('ordinary_ws_probe_failed')
    result_value = json.loads(ws_output.read_text())
    if result_value['errors'] or not result_value['done'] or not result_value['has_content']:
        raise RuntimeError('ordinary_ws_execution_failed')
    report['checks'].append('public_websocket_same_name_different_connection')

    def events(index):
        return read_json(providers[index] + '/__fixture/events')[1]

    observed = [e for e in events(0) if e['event'] == 'provider.execution_observed']
    if not any(e.get('skill_verified') for e in observed) or not any(e.get('workspace_read_verified') for e in observed):
        raise RuntimeError('native_skill_or_workspace_not_observed')
    child_names = {'skills_list', 'skill_view', 'networkclaw_workspace_read'}
    frozen_skill = next(ref for ref in frozen_execution['skills'] if ref['skill_id'] == 'workspace-inspection')
    if not any(e.get('skill_verified') and set(e['tool_names']) == child_names and
               e.get('skill_content_hash') == frozen_skill['content_hash'] and e.get('skill_version') == frozen_skill['version'] and
               e.get('model') == models[0]['model_id'] and e.get('credential_revision') == 1 and
               e.get('reasoning_effort') == 'low' and e.get('max_output_tokens') == 256 for e in observed):
        diagnostic(json.dumps({'observed': observed, 'expected_skill': frozen_skill}, sort_keys=True))
        raise RuntimeError('native_child_frozen_skill_not_observed')
    allocations = json.loads(sql(f"SELECT COALESCE(json_agg(e.value),'[]'::json) FROM harness_run_admissions a, LATERAL jsonb_each(COALESCE(a.binding->'child_allocations','{{}}'::jsonb)) e WHERE a.session_id='{first}'"))
    granted = [a for a in allocations if a['decision'] == 'grant']
    if not granted or not all(a['released'] and a['child_session_id'] != first for a in granted):
        raise RuntimeError('native_child_allocation_not_released')
    if sql(f"SELECT count(*) FROM session_runtime_bindings WHERE session_id IN ('{first}','{second}')") != '2':
        raise RuntimeError('native_binding_not_saved')
    report['checks'].extend(['actual_frozen_skill_content_verified', 'actual_child_skill_and_narrowed_tools',
                              'platform_child_allocations_released', 'platform_native_runtime_associations_saved'])

    old_revision = [read_json(url)[1]['snapshot_revision'] for url in status_urls]
    connection = next(c for c in admin('connections')['connections'] if c['id'] == models[1]['connection_id'])
    admin('connections/' + connection['id'], 'PUT', {k: connection[k] for k in
          ('name', 'provider_id', 'api_mode', 'base_url', 'timeout_seconds', 'enabled')} | {'api_key': 'model-fixture-v2'})
    started = time.monotonic()
    for i, url in enumerate(status_urls):
        wait(lambda i=i,url=url: read_json(url)[1]['snapshot_revision'] > old_revision[i], 'ordinary_rotation_convergence_failed')
    report['convergence_seconds'].append(round(time.monotonic() - started, 3))
    rotated = next(m for m in admin('models')['models'] if m['id'] == models[1]['id'])
    send(first, 'ordinary-after-credential-rotation', rotated)
    requests = [e for e in events(1) if e['event'] == 'provider.request_received']
    if not requests or requests[-1]['credential_revision'] != 2 or requests[-1]['history_messages'] < 4:
        raise RuntimeError('credential_rotation_or_native_history_failed')
    report['checks'].extend(['broker_30_second_rotation_convergence', 'credential_rotation_preserves_native_history'])

    if args.manager_restart:
        import base64
        prior_tip = sql(f"SELECT hermes_session_id FROM session_runtime_bindings WHERE session_id='{first}'")
        runtime_id = sql(f"SELECT runtime_manager_id FROM sessions WHERE id='{first}'")
        node = int(runtime_id.rsplit('-', 1)[1])
        old_binding = json.loads(sql(f"SELECT binding FROM harness_run_admissions WHERE session_id='{first}' ORDER BY created_at DESC LIMIT 1"))
        before = sum(len(events(i)) for i in range(2))
        restart_manager(node)
        grant = old_binding['host_grant']
        wire_grant = {k:grant[k] for k in ('session_id','execution_epoch','workspace','turn_budget','resource_profile','allowed_tools')}
        for field in ('capability_snapshot','skill_snapshot','execution_snapshot'):
            wire_grant[field + '_json'] = base64.b64encode(json.dumps(grant[field]).encode()).decode()
        request = {'session_id': first, 'message': 'old-run-must-not-repeat', 'execution_path': 'harness',
            'model_config_id': rotated['id'], 'model_config_revision': rotated['config_revision'], 'credential_revision': rotated['credential_revision'],
            'harness': {k:old_binding[k] for k in ('tenant_id','user_id','owner_id','execution_epoch','turn_id','run_id','process_id','lease','workspace_root')} | {'host_grant': wire_grant, 'agent_id': old_binding.get('agent_id') or 'default'}}
        retry_input, retry_output = work / 'old-run-retry.json', work / 'old-run-retry-result.json'
        retry_input.write_text(json.dumps(request))
        result = subprocess.run([str(work / 'probe'), '-test.run=^TestModelSnapshotDistributedProbe$'], cwd=go,
            env=dict(common, MODEL_SNAPSHOT_PROBE_ENDPOINT=f'127.0.0.1:{grpc_ports[node]}',
                     MODEL_SNAPSHOT_PROBE_INPUT=str(retry_input), MODEL_SNAPSHOT_PROBE_OUTPUT=str(retry_output)),
            capture_output=True, timeout=100)
        if result.returncode:
            diagnostic((result.stdout + result.stderr).decode('utf-8', 'replace'))
            raise RuntimeError('manager_restart_replay_probe_failed')
        retried = json.loads(retry_output.read_text())
        if not retried['errors'] or retried['has_content'] or before != sum(len(events(i)) for i in range(2)):
            raise RuntimeError('lost_manager_pin_reexecuted_old_turn')
        send(first, 'new-turn-after-manager-restart', rotated)
        if sql(f"SELECT hermes_session_id FROM session_runtime_bindings WHERE session_id='{first}'") != prior_tip:
            raise RuntimeError('manager_restart_lost_native_tip')
        report['checks'].extend(['real_manager_restart_old_run_not_reexecuted','real_manager_restart_new_turn_recovers_native_tip'])

    if real_config:
        previous = [read_json(url)[1]['snapshot_revision'] for url in status_urls]
        connection = admin('connections', 'POST', {'name': 'real-gpt-ordinary', 'provider_id': 'openai',
            'api_mode': 'chat_completions', 'base_url': real_config['endpoint'], 'api_key': real_config['key'],
            'timeout_seconds': 120, 'enabled': True})
        actual = admin('models', 'POST', {'connection_id': connection['id'], 'model_id': real_config['model'],
            'display_name': 'real-gpt-ordinary', 'enabled': True,
            'capabilities': {'context_tokens': 128000, 'tools': True, 'vision': False, 'temperature': False, 'reasoning_efforts': []},
            'parameters': {}})
        for i,url in enumerate(status_urls):
            wait(lambda i=i,url=url: read_json(url)[1]['snapshot_revision'] > previous[i], 'real_gpt_sync_failed')
        reply = send(first, 'Reply with exactly ordinary-gpt-ok. Do not use tools.', actual, effort=None)
        if 'ordinary-gpt-ok' not in reply['reply']:
            raise RuntimeError('real_gpt_ordinary_reply_invalid')
        report['checks'].append('real_gpt_public_ordinary_session')

    if args.browser:
        browser_output = work / 'browser-result.json'
        result = subprocess.run(['node', str(Path(__file__).parent / 'session-execution-browser.cjs')],
            cwd=go / 'web2', env=dict(common, SESSION_EXECUTION_BROWSER_URL=origin,
                SESSION_EXECUTION_BROWSER_MODELS=json.dumps([models[0]['id'], models[2]['id']]),
                SESSION_EXECUTION_BROWSER_OUTPUT=str(browser_output)), capture_output=True, timeout=180)
        if result.returncode:
            diagnostic((result.stdout + result.stderr).decode('utf-8', 'replace'))
            raise RuntimeError('ordinary_browser_flow_failed')
        result_value = json.loads(browser_output.read_text())
        report['browser'] = result_value
        report['checks'].extend(result_value['checks'])

    # The current matrices intentionally report their exact coverage, never fill absent gates.
    report['public_response_scan'] = 'passed'
    report['native_child_allocations'] = len(granted)
