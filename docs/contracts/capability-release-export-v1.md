# Capability Release Export v1

R-06 exports an immutable directory after rechecking the candidate manifest against
the current Harness vendor, its check report, and the diff calculated from the
explicit baseline snapshot. The baseline in the default Make workflow is a test
fixture; it is not evidence of a production published release.

```text
capability-release/
  manifest/capability-release.v1.json
  reports/check.json
  reports/diff.json
  migration/migration-plan.json
  provenance/source-lock.json
  provenance/published-release.json
  provenance/vendor.json
  audit/compile.json
  audit/diff.json
  audit/export.json
  schemas/capability-release-v1.schema.json
  verify.py
  artifact_scan.py
  capability_contract.py
  checksums.sha256
```

`source-lock.json` is a frozen `capability-release-sources.v1` snapshot of the
manifest's three source identities, protocol and target. It records the exact
compiler input, including dirty trees and optional Git commits, and works without
Git. The workspace's build `sources.lock.yaml` is a separate input: it may describe
older commits and is not copied or presented as the identity of this artifact.

Vendor provenance includes pinned source identity, manifest/tree hashes,
allowlist/patch-series hashes, patch file hashes, and the verified file count.
Skill bodies and provider credentials are excluded. Export reuses the bundle
content scanner and rejects sensitive JSON fields, local absolute paths and unsafe
support-file paths. Audit identities use bounded identifiers, not free-form text.

Compile and diff write `<output>.audit.json` by default; `--audit` overrides the
location. Each audit records operation, release id/hash, source identities,
`--operator`, `--job-id`, result and stable reason code. Failed operations have
`status=failed` and `result=failed`, never a published marker. When input cannot be
read safely, unavailable release identities are null. Audit metadata stays outside
the release hash. Successful compile/diff receipts are required for export and are
included in its checksums.

Export stages all files, verifies the complete directory, then renames it into
place. An existing destination is rejected and preserved. Failure removes staging
files and writes an external failure audit. Repeated exports of the same inputs
and audit identities have identical file bytes and checksum records.

```sh
make capability-release-export \
  CAPABILITY_RELEASE_OUTPUT=.integration-state/artifacts/my-release \
  CAPABILITY_RELEASE_OPERATOR=release-ci \
  CAPABILITY_RELEASE_JOB_ID=build-001
make capability-release-verify-export \
  CAPABILITY_RELEASE_OUTPUT=.integration-state/artifacts/my-release
```

After relocation, run `python -B verify.py` inside the artifact, or
`python -B /relocated/artifact/verify.py` from another directory. Python 3.12 and
the existing `jsonschema` dependency are required; no original repository,
Harness process, Git checkout, YAML lock file or absolute source path is read.
The verifier checks the exact file set, SHA-256 records, schema/canonical hash,
check/diff/migration/source/vendor/audit associations and content restrictions.
It writes no files. The root checksum list is the artifact checksum; its hash is
returned as `checksum_hash` without embedding a self-referential checksum.

Checksums verify integrity and associations, not a publisher's signature. The
artifact remains a draft release input. Import/publish authorization belongs to
R-07/R-08, and bundle/CI integration belongs to R-10.
