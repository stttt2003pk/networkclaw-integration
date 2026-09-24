# Hermes Vendor Upgrade

Hermes source, patches, allowlist, vendor files, runtime closure and Python tests are owned by `networkclaw-harness`. Do not edit `vendor/hermes` from this repository.

## Upgrade Flow

1. In the Harness repository, update the pinned upstream source in `upstream/hermes-source.json`, review the allowlist and patch series, then regenerate the vendor snapshot with `make sync-hermes HERMES_SOURCE=/path/to/clean/pinned-hermes-checkout`.
2. Run `make verify-hermes` and `scripts/run_tests.sh`. Review the generated source commit, patch series, manifest and vendor hashes.
3. With clean NetworkClaw and Harness commits checked out, run `make vendor-status` and `make vendor-compat-test`. The latter runs the Harness vendor verifier, all Harness tests, the Go ↔ Harness combination matrix and the source-lock gate. It writes `.integration-state/evidence/vendor-compat-report.json` and does not produce a release bundle.
4. After all checks pass on clean committed sources, advance the NetworkClaw/Harness pins explicitly with `make vendor-compat-test VENDOR_COMPAT_ARGS=--update-lock`, review `sources.lock.yaml`, and commit the source changes and lock update in their owning repositories. The command refuses to advance a dirty source tree.
5. Re-run `make vendor-status` and `make vendor-compat-test` against the committed sources. Generate a release bundle only through the normal release gate after the source lock is clean and verified.

The compatibility report records NetworkClaw, Harness and Integration commit/tree identities, source-lock state, Hermes upstream ref, patch-series hash, vendor tree hash, each gate's command/exit code/output tail, and whether the lock was advanced. The previous lock is the manual recovery point: restore its NetworkClaw and Harness commits, restore the matching lock entry, then rerun the gates. Failed checks never advance the lock or generate a formal bundle.

## Failure Fixture

`make vendor-compat-test VENDOR_COMPAT_ARGS=--vendor-fixture` copies Harness to a temporary directory, tampers with one vendored file, and verifies that `verify-hermes-vendor.py` rejects the snapshot before tests, lock updates, or bundle creation. The temporary copy is removed after the run. This tests failure blocking without mutating the customer's Harness checkout.

## Report

Default report path: `.integration-state/evidence/vendor-compat-report.json`. The report is local build evidence and is not committed automatically; archive it with the CI run when reviewing a vendor change.
