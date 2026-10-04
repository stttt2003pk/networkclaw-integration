.PHONY: doctor bootstrap dev-up dev-down compose-up compose-down compose-status restart-go restart-gateway logs collect-diagnostics resolve-sources validate-contracts validate-events hermes-inventory hermes-catalog hermes-skill-manifest capability-release-vendor-check capability-release-discover capability-release-compile capability-release-check capability-release-diff test integration-test combination-matrix event-process-check fault-fixtures provider-stub bundle verify-bundle bundle-self-test kind-up kind-down ci-test image security-scan vendor-status vendor-compat-test

SHELL := /bin/sh
BUNDLE_OUTPUT ?= .integration-state/artifacts/networkclaw-bundle.tar.gz
BUNDLE_VERSION ?= 0.1.0-local
BUNDLE_RELEASE ?=
BUNDLE_SIGNING_KEY ?=
BUNDLE_CAPABILITY_RELEASE ?= 1
BUNDLE_PUBLIC_KEY ?=
CAPABILITY_RELEASE_OUTPUT ?= .integration-state/artifacts/capability-release
CAPABILITY_RELEASE_OPERATOR ?= local
CAPABILITY_RELEASE_JOB_ID ?= manual
CAPABILITY_RELEASE_NETWORKCLAW ?= ../NetworkClaw
CAPABILITY_RELEASE_AGENTS ?= tests/fixtures/capability-release/agent-discovery-v1.json
CAPABILITY_RELEASE_PUBLISHED ?= tests/fixtures/capability-release/valid-release-v1.json
CAPABILITY_MIGRATION_REPORT ?= .integration-state/evidence/capability-session-migration-v1.json

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

hermes-inventory:
	@.venv/bin/python ./tools/generate-hermes-inventory.py

hermes-catalog: hermes-inventory
	@.venv/bin/python ./tools/project-hermes-catalog.py

hermes-skill-manifest:
	@.venv/bin/python ./tools/generate-skill-manifest.py

capability-release-vendor-check:
	@.venv/bin/python ./tools/capability-release.py vendor-check --report .integration-state/evidence/capability-release-vendor-gate.json

capability-release-discover:
	@.venv/bin/python ./tools/capability-release.py discover --agents "$(CAPABILITY_RELEASE_AGENTS)" --output .integration-state/evidence/capability-discovery-v1.json

capability-release-compile: capability-release-discover
	@.venv/bin/python ./tools/capability-release.py compile --discovery .integration-state/evidence/capability-discovery-v1.json --output .integration-state/evidence/capability-release-v1.json --operator "$(CAPABILITY_RELEASE_OPERATOR)" --job-id "$(CAPABILITY_RELEASE_JOB_ID)"

capability-release-check: capability-release-compile
	@.venv/bin/python ./tools/capability-release.py check --manifest .integration-state/evidence/capability-release-v1.json --report .integration-state/evidence/capability-release-check-v1.json

capability-release-diff: capability-release-check
	@.venv/bin/python ./tools/capability-release.py diff --published "$(CAPABILITY_RELEASE_PUBLISHED)" --candidate .integration-state/evidence/capability-release-v1.json --output .integration-state/evidence/capability-release-diff-v1.json --operator "$(CAPABILITY_RELEASE_OPERATOR)" --job-id "$(CAPABILITY_RELEASE_JOB_ID)"

.PHONY: capability-release-export capability-release-verify-export
capability-release-export: capability-release-diff
	@.venv/bin/python ./tools/capability-release.py export --manifest .integration-state/evidence/capability-release-v1.json --check .integration-state/evidence/capability-release-check-v1.json --diff .integration-state/evidence/capability-release-diff-v1.json --published "$(CAPABILITY_RELEASE_PUBLISHED)" --output "$(CAPABILITY_RELEASE_OUTPUT)" --operator "$(CAPABILITY_RELEASE_OPERATOR)" --job-id "$(CAPABILITY_RELEASE_JOB_ID)"

capability-release-verify-export:
	@.venv/bin/python ./tools/capability-release.py verify-export "$(CAPABILITY_RELEASE_OUTPUT)"

.PHONY: capability-release-admin-contract-test
capability-release-admin-contract-test:
	@NETWORKCLAW_INTEGRATION_ROOT="$(CURDIR)" CAPABILITY_RELEASE_CLIENT_PYTHON="$(CURDIR)/.venv/bin/python" CAPABILITY_RELEASE_CONTRACT_REPORT="$(CURDIR)/tests/fixtures/capability-release/admin-contract-v1.json" go -C "$(CAPABILITY_RELEASE_NETWORKCLAW)" test -race ./internal/lobby/transport/http -run TestCapabilityReleaseHTTPContract -count=1
	@NETWORKCLAW_PATH="$(CAPABILITY_RELEASE_NETWORKCLAW)" .venv/bin/python -m unittest discover -s tests -p test_capability_release_admin.py -v

.PHONY: capability-release-session-migration-test
capability-release-session-migration-test:
	@test -n "$$CAPABILITY_MIGRATION_TEST_DSN" || (echo "CAPABILITY_MIGRATION_TEST_DSN is required for the isolated PostgreSQL fixture" >&2; exit 1)
	@mkdir -p "$(dir $(CAPABILITY_MIGRATION_REPORT))"
	@NETWORKCLAW_INTEGRATION_ROOT="$(CURDIR)" CAPABILITY_MIGRATION_TEST_REPORT="$(abspath $(CAPABILITY_MIGRATION_REPORT))" go -C "$(CAPABILITY_RELEASE_NETWORKCLAW)" test -race ./tests/integration/harnessinterop -run TestCapabilityMigrationPublishedSessionsAndRollback -count=1 -v

.PHONY: capability-release-acceptance
capability-release-acceptance: ## 验证跨仓 release；要求独立 PostgreSQL fixture
	@.venv/bin/python ./tools/run-capability-release-acceptance.py

.PHONY: model-snapshot-acceptance
model-snapshot-acceptance: ## 真实双 Lobby/双 manager 验收；需要可创建临时库的 PostgreSQL 和 redis-server
	@.venv/bin/python ./tools/run-model-snapshot-acceptance.py $(MODEL_SNAPSHOT_ARGS)

.PHONY: session-execution-acceptance
session-execution-acceptance: ## 公开无 Profile 会话及原生 Tool/Skill/delegation 双节点验收
	@.venv/bin/python ./tools/run-model-snapshot-acceptance.py --session-execution --report .integration-state/evidence/session-execution-acceptance.json $(SESSION_EXECUTION_ACCEPTANCE_ARGS)

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

bundle: $(if $(filter 1,$(BUNDLE_CAPABILITY_RELEASE)),capability-release-vendor-check capability-release-diff)
	@.venv/bin/python ./tools/build-bundle.py --output "$(BUNDLE_OUTPUT)" --bundle-version "$(BUNDLE_VERSION)" $(if $(NETWORKCLAW_PATH),--networkclaw "$(NETWORKCLAW_PATH)") $(if $(HARNESS_PATH),--harness "$(HARNESS_PATH)") $(if $(BUNDLE_RELEASE),--release) $(if $(filter 1,$(BUNDLE_CAPABILITY_RELEASE)),--capability-release) $(if $(BUNDLE_SIGNING_KEY),--signing-key "$(BUNDLE_SIGNING_KEY)")

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

.PHONY: session-dev-lifecycle-acceptance
session-dev-lifecycle-acceptance: ## 使用独立状态、端口和数据库验收 dev-up/down
	@.venv/bin/python ./tools/session_dev_lifecycle_acceptance.py

.PHONY: session-image-acceptance
session-image-acceptance: ## 在交付的 Linux/amd64 镜像中验收无 Profile 原生会话
	@.venv/bin/python ./tools/session_image_acceptance.py --image "$(NETWORKCLAW_IMAGE_TAG)" --bundle "$(BUNDLE_OUTPUT)"
