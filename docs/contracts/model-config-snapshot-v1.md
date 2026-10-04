# Model configuration snapshot v1

Lobby owns persisted model connections, encrypted credentials and model configurations.
`GET /internal/v1/model-config-snapshot` requires a fixed Bearer token and returns a
private `model-config.v1` snapshot. It is not a Session capability snapshot and must
never be exported, logged or included in public events. Production transport uses HTTPS.

The snapshot contains `contract_version`, `snapshot_revision`, `default_model_id`
and `models`. Every enabled model carries `id`, `connection_id`, `provider_id`,
`model_id`, `api_mode`, `base_url`, `api_key`, `config_revision`,
`credential_revision`, `timeout_seconds`, `capabilities` and `parameters`.
Public model responses omit endpoint and credential fields. Credentials are encrypted
at rest; the internal response and node cache contain plaintext only in memory.

Connection/model/default changes and the global revision commit together. Connections
are shared by models; endpoint/protocol/credential changes update the execution
revision of every affected model. Display-only changes do not change execution identity.
The ETag is `"model-config-<revision>"`; a matching request returns 304.

chatrtmgr immediately synchronizes on startup, then every 30 seconds with a five-second
request timeout. Valid 200/304 responses renew freshness. Invalid responses, rollback,
authentication failures and timeouts preserve the previous cache without renewing it.
New turns stop after five minutes without confirmation. Empty snapshots are valid.

The Lobby-to-chatrtmgr request includes a public model reference and minimum execution
and credential revisions. chatrtmgr pins one immutable configuration per run and sends
`model_execution` in the private Host Protocol `user.input` payload. Missing/newer models
return `model_config_not_synced`; unavailable/expired snapshots return
`model_config_unavailable`/`model_config_stale`. No per-turn fetch or environment fallback.
Replay and controls do not select a model. Lost pins never authorize automatic reexecution.

Lobby's existing durable run admission records the original process/service ID.
The manager validates that binding against its local process table before pinning.
New service IDs after a manager restart fence old admissions: a lost pin cannot be
re-created on another process. A Gateway restart changes its socket and prevents
retrying a pinned run against a fresh runtime. Retries keep the exact original
configuration, parameters and deadline. Closing a session drops credential values
and retains a memory-only run tombstone until manager shutdown. Controls and event
replay bypass model resolution. No manager-to-Lobby call occurs during pinning;
authorized new turns continue from a fresh cache during synchronization outages.

Harness validates explicit configuration and egress policy, reuses an Agent when its
execution identity is unchanged, and otherwise rebuilds it between turns. SessionDB,
workspace, history and frozen capability grants survive. Each turn invokes native
`run_conversation()` once. Credential values and hashes never enter cache identities.
