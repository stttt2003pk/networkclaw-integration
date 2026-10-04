# X-02 Bundle、schema drift 和交付验收

状态：**已完成（2026-09-29）**。

## 产物与追溯

- Bundle：`.integration-state/artifacts/x02-bundle.tar.gz`
- Bundle SHA-256：`5ffe3fec63525571115dab9ad83d5f0245f5555c2877d8851082463481fe5c3a`
- Manifest 记录三仓 tree hash、commit、dirty/diff hash、Harness vendor tree hash、Hermes patch hash、Host Protocol `1.0` 和 Ubuntu 22.04/amd64 target。
- Bundle 包含 capability snapshot、Skill release manifest、event catalog、Host Protocol schema、Hermes inventory/catalog、Go API 来源和 Web 类型/测试。

## 验证结果

- `make hermes-inventory hermes-catalog hermes-skill-manifest validate-contracts`：通过。
- `make verify-bundle BUNDLE_OUTPUT=.integration-state/artifacts/x02-bundle.tar.gz`：通过。
- 隔离 `tests/bundle/self_test.py`：`status=passed`，13 个阶段全部通过，`failures=[]`、`missing_inputs=[]`，重建 bundle 验证通过，临时 workspace 已清理。
- `make integration-test`：组合矩阵通过，13 个场景通过，cleanup 为 `clean`。
- NetworkClaw `go test ./...`：通过；`git diff --check`：通过。

Drift 和 hash gate 由 `validate-contracts`、Hermes catalog projection、bundle manifest
校验及隔离重建共同覆盖；本地 bundle 因三仓存在未提交改动标记为 `customized=true`，不作为正式 release provenance。

