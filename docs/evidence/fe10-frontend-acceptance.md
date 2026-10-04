# FE-10 Frontend Acceptance Evidence

Date: 2026-09-30

## Scope

All frontend commands ran in `../NetworkClaw/web2`.
`NetworkClaw/web` was not started, modified, installed, built, or tested.

## Gates

- `npm run typecheck`: passed.
- `npm run build`: passed; only the existing Vite chunk-size warning remains.
- `npm test -- --run`: 45 test files, 332 passed, 1 skipped.
- `make validate-contracts`: passed.
- `make test`: 80 integration tests passed, including capability schema, skill manifest,
  event catalog, process tree, bundle, and web2 readiness checks.
- `make integration-test`: passed; combination matrix reports 13/13 scenarios passed.

## Acceptance Coverage

- Agent revision and session snapshot boundary: `AgentRevisionPicker` and
  `SessionSnapshotSummary` tests, plus the A-07 session snapshot evidence.
- Runtime activity: `RuntimeCapabilityDrawer.test.tsx`, canonical process integration
  tests, and `.integration-state/evidence/event-e06-runtime-browser.json`.
- Skill modes and dependency/trust/release projection: capability and skill catalog
  tests plus `docs/evidence/a07-agent-vertical-acceptance.md`.
- Toolset/atomic grant, deny, unavailable, not-loaded, turn-disabled and child lineage:
  capability projection tests, runtime drawer isolation test, and combination matrix.
- Legacy entry: `/agent-skill-tool` is read-only migration guidance; legacy catalog
  POST/PATCH/DELETE functions and CRUD sections are absent from production `web2`.

## Cleanup

The combination matrix reported no active Gateway/provider processes or sockets. The
test-owned leftover socket was removed after inspection; no `ncg-*` temporary roots
remain.

`full_catalog_verified=false` in the runtime browser report is intentional: the retired
legacy catalog is not used as the runtime authority. New revision/snapshot evidence is
provided by the A-07 vertical acceptance and capability contract fixtures.
