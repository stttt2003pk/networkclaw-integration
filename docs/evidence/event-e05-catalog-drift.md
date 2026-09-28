# E-05 canonical catalog and capability drift gate

## Gate

`tools/check_event_catalog.py` is the Integration drift check for the canonical
event vocabulary. It reads the versioned catalog and verifies:

- Harness `EVENTS` and `PROCESS_EXTENSIONS` exactly match the catalog.
- Harness `ALL_EVENTS` is the union advertised by `capabilities.report`.
- Go lobby exposes an opaque `canonical_event` carrier and validates identity
  and size without maintaining a second event list.
- web2 has explicit canonical handlers where it projects user state and an
  explicit `process.unknownEvents` bucket for control, diagnostic or future
  events it does not render.

The checker emits the generated validation report
[`event-catalog-consumer-report-v1.json`](../../schemas/events/event-catalog-consumer-report-v1.json).
The report currently covers 36 baseline events and 20 process extensions.

## Drift behavior

`tests/test_event_catalog_drift.py` runs the checker against the current
workspace and against temporary catalogs with one event added or removed. Both
mutations fail the gate. The test also compares the generated report with the
checked-in report, so a consumer or catalog change cannot silently leave stale
validation data.

The Integration `Makefile` exposes the same gate through `make validate-events`
and makes `make test` depend on it.

## Runtime capability evidence

Harness `tests/test_host.py::test_version_handshake_and_capability_catalog`
asserts that the runtime `capabilities.report.payload.events` set equals
`ALL_EVENTS`, including all 20 process extensions. This verifies the report is
not merely a static catalog check.

## Reproduction

```text
make validate-events
python3.12 -m unittest tests.test_event_catalog_drift tests.test_event_contracts
.venv/bin/python -m pytest -q tests/test_host.py
```

Observed result on 2026-09-27: the drift gate, mutation tests, event contract
tests and Harness capability tests passed.

## Controlled unknown policy

The Go relay remains opaque and preserves unknown event names. web2 records
events it does not explicitly project in `ProcessTreeState.unknownEvents`; it
does not rename them or infer user facts from their text. This makes adding a
new event a visible catalog/consumer decision instead of a silent projection
loss.
