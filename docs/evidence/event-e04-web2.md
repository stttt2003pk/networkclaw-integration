# E-04 lobby/web2 canonical event consumption

## Scope

E-04 makes the canonical envelope the authoritative input for the lobby to web2
user projection. The lobby validates identity and size, keeps the raw envelope in
`canonical_event`, and does not rename or collapse the event type. Web2 reduces
the envelope into a process tree while retaining the original event ledger.

```text
Harness Gateway canonical envelope
  -> chatrtmgr canonical relay
    -> lobby StreamChunk.canonical_event
      -> web2 parseStreamFrame
        -> reduceProcessTree / semantic projection
          -> ProcessTimeline + AgentCard + ToolCallCard + interaction cards
```

## Implemented behavior

- `delegation.requested` and `delegation.resolved` create allocation nodes with
  task index, child session, parent turn and grant/deny state.
- `subagent.start`, `subagent.text`, `subagent.thinking`,
  `subagent_progress` and `subagent.complete` update independent child Agent
  cards. Child events are attached through session and lineage fields.
- `tool.generating`, `tool.started`, `tool.progress` and `tool.completed` merge
  by `invocation_id`; tool cards remain attached to the owning child Agent.
- `plan.updated`, `artifact.created`, approval and clarification events are
  projected from their canonical payloads, with stable IDs and no text parsing.
- `heartbeat`, context and provider retry facts are display-limited diagnostics;
  usage/provider attempt facts remain in the ledger but are excluded from the
  ordinary user timeline by default.
- `reasoning.delta` is hidden unless the producer marks the payload as an
  authorized summary. Raw reasoning is never projected into the ordinary chat.
- Duplicate `event_id`s are ignored, out-of-order events are retained and sorted
  by lineage/sequence, session/run mismatches are dropped, and the first root
  terminal event latches the UI. Late events remain audit facts and cannot revive
  a completed run.
- E-07 removes legacy chunks from the real-time reducer: `HomePage` ignores
  non-canonical stream frames and all approval/clarification state comes from
  canonical interaction events. Legacy chunks remain readable only through the
  stored historical message path and isolated compatibility tests.

## Evidence

### Web2 contract and UI tests

- `web2/src/api/chat.test.ts` verifies nested and direct canonical envelopes,
  original event names, event identity and terminal metadata.
- `web2/src/api/semanticProjection.test.ts` verifies process-tree projection,
  child lineage, tools, artifacts, interactions, event deduplication, ordering,
  terminal latch and reasoning visibility.
- `web2/src/components/CanonicalProcess.integration.test.tsx` verifies the
  rendered delegation, child Agent, tool, artifact and pending approval flow.
- `web2/src/components/ProcessTimeline.test.tsx` verifies delegation, plan,
  artifact and interaction rendering plus restricted diagnostic filtering.

### Lobby and relay tests

- `NetworkClaw/internal/lobby/usecase/canonical_event_test.go` verifies canonical
  identity, session/run validation and the 64 KiB limit.
- `NetworkClaw/internal/chatrtmgr/transport/grpc/canonical_event_test.go`
  verifies unknown event preservation, `event_id`/payload byte retention,
  terminal preservation and oversized-envelope rejection.
- `NetworkClaw/internal/lobby/transport/websocket/handler_test.go` verifies the
  canonical event remains a websocket `canonical_event` frame.

## Reproduction

From `NetworkClaw/web2`:

```text
npm test -- --run
npm run typecheck
npm run build
```

Observed result on 2026-09-27: 36 test files, 322 tests passed; typecheck and
Vite production build passed.

From `NetworkClaw`:

```text
go test ./internal/lobby/... ./internal/chatrtmgr/...
```

Observed result on 2026-09-27: all lobby and chatrtmgr packages passed.

## E-07 boundary

The production websocket path emits only `canonical_event` plus `done`/`error`
control frames. The old chunk projection remains source-compatible for historical
reads and rollback fixtures, but has no production consumer.
