# R-11 Cross-Repository Release Acceptance

**Date:** 2026-10-02  
**Status:** Passed for the R-11 capability-release acceptance scope.

## Evidence

- Mac arm64 unified entry `make capability-release-acceptance` passed all five stages: release gates, 29 Integration release tests, Harness vendor/Skill tests, 7 admin contract tests, and PostgreSQL transactions/session migration.
- Ubuntu 22.04 Linux/amd64 ran the same five stages from an ephemeral clean snapshot. The run passed 29 Integration tests, 17 Harness vendor/Skill tests, 7 admin contract tests, and the real PostgreSQL database tests.
- The current compiled release contains 64 Toolsets, 101 Tools, 59 Skills, 1 Agent, 1,499 Toolset memberships, 2 Skill dependencies, 3 Agent Tool bindings and 1 Agent Skill binding. Repeated import is idempotent and publish preserves the manifest hash.
- Transaction failure injection passed at `catalog`, `tools`, `toolsets`, `skills`, `dependencies`, `agents`, `bindings`, `release` and `audit`; the stable receipt is `import_transaction_failed`. Hash conflicts return `release_hash_conflict`.
- Session migration evidence covers legacy write rejection, old-session preservation, new-session adoption, publish/rollback snapshot behavior, stale and tampered grant rejection, real Harness resume, and migration up/down.

## Architecture Acceptance Matrix

| # | Requirement | Evidence |
|---:|---|---|
| 1 | Deterministic compile/hash | Clean snapshot repeated discovery/compile and independent check passed. |
| 2 | Fail closed on missing or untrusted dependencies | Integration failure tests cover vendor, unknown dependency, stale revision and trust mutations. |
| 3 | Full source/vendor traceability | 1104-file vendor gate, Skill hashes, Tool schema/source hashes and three-repository provenance are recorded. |
| 4 | Atomic NetworkClaw import | Complete manifest import and nine failure injection stages leave no partial rows. |
| 5 | Idempotent import and immutable published release | Repeated import is idempotent; publish preserves the stored manifest hash; conflicts use stable reason codes. |
| 6 | New and existing session snapshots | Migration test proves new snapshot adoption, old snapshot preservation, rollback and real Harness resume. |
| 7 | Legacy JSON is migration input only | `legacy-write-rejected` and `migration-command-readonly` pass; new sessions use stored revision snapshots. |
| 8 | CI gates without production import | `ci-test.sh` invokes vendor/compile/check/diff and bundle verification; admin import is not a CI default. Both platform acceptance reports and cleanup checks pass. |
| 9 | Runtime boundary preserved | No Agent loop, Tool executor or Skill loader was added to Integration; Hermes vendor tree was not hand-edited. |

## Provenance

The Ubuntu acceptance used temporary commits only for clean-snapshot verification. They are not claims about the real branch histories. The Mac report records the real dirty working trees without modifying or reverting unrelated changes. Hermes source ref is `6005aa1fd9aac8b1024ace50fec8cd1c85a04bae`; the vendor manifest and tree hashes are recorded in the companion JSON report.

## Cleanup And Boundary

The acceptance wrapper verifies removal of its temporary workspace and PostgreSQL schema. The temporary runner, containers, processes and sockets were stopped after evidence capture. No direct edit was made to `networkclaw-harness/vendor/hermes`.

A separate generic full `ci-test.sh` attempt exposed runner-only limitations (missing Helm and root/path assumptions in unrelated full-suite tests). That attempt is retained as a limitation and is not used to claim full CI success. The R-11-specific release gates and cross-repository database acceptance passed on Ubuntu after temporary runner setup.

## Next Step

Freeze the real three-repository revisions in `sources.lock.yaml`, rerun the complete CI on a runner with the required tools, writable storage and normal user permissions, then verify the signed bundle/image inputs before an explicit administrator import/publish. The current dirty worktrees and temporary snapshot commits do not establish publishability.
