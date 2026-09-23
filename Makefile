.PHONY: doctor bootstrap dev-up dev-down restart-go restart-harness logs collect-diagnostics resolve-sources validate-contracts test integration-test combination-matrix fault-fixtures provider-stub bundle verify-bundle bundle-self-test ci-test image security-scan

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

restart-go:
	@.venv/bin/python ./tools/dev.py restart-go

restart-harness:
	@.venv/bin/python ./tools/dev.py restart-harness

logs:
	@.venv/bin/python ./tools/dev.py logs

collect-diagnostics:
	@.venv/bin/python ./tools/dev.py collect-diagnostics

resolve-sources:
	@python3 ./tools/resolve_sources.py --json

validate-contracts:
	@.venv/bin/python ./tools/validate-contracts.py

verify-sources-lock:
	@.venv/bin/python ./tools/verify_sources_lock.py

test: validate-contracts
	@.venv/bin/python -m unittest discover -s tests -v

integration-test:
	@./tools/integration-test.sh

combination-matrix:
	@.venv/bin/python ./tools/run-combination-matrix.py

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

ci-test:
	@./ci/ubuntu-22.04/ci-test.sh

security-scan:
	@./ci/ubuntu-22.04/security-scan.sh "$(IMAGE_ARCHIVE)"

image:
	@python3.12 ./ci/ubuntu-22.04/build-artifacts.py
