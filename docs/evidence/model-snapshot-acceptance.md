# 模型 Snapshot 本地验收（2026-10-03）

NetworkClaw 实现 PostgreSQL 模型配置、管理员 API/页面、公共选择列表、私有 Bearer Snapshot、chatrtmgr 内存 broker 和逐 turn 固定配置；Harness 根据执行身份复用或替换 Agent，保留 Session、历史和冻结权限。Integration 只负责部署输入和组合验收，不复制业务源码。

新增 turn 不逐次请求 Lobby。broker 启动同步，之后每 30 秒同步，5 秒超时；旧快照最后成功确认超过 5 分钟拒绝新 turn。复用已有持久化 admission 的 ProcessID 与本地 process/socket fencing；pin 丢失不自动使用最新配置重跑旧 run。

| 仓库 | 实际入口 | 结果 |
|---|---|---|
| NetworkClaw | `go test -race ./internal/chatrtmgr/... ./internal/lobby/usecase ./internal/lobby/transport/http ./internal/shared/modelconfig ./cmd/chatrtmgr ./cmd/lobby ./tests/integration/harnessinterop -count=1` | 通过；真实 interop 包 219.274 秒 |
| NetworkClaw | `go test -race ./internal/chatrtmgr/forwarder -count=1` | 最终 socket guard 通过 |
| NetworkClaw | `TEST_DB_USER=maxrocketman go test -race ./internal/lobby/repository -run 'TestModelConfiguration|TestHarnessAdmissionPreserves' -count=1 -v` | 3 项通过：事务版本、并发写读、admission process/lease |
| NetworkClaw/web2 | `npm test -- --run` / `npm run typecheck` / `npm run build` | 336 通过、1 跳过；类型检查与构建通过 |
| Harness | `scripts/run_tests.sh -q` | 304 项通过，vendor/closure/doc-link 验证通过 |
| Integration | `make test` | 129 项 Python 测试及 web2-server Go race 通过 |
| Integration | `MODEL_ACCEPTANCE_PGADMIN=maxrocketman make model-snapshot-acceptance MODEL_SNAPSHOT_ARGS=--real-gpt` | 27 项通过；机器报告见 [JSON](model-snapshot-acceptance.json) |
| Integration | `make bundle BUNDLE_OUTPUT=.integration-state/artifacts/model-snapshot-bundle.tar.gz` / `make verify-bundle BUNDLE_OUTPUT=.integration-state/artifacts/model-snapshot-bundle.tar.gz` | 开发 bundle 构建、内容/hash/provenance 与凭证扫描通过 |
| Integration | `DOCKER_BUILDKIT=0 BASE_IMAGE=networkclaw-e06/python-base:3.12.11 CI_WHEELHOUSE=.integration-state/ci/wheelhouse BUNDLE_OUTPUT=.integration-state/artifacts/model-snapshot-bundle.tar.gz NETWORKCLAW_IMAGE_TAG=networkclaw:model-snapshot-validation make image` | Linux/amd64 开发镜像构建通过；非 root 离线 Harness 导入及缺失配置拒绝检查通过 |

组合验收使用临时 PostgreSQL 数据库、两个 Lobby、两个 manager、真实 Gateway 与 provider stub。覆盖同会话 A→B、同名不同连接、协议切换、凭证轮换、在途配置固定、重试不重执行、重启丢失 pin、同步故障/恢复、空快照、停用及实际 GPT。Lobby 停机时的新鲜缓存允许已授权新 turn 执行。实际收敛耗时为 27.458、5.718、26.170、27.450、14.979 秒。测试数据库、临时目录、服务子进程和 socket 均清理。

真实浏览器 walkthrough 也已完成：管理员页面创建/更新/设默认并验证未保存草稿保留，主页面同会话切换模型和低/高 Effort；provider stub 观察到正确模型、参数和增长的历史消息。证据见 [浏览器验收 JSON](model-snapshot-browser-walkthrough.json)。此前配合浏览器进行的组合尝试因缓存未收敛失败；最终独立运行的 27 项报告已经重新生成并通过。

使用缓存的 amd64 基础镜像构建了 `networkclaw:model-snapshot-validation`，容器架构为 `linux/amd64`、运行用户为 `65532:65532`，并完成离线 Harness 导入和缺失显式模型配置的 fail-closed 检查。直接访问 Docker Hub 的构建尝试因认证超时失败；本地构建使用已有的不可变 amd64 基础镜像 digest。

镜像已对所有 14 个保存层及 metadata 扫描，覆盖 10,290 个文件；4 个本地 provider 凭证、Snapshot Bearer token 或 TLS 私钥值均未匹配。该检查只证明已知凭证原值未进入镜像，不替代完整通用 secret 扫描。机器证据见 [镜像凭证检查 JSON](model-snapshot-image-credential-scan.json)。本报告、最终验收 JSON 与扫描记录在构建后更新，当前 bundle/镜像中的文档仍是较早快照；这些更新没有改变业务代码。

收尾期间误停了原有本地开发服务，随后通过 `make dev-up` 恢复；Web2、Lobby 和 chatrtmgr 监听已恢复，manager 的 `/model-config/status` 返回 `ready: true` 并持续同步。验收临时服务已清理，恢复的开发服务保持运行。

边界：组合验收和浏览器 walkthrough 在 Mac/arm64 上运行；第二 manager 使用直接 gRPC，未验证共享双节点发现；Session 创建/归属使用隔离 SQL fixture。全树 Go 仍有既有 `TestCatalogAgent_CRUD`、`TestCatalogAgent_FindByName` migration 029 `legacy_capability_readonly` 失败。本 bundle 是未签名、dirty/customized 开发制品。Linux/amd64 镜像已构建，但未完成 Ubuntu 22.04 部署验收；Mac 上的 bundle self-test 因提供的 Linux wheelhouse 缺少 `charset-normalizer==3.5.1` 的 Mac 兼容 wheel 而停止，不能作为通过证据。

回滚模型配置也推进版本；部署给 manager 的模型侧输入只有 Lobby URL 和 Bearer Secret 文件（HTTPS 可另设 CA）。模型/provider 凭证仅经私有 snapshot 和受信 Host 输入传输，不落 broker 磁盘、公共事件或 Session 能力快照。用户工作区的其他未提交改动保留；本轮未提交 Git。
