.PHONY: doctor dev-up dev-down test integration-test bundle verify-bundle image

SHELL := /bin/sh

doctor:
	@./tools/doctor.sh

dev-up:
	@printf '%s\n' 'integration: dev-up is not implemented yet' >&2; exit 2

dev-down:
	@printf '%s\n' 'integration: dev-down is not implemented yet' >&2; exit 2

test:
	@printf '%s\n' 'integration: test is not implemented yet' >&2; exit 2

integration-test:
	@printf '%s\n' 'integration: integration-test is not implemented yet' >&2; exit 2

bundle:
	@printf '%s\n' 'integration: bundle is not implemented yet' >&2; exit 2

verify-bundle:
	@printf '%s\n' 'integration: verify-bundle is not implemented yet' >&2; exit 2

image:
	@printf '%s\n' 'integration: image is not implemented yet' >&2; exit 2
