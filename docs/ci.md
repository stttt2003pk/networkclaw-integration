# Ubuntu 22.04 / Linux amd64 CI

I-08 的正式目标是 Ubuntu 22.04、Linux/amd64。Mac 只承担快速反馈，不能替代本门禁。

## 本地或 CI 运行

```bash
NETWORKCLAW_PATH=/workspace/NetworkClaw \
HARNESS_PATH=/workspace/networkclaw-harness \
make ci-test
make image
```

`ci/ubuntu-22.04/ci-test.sh` 分阶段执行 NetworkClaw 全量 `go test -race ./...`、Harness vendor/runtime 测试、Integration 测试、组合矩阵、bundle/manifest 校验和隔离 bundle self-test，并写入 `.integration-state/evidence/ubuntu-22.04-ci.json`。失败阶段保留在机器报告中，不把失败伪装为成功。

`ci/ubuntu-22.04/build-artifacts.py` 使用 `GOOS=linux GOARCH=amd64 CGO_ENABLED=0` 构建 `lobby`、`chatrtmgr`、`chatsvc`，在 `--platform=linux/amd64 --network=none` 下构建离线 Harness/Go combined OCI image，并输出 OCI 发布归档、可供 Trivy `--input` 使用的 Docker archive sidecar、SHA-256 和 `build-manifest.json`。OCI 是发布输入，Docker archive 只用于扫描，不替代 OCI 产物。

仓库中的 `.github/workflows/ubuntu-22.04.yml` 是 GitHub Actions 的实际入口；`ci/pipelines/github-actions.yml` 保留为可移植的 pipeline 模板。构建清单分别记录 Ubuntu 22.04 runner 和 Debian 12 Python runtime base，避免把 runtime OS 误标为 Ubuntu。

私有客户仓库通过 Actions variables 覆盖 `NETWORKCLAW_REPOSITORY`、`NETWORKCLAW_REF`、`HARNESS_REPOSITORY` 和 `HARNESS_REF`，并配置可读取两个仓库的 `SOURCE_REPO_TOKEN` secret；默认 ref 是 `sources.lock.yaml` 中锁定的 commit。变更 ref 时必须同步更新 lock 并通过 source-lock gate。

正式 CI 还必须运行 `govulncheck ./...` 并调用 `make security-scan IMAGE_ARCHIVE=...`。后者要求 `syft` 生成 CycloneDX SBOM，要求 `trivy` 对 Docker archive sidecar 执行 HIGH/CRITICAL 漏洞（忽略尚无修复的条目）、secret 和 misconfiguration 扫描；CI 先预热固定版本的漏洞数据库，再以 skip-update 模式运行，工具缺失、数据库预热失败或扫描失败均为失败。

依赖边界：Harness 的 `requirements*.lock` 和 `offline/wheels` 提供离线 Python 依赖；Go module cache/base image 由 Ubuntu runner 或预热的 CI 缓存提供。CI checkout 必须通过 `sources.lock.yaml` 验证 NetworkClaw/Harness 的 commit/tree 和 Integration 的 clean tree hash；由于 lock 文件属于 Integration 自身，不能把 Integration commit 自引用到 lock 中。生产 release 不允许 dirty/customized source。
