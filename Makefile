.PHONY: doctor bootstrap dev-up dev-down compose-up compose-down compose-status restart-go restart-gateway logs collect-diagnostics resolve-sources validate-contracts validate-events test integration-test combination-matrix event-process-check fault-fixtures provider-stub bundle verify-bundle bundle-self-test kind-up kind-down ci-test image security-scan vendor-status vendor-compat-test

SHELL := /bin/sh
BUNDLE_OUTPUT ?= .integration-state/artifacts/networkclaw-bundle.tar.gz
BUNDLE_VERSION ?= 0.1.0-local
BUNDLE_RELEASE ?=
BUNDLE_SIGNING_KEY ?=
BUNDLE_PUBLIC_KEY ?=

doctor:
	@./tools/doctor.sh

bootstrap:
	@python3.12 -m venv .venv
	@.venv/bin/python -m pip install -e .

dev-up:
	@.venv/bin/python ./tools/dev.py up

dev-down:
	@.venv/bin/python ./tools/dev.py down

compose-up:
	@.venv/bin/python ./tools/compose.py up

compose-down:
	@.venv/bin/python ./tools/compose.py down

compose-status:
	@.venv/bin/python ./tools/compose.py status

restart-go:
	@.venv/bin/python ./tools/dev.py restart-go

restart-gateway:
	@.venv/bin/python ./tools/dev.py restart-gateway

logs:
	@.venv/bin/python ./tools/dev.py logs

collect-diagnostics:
	@.venv/bin/python ./tools/dev.py collect-diagnostics

resolve-sources:
	@python3 ./tools/resolve_sources.py --json

validate-contracts:
	@.venv/bin/python ./tools/validate-contracts.py

validate-events:
	@.venv/bin/python ./tools/check_event_catalog.py --report .integration-state/evidence/event-catalog-consumer-report.json

verify-sources-lock:
	@.venv/bin/python ./tools/verify_sources_lock.py

test: validate-contracts validate-events
	@.venv/bin/python -m unittest discover -s tests -v
	@GO111MODULE=off go test -race ./tools/web2-server

integration-test:
	@./tools/integration-test.sh

combination-matrix:
	@.venv/bin/python ./tools/run-combination-matrix.py

event-process-check:
	@.venv/bin/python ./tools/check_event_process.py

fault-fixtures:
	@.venv/bin/python -m unittest discover -s tests -p 'test_fault_fixtures.py' -v

provider-stub:
	@.venv/bin/python ./tests/fixtures/provider_stub/server.py

bundle:
	@.venv/bin/python ./tools/build-bundle.py --output "$(BUNDLE_OUTPUT)" --bundle-version "$(BUNDLE_VERSION)" $(if $(NETWORKCLAW_PATH),--networkclaw "$(NETWORKCLAW_PATH)") $(if $(HARNESS_PATH),--harness "$(HARNESS_PATH)") $(if $(BUNDLE_RELEASE),--release) $(if $(BUNDLE_SIGNING_KEY),--signing-key "$(BUNDLE_SIGNING_KEY)")

verify-bundle:
	@.venv/bin/python ./tools/verify-bundle.py "$(BUNDLE_OUTPUT)" $(if $(BUNDLE_PUBLIC_KEY),--public-key "$(BUNDLE_PUBLIC_KEY)")

bundle-self-test:
	@python3.12 ./tests/bundle/self_test.py "$(BUNDLE_OUTPUT)" --report .integration-state/evidence/bundle-self-test.json

kind-up:
	@python3 ./tools/kind-up.py up

kind-down:
	@python3 ./tools/kind-up.py down

ci-test:
	@./ci/ubuntu-22.04/ci-test.sh

security-scan:
	@./ci/ubuntu-22.04/security-scan.sh "$(IMAGE_ARCHIVE)"

vendor-status:
	@.venv/bin/python ./tools/vendor_status.py

vendor-compat-test:
	@.venv/bin/python ./tools/vendor_compat_test.py $(VENDOR_COMPAT_ARGS)

image:
	@python3.12 ./ci/ubuntu-22.04/build-artifacts.py
