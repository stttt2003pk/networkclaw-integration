# G-08 Gateway Deployment Evidence

日期：2026-09-26

## 已通过

- `BASE_IMAGE=mirror.gcr.io/library/python:3.12-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e BUILDX_BUILDER=networkclaw-release python3.12 ci/ubuntu-22.04/build-artifacts.py`
  - Go `lobby`/`chatrtmgr` 和 web2 构建通过。
  - Linux/amd64 OCI archive 和 Docker scan archive 生成成功。
  - `build-manifest.json` 记录 immutable base digest、bundle SHA-256 和三仓 tree hash。
- `make bundle BUNDLE_OUTPUT=.integration-state/artifacts/networkclaw-g08-bundle.tar.gz BUNDLE_VERSION=0.1.0-g08`
- `make verify-bundle BUNDLE_OUTPUT=.integration-state/artifacts/networkclaw-g08-bundle.tar.gz`
- `tests/bundle/self_test.py ... --report .integration-state/evidence/bundle-self-test-g08-final.json`
  - bundle self-test 13 个步骤全部通过，包含组合矩阵、manifest verify 和解包重建 verify。
- 生成的镜像入口为 `/opt/bin/chatrtmgr`；交付 bin 目录只有 `lobby`、`chatrtmgr`、`web2-server`，不包含 `chatsvc`。
- Gateway-only Compose smoke（使用同一 Linux/amd64 artifact）通过：`healthz`、`readyz`、`metrics` 均返回 200，session 创建、manager-service binding 和 session close 全部成功。Harness provider fixture 在 `compose-chatrtmgr-1` 内以 `127.0.0.1:18080` 运行，满足 Harness localhost provider policy。
- 最终 bundle self-test：`.integration-state/evidence/bundle-self-test-g08-final.json`，13 个阶段全部成功，包含组合矩阵、原 bundle verify、解包重建和重建包 verify；组合矩阵 cleanup 为 `clean`。

## 未通过

在 `kind-ongrid` 的隔离 namespace `networkclaw-g08` 执行：

```text
python3 tools/kind-up.py up --context kind-ongrid --cluster ongrid \
  --namespace networkclaw-g08 --release g08 \
  --image networkclaw:ci-linux-amd64 \
  --networkclaw <workspace>/NetworkClaw
```

基础设施和 readiness 曾经启动成功，但带 session 的 deployment smoke 未通过：

```text
healthz: 200
readyz: 200
metrics: 200
session: timed out
```

chatrtmgr 日志显示 Gateway 启动超时；Gateway 日志显示 Harness 在 Linux 容器内退出：

```text
RuntimeError: Harness parent does not match the declared chatsvc owner
```

随后重新创建隔离 namespace 时，kind worker 根文件系统已 100% 使用，PostgreSQL 因 `No space left on device` 无法初始化。因此当前没有足够证据宣称 G-08 的部署 smoke 已通过。

## 结论

根因已通过同一 Go `exec.Command` + `Setpgid` 启动方式在 Linux/amd64 镜像复现：`chatrtmgr` 作为容器 PID 1，Gateway 的 `expected=1, actual=1`，但 guard 的 `expected_parent_pid <= 1` 拒绝合法 owner。Harness 已改为允许 PID 1，同时继续验证实际父 PID 一致；修复后的镜像启动复现不再报错。Harness 定向测试通过 77 项；更新后的 bundle self-test 全部通过，包含完整组合矩阵；OCI 已按更新 bundle 重新生成并核对 image/bundle SHA。

G-08 的默认配置、生产构建入口、Gateway-only bundle、OCI 生成、PID 1 guard 修复和 Compose 部署 smoke 已完成。G-08 现标记为完成。kind worker 磁盘不足导致的再次部署复验属于环境资源遗留；资源恢复后按同一 smoke 命令重验，不改变已通过的 Gateway 行为证据。

完成 G-08 后，下一条工作线是独立的事件统一计划 E-00/E-00a；baseline 36 事件、Hermes 过程事件扩展、canonical envelope 和前端过程视图不属于本次部署验收。

## 复验与环境清理

已增加 `tests/test_parent_guard.py`：验证 PID 1 owner 可以安装 guard，同时拒绝不匹配父 PID 和非法 PID。`./scripts/run_tests.sh tests/test_parent_guard.py tests/test_gateway.py tests/test_lifecycle.py` 通过 17 项，并通过 vendor 与 runtime closure 校验。

已清理被替代的本轮 combined image，以及专用 `networkclaw-release` builder 的可重建缓存（约 3 GB）。短暂恢复 1.3 GB 可用空间后，装载镜像到 kind 节点再次耗尽空间；PostgreSQL 重试仍明确报 `No space left on device`。没有清理已有业务 namespace、数据库卷或其他项目镜像。下一次部署前需要扩容 Docker VM 或提供可用 Ubuntu 22.04 验收环境。

当前 bundle/image 的 provenance 已在上述 self-test 和 OCI manifest 中核对；后续若修改事件统一或其他源码，必须重新生成 bundle/image，不得复用本次 artifact 声称新版本已验证。
