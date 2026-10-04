# NetworkClaw Integration 组合交付计划

## 目标

本计划把 `networkclaw`、`networkclaw-harness` 和本仓库组合成一个客户可继续开发、调试、升级、构建和部署的工程体系。

本计划解决的不是在 integration 中重写 Go 或 Hermes，而是把三仓库之间的联动责任做成可复验的工具链：

```text
三个独立 Git 仓库
  -> 本地 Mac 联调
  -> 组合协议/故障验收
  -> 自包含源码 bundle
  -> Ubuntu 22.04 Linux/amd64 CI
  -> 镜像与部署输入
```

## 与现有计划的关系

`networkclaw-harness/src/networkclaw_harness/docs/plan/py_and_harness.md` 主要描述 Harness 内部语义和 Python 侧验收；`go_and_harness.md` 主要描述 Go adapter、Host Protocol 和跨进程目标。它们不能单独证明客户交付链完整。

本计划承接以下未闭合项：

| 旧计划问题 | Integration 承接任务 |
|---|---|
| Go ↔ Python takeover、late event/control、provider/transport 组合证据不集中 | I-04、I-05 |
| 本地三个源码工作树如何共同启动和调试未固化 | I-02、I-03 |
| dirty/custom source 如何构建且不冒充官方 release | I-06 |
| bundle 脱离原始 Git/绝对路径后能否继续构建未证明 | I-06、I-07 |
| Mac 本地校验与 Ubuntu 22.04 正式构建边界未固化 | I-02、I-08 |
| compatibility/build manifest 只记录旧双仓状态 | I-01、I-06、I-08 |
| vendor 更新后如何重新跑组合验收未固化 | I-09 |
| 部署组如何消费 bundle/image/manifest 未固化 | I-10 |

旧计划中的单仓库能力仍然必须在其所属仓库保持通过；Integration 任务不会把这些能力复制一份。

## Harness Gateway 目标架构

当前跨仓库目标已经确定为：

```text
user_id -> 一个 Harness Gateway 进程
             -> 多个 session_id
                -> 各自独立的 Hermes session/runtime
                   -> 各自按 agent_id 选择或重建 Agent
```

Gateway 将最终替代 chatsvc 承接用户亲和、session/lease 和 Host Protocol 事件；chatrtmgr 仍负责用户级进程亲和、UDS、进程生命周期和故障重启；现有 Harness `HermesHostAdapter`、`_HermesSession` 和 Hermes runtime 继续负责 Agent/turn 执行生命周期。迁移重点是新增 Gateway 外壳和 `agent_id` 配置接线，不是重写 Adapter 或 Hermes Agent loop。详细职责、故障范围和完成度见 [Harness Gateway 亲和与执行边界](../architecture/harness-gateway-affinity.md)。

可执行任务拆分见：

- [Harness Gateway 替代 chatsvc 执行方案](harness-gateway-replacement-plan.md)：先完成 Gateway 直连、兼容传输、组合验收和 chatsvc 移除。
- [Harness 事件统一设计与执行计划](event-unification-design-and-plan.md)：在 Gateway 替代完成后，单独推进 baseline 36 个事件、Hermes 过程事件扩展和前端过程视图的 canonical envelope、原名透传和下游统一。

该架构正在按独立迁移计划实施：G-01 至 G-08 已完成。G-08 已将默认配置、生产构建入口、Gateway-only bundle、Linux/amd64 OCI 和 Compose 部署 smoke 切换到 Gateway；合法 PID 1 owner guard 已在 Harness 修复并通过定向、组合矩阵和最终 bundle self-test。kind worker 的磁盘不足仍是平台资源恢复后的重验项，不是 Gateway 功能阻塞。baseline 36 个事件、Hermes 过程事件扩展和前端过程视图由独立事件计划承接，下一步先执行 E-00/E-00a。

## 责任边界

以下按客户团队职责建议主责，实际团队名称可替换，但源码所有权不变：

| 团队 | 主责 | 不负责 |
|---|---|---|
| 后台组 | NetworkClaw Go 后台、Host Protocol Go 侧实现与单仓测试；配合跨仓问题定位 | 在 Integration 复制 Go 业务实现 |
| Harness/UE 组 | Harness、Hermes vendor、Python 侧协议实现与单仓测试；vendor 升级和回退 | 在 Integration 维护第二份 Harness/vendor 源码 |
| 构建组 | Integration 工具、组合验收、bundle/manifest、Ubuntu CI 和镜像构建 | 直接修改 Go/Harness 权威源码；需要改动时回到对应仓库 |
| 部署组 | 消费已验证 image/bundle/manifest，维护首次部署配置、运行调试和必要的版本切换说明 | 自行拼装三仓源码或绕过构建 manifest |

每项任务由一个团队主责，其他团队按协议、源码或部署边界协作；代码合并始终回到其权威仓库。

## 依赖总图

```text
I-01 -> I-02 -> I-03 -> I-04 -> I-05 ──┐
                  I-02 -> I-06 -> I-07 ─┴-> I-08
I-01 + I-05 + I-06 + I-08 -> I-09
I-08 -> I-10（引入新 vendor 版本时还需 I-09）
```

依赖关系以各任务的“依赖”字段为准：I-02 完成后，I-03/I-04/I-05 与 I-06/I-07 两条主线可以并行推进；I-08 等 I-05 与 I-07 汇合后启动；I-09 需要已有的组合矩阵、bundle provenance 和 Ubuntu CI；I-10 可基于 I-08 已验证的版本开始首次部署，引入新 vendor 版本时再以 I-09 的兼容性结果为前提。I-08 必须依赖 I-07，不能只把本地 Mac Docker 结果当成正式目标平台证据。

## 阶段与任务

### I-01 [P0] 冻结三仓库组合契约与验收基线

**依赖**：无。

**主责**：构建组；后台组与 Harness/UE 组评审协议和启动边界。

**状态**：已完成（2026-09-23）。

**内容**：

- 定义三个仓库的职责、源码定位模式、本地模式与 CI/checkout 模式。
- 定义 `workspace.local.yaml`、`sources.lock.yaml` 和 bundle manifest 的 schema。
- 冻结 Host Protocol、terminal schema、epoch semantics、Harness/Go 启动参数和端口/UDS 约定。
- 明确 Mac 只做开发/快速验证，Ubuntu 22.04 Linux/amd64 才是正式镜像基线。
- 将“源码包无 Git 也能构建”“customized build 可构建但必须标记来源”写入契约。

**产物**：

- `schemas/workspace-local.schema.json`
- `schemas/sources-lock.schema.json`
- `schemas/bundle-manifest.schema.json`、`schemas/host-protocol-v1-terminal.schema.json`
- `docs/contracts/source-combination.md`
- 契约版本与兼容性规则。

**验收**：schema 可校验示例；无任何字段要求客户必须保留我们的 Git 仓库历史；关键协议字段与 Harness/NetworkClaw 文档一致。

**完成证据**：`schemas/` 下四个 Draft 2020-12 schema 均通过 `make validate-contracts`；`docs/contracts/source-combination.md` 固化 JSONL Host Protocol 1.0、terminal payload、epoch fencing、chatsvc-owned Harness、Unix socket、Mac/Ubuntu 平台边界及源码包/customized provenance 规则。schema 中源码 lock 的 commit 是 checkout 模式定位信息；bundle manifest 允许 Git commit、dirty/diff 和 vendor hash 为空，tree hash 仍为必需。

### I-02 [P0] 实现源码工作区解析与环境诊断

**依赖**：I-01。

**主责**：构建组。

**状态**：已完成（2026-09-23）。

**内容**：

- 支持 sibling 目录、显式相对路径、绝对路径和 CI 临时 checkout。
- 禁止依赖 cwd、软链接或开发机绝对路径作为唯一机制。
- `doctor` 检查两个源码仓库、Git/Go/CPython 3.12、Harness 环境、Docker/Podman、端口和必要配置。
- 诊断输出不得泄露 provider key、`.env` 内容或客户路径以外的敏感信息。
- 对源码仓库报告 commit、dirty、tree hash，但不要求本地调试必须 clean。

**产物**：

- `tools/resolve-sources.*`
- `tools/doctor.*`
- `workspace.local.example.yaml`
- `sources.lock.example.yaml`

**验收**：在当前 Mac sibling 工作区、临时相对目录、绝对路径和缺失仓库场景分别得到明确结果；错误退出码稳定。

**完成证据**：`tools/resolve_sources.py` 通过集成根目录锚定路径解析（不依赖调用 cwd），支持 YAML 相对/绝对路径与 env 覆盖；源码包无 `.git` 时仍计算 SHA-256 tree hash。`make doctor` 在当前 Mac sibling 结构通过，报告 Go、CPython 3.12、Harness imports、Git、Docker 与两个源码树 commit/dirty/tree hash；`tests/test_workspace_tools.py` 覆盖相对路径、绝对路径、无 Git 源码包、缺失仓库非零退出和 UDS readiness frame。

### I-03 [P0] 实现本地 Go ↔ Harness 启动与调试编排

**依赖**：I-02。

**主责**：构建组；后台组和 Harness/UE 组提供受支持的启动入口与调试信息。

**状态**：已完成（2026-09-23）。

**内容**：

- `dev-up`、`dev-down`、`restart-go`、`restart-harness`、`logs`、`collect-diagnostics`。
- 使用两个真实源码工作树，不复制源码，不修改用户未提交文件。
- 管理临时 workspace、Unix socket/JSONL transport、provider 配置、健康检查和子进程退出。
- 支持 IDE attach：保留可读日志、PID、启动命令摘要和协议帧 artifact。
- 进程退出时清理临时资源，但不得删除用户源码或持久 session workspace。

**产物**：

- `tools/dev-up.*`、`tools/dev-down.*`
- `tools/process/`
- `docs/local-development.md` 更新
- 本地 compose 或等价启动配置。

**验收**：Mac 上从三个独立仓库启动真实 Go + Harness；能单独重启一侧；健康检查失败时不遗留孤儿进程；provider 配置入口可指向本地服务。provider stub 和故障行为本身由 I-04 验收。

**完成证据**：`tools/dev.py` 实际构建并启动 NetworkClaw `cmd/chatsvc`，由 chatsvc 通过 `tools/harness-launcher.sh` 启动真实 Harness；UDS HealthCheck 是 readiness gate。支持 up/down/restart-go/restart-harness/logs/collect-diagnostics；Harness 由 chatsvc 管理，故 Harness restart 明确重启 owning chatsvc，不伪装为独立 daemon。记录 chatsvc 和真实 Harness 子进程 PID/命令；PID 文件校验执行命令路径后才发信号；超时/启动失败会 TERM→KILL 收尾并移除 Integration socket。`.integration-state/` 保留 logs、PID、socket、binary、诊断与脱敏 frame metadata；metadata 不含 payload，ID 进程内 HMAC 摘要化，state/log/PID/frame 权限分别为 `0700`/`0600`。Go client 的可选 frame recorder 通过 `NETWORKCLAW_HARNESS_FRAME_LOG` 开启，默认关闭。provider env 默认从 NetworkClaw `.env` 读取，也支持路径覆盖；已导出的 shell value 优先，诊断不记录值。provider stub、transport fault 和 fault matrix 不属于 I-03 的完成边界，由 I-04 单独验收。

实跑证据（Mac）：`make dev-up` 对真实 chatsvc UDS HealthCheck 返回 ready；`make restart-go` 与 `make restart-harness` 均重新 ready；`make dev-down` 后 PID/socket 不存在且 `pgrep -f '[n]etworkclaw_harness.host'` 无残留。以 `NETWORKCLAW_PYTHON=/definitely/missing/python make dev-up` 注入启动失败，命令非零退出且 chatsvc/Harness/PID/socket 均无残留。`harness-frames.jsonl` 实际记录 protocol negotiation 与 metrics 帧摘要；对 artifact 搜索 payload/API key 字段未发现内容。

### I-04 [P0] 建立 provider stub、transport fault 和故障注入夹具

**依赖**：I-03。

**主责**：构建组；后台组和 Harness/UE 组协作提供可注入边界及稳定 reason code。

**内容**：

- localhost-only provider stub，覆盖正常响应、慢响应、半流式断连、HTTP 错误和无效响应。
- transport drop/reset、Harness SIGKILL、Go client disconnect、旧 epoch late frame 注入。
- 可控时序工具：等待 ready、事件账本、bounded timeout、进程清理。
- parent/child、control early registration、completed-turn control 等组合场景的夹具入口。
- 所有故障结果必须使用稳定 reason code，禁止依赖日志文本断言。

**产物**：

- `tests/fixtures/provider_stub/`
- `tools/fault-proxy.py`
- `tests/support/fault_injection.py`, `tests/support/event_ledger.py`, `tests/support/process.py`
- 故障场景清单和清理策略。

**验收**：夹具离线可运行；无外部模型密钥；测试结束无子进程、socket、临时 workspace 泄漏。

**状态**：已完成（2026-09-23）。

**完成证据**：`tests/fixtures/provider_stub/server.py` 提供 loopback-only 的 OpenAI-compatible provider stub，覆盖正常/慢响应、半流式断连、TCP reset、HTTP 错误和 malformed response；`tools/fault-proxy.py` 支持 JSONL relay 的 drop/reset/sigkill/disconnect/stale-terminal 注入；`tests/support/` 提供脱敏 event ledger、bounded readiness/cleanup 和 fault plan。`make fault-fixtures` 通过 14 项离线夹具测试，`make test` 通过 19 项 Python 测试，`make integration-test` 通过真实 NetworkClaw Go ↔ Harness interop（含 provider interruption、transport interruption、reason code、control race、parent/child scope）。

**边界**：I-04 证明的是可复用的故障夹具和清理语义；完整跨仓行为矩阵、机器可读组合报告属于 I-05，Ubuntu 22.04 full matrix 属于 I-08。

### I-05 [P0] 完成真实跨仓组合验收矩阵

**依赖**：I-04；协议变更还依赖 I-01。

**主责**：构建组；后台组和 Harness/UE 组共同确认各自协议语义与终态。

**内容**：

- 单 Session vertical flow：negotiate → open/resume → input → event → terminal → close。
- 多 Session multiplexing、同 Session admission、active stream cancel/steer。
- lease renew/revoke/takeover、旧 owner late event/control/terminal rejection。
- provider interruption、transport interruption、两者组合终态。
- request replay/hash conflict、EOF fan-out、backpressure。
- SIGKILL/replacement、同 workspace/SessionDB 恢复、unknown side effect no replay。
- parent/child 独立 session/workspace/DB、interrupt scope 和 exactly-once release。

**产物**：

- `tests/integration/`
- `docs/evidence/combination-matrix.md`
- 可机器读取的测试报告和 reason-code ledger。

**验收**：Mac 可执行 smoke 与完整组合矩阵；每个场景断言客户端终态和 stale frame 处理，不能以单仓库测试替代。Ubuntu 22.04 上运行同一 full matrix 是 I-08 的验收项，不作为 I-05 的先决条件。

**状态**：已完成（2026-09-23）。

**完成证据**：`NetworkClaw/tests/integration/harnessinterop/` 新增单 Session vertical flow、同 Session admission/active steer/cancel、request replay/hash conflict 和 takeover/stale control 的真实 Go client ↔ Python Harness 测试；现有 provider interruption、双 Session multiplex、parent/child scope 测试继续纳入。`tools/run-combination-matrix.py` 统一运行跨仓测试、Go SIGKILL/replacement 和 EOF/backpressure 支撑测试、Harness recovery/delegation 测试，生成 `.integration-state/evidence/combination-matrix.json` 与 Markdown 报告，并记录 post-matrix cleanup evidence。2026-09-26 Mac 实跑当前矩阵全部通过，cleanup status 为 `clean`。报告 reason code 是各测试断言的预期值，脚本验证指定测试执行通过，不自动解析运行时事件；旧 epoch revoke 的 Go 本地 binding 检查属于单元支撑证据，不列为 wire protocol 跨仓场景。固定场景、命令和平台边界见 `docs/evidence/combination-matrix.md`。

**边界**：EOF/backpressure、unknown side effect 和 exactly-once child release 的直接证据仍来自 Go client/Harness 支撑测试；它们由同一个组合门禁运行并列入报告，但不被描述为单一 Go↔Python 场景。Ubuntu 22.04 full matrix、镜像和 bundle 脱离工作区验收属于 I-07/I-08。

### I-06 [P0] 实现 bundle、源码树身份和 build manifest

**依赖**：I-01、I-02。

**主责**：构建组；后台组和 Harness/UE 组确认各自源码身份及构建输入。

**内容**：

- 从当前三个工作树或 CI checkout 生成 `networkclaw-bundle`，排除 `.git`、缓存、密钥和本机绝对路径。
- 记录 NetworkClaw、Harness、Integration 的 tree hash；Git commit 可用时记录，缺 Git 时仍可构建。
- 记录 Harness vendor tree hash、Hermes upstream ref/patch metadata、Host Protocol、target、dirty/customized、diff hash。
- 区分 local/custom bundle 与正式客户发布 bundle，不把 dirty 版本误标为官方来源。
- 支持 deterministic archive、checksums 和可选签名接口。

**产物**：

- `tools/build-bundle.*`
- `tools/verify-bundle.*`
- `schemas/bundle-manifest.schema.json`
- `docs/bundle.md` 更新

**状态**：已完成（2026-09-23）。

**完成证据**：`tools/build-bundle.py` 与 `tools/verify-bundle.py` 从当前三仓源码生成/校验 `networkclaw-bundle.tar.gz`、SHA-256 sidecar 和可选 OpenSSL detached signature；`schemas/bundle-manifest.schema.json` 定义来源与 artifact provenance。manifest 记录三个源码树 hash、可用的 commit/dirty/diff/customized 状态、Harness vendor tree hash、Hermes upstream ref/repository/patch hash、Host Protocol 1.0、Ubuntu 22.04 Linux/amd64 target 和 bundle payload hash。release 模式要求三仓 Git clean 且 commit/tree hash 与 `sources.lock.yaml` 一致；local 模式支持 dirty 与无 Git 源码快照并标记 customized。builder 与 `resolve-sources` 共用 tree/diff 身份算法；`.codebase-memory` 等本机生成缓存排除在 bundle 外。

2026-09-23 Mac 验证：`make test` 通过 38 项测试（含 19 项 bundle 专项测试）；真实三仓 `make bundle`、`make verify-bundle`、schema 校验、Python compile 均通过。真实 NetworkClaw/Harness manifest commit/tree/dirty/diff 与 `tools/resolve_sources.py --json` 一致；Harness vendor tree 与 Hermes patch provenance 均有 hash。两次独立真实 bundle 构建的归档 SHA-256 一致。verifier 对归档内容、payload hashes 和敏感信息扫描通过；私钥签名/公钥验证、归档篡改拒绝和 sidecar 更新后 payload 篡改拒绝由专项测试覆盖。

**边界**：当前真实 bundle 是本机 dirty/customized 交付快照，不是正式 release；签名验证接口通过临时测试密钥验证，未签发客户发布签名。脱离原工作区继续开发/构建属于 I-07，Ubuntu 22.04 正式构建属于 I-08。

### I-07 [P0] 验证 bundle 脱离原始工作区可继续开发和构建

**依赖**：I-06。

**主责**：构建组；后台组与 Harness/UE 组协助确认各自源码快照可离线使用。

**内容**：

- 将 bundle 解压到临时目录，删除原始仓库引用、`.git` 和本机 virtualenv 依赖。
- 从 bundle 内的 tools/CI/docs 重新执行 doctor、测试、组合验收和构建准备。
- 检查脚本没有硬编码 `/Users/...`、源仓库 URL、未声明环境变量或外部 fixture。
- 明确哪些依赖必须从 Ubuntu CI wheelhouse/base image 提供。

**产物**：

- `tests/bundle/`
- `docs/customer-handoff.md`
- bundle self-test report。

**验收**：bundle 在干净临时目录完成源码级 smoke、组合测试准备和 manifest 校验；失败必须说明缺失输入。

**状态**：已完成（2026-09-23）。

**完成证据**：`tests/bundle/self_test.py` 将输入归档及 checksum sidecar 复制到系统临时目录后执行 archive safety、独立 Harness/Integration venv 和锁定依赖安装、doctor、Harness 全量测试、Integration 测试、Go ↔ Python 组合矩阵、原 bundle manifest/checksum 校验、从解包源码重建 bundle 及重建 bundle 校验。2026-09-23 Mac 实跑报告 `.integration-state/evidence/bundle-self-test.json` 状态为 `passed`，13 个 step 记录全部退出码 0，`failures=[]`、`missing_inputs=[]`；正常报告不保留临时工作区路径。自测清理 `NETWORKCLAW_*`/`HARNESS_PATH` 本机设置，并验证 bundle 不含 `.git`、virtualenv、危险 symlink 或任意绝对源码目录路径。CPython 3.12、Go toolchain、Harness lock 文件 wheels 和 Integration Python 依赖是自测输入；Ubuntu 22.04 wheelhouse/base image、Linux/amd64 正式构建仍属于 I-08。

### I-08 [P0] 建立 Ubuntu 22.04 CI 和 Linux/amd64 正式构建

**依赖**：I-05、I-07。

**主责**：构建组；后台组与 Harness/UE 组维护其单仓 CI/构建要求并协助失败归属。

**状态**：已完成（2026-09-24）。

**内容**：

- CI checkout 三仓库或接收 bundle，并验证 lock/tree hash。
- 运行 Go 全量测试与 `-race` 重点门禁、Harness 官方测试/vendor/runtime verifier、组合矩阵。
- 构建 Go linux/amd64 binaries、Harness runtime/image 和 OCI artifact。
- 使用 offline wheelhouse、`govulncheck`、SBOM/license/security scan；不因 Mac arm64 smoke 通过而跳过目标平台。
- 生成客户可读构建报告和 machine-readable manifest。

**产物**：

- `ci/ubuntu-22.04/`
- `ci/pipelines/`
- `docs/ci.md`
- Linux/amd64 artifact 与 digest。

**验收**：网络受限/禁网复验可执行；Go、Harness、interop、bundle verifier 全绿；失败时按仓库和阶段分层报告。

**完成证据**：`ci/ubuntu-22.04/ci-test.sh` 按阶段生成 machine-readable report 和独立日志；2026-09-24 的 clean-source 目标门禁通过 integration/Harness bootstrap、wheelhouse sync、Go `-race`、source lock、Harness 240 项、Integration 38 项、组合矩阵、bundle verifier 和隔离 self-test，报告为 `.integration-state/evidence/ubuntu-22.04-ci.json`。`make image` 以 Linux/amd64 目标生成 OCI 与 Docker archive 及 build manifest；入口为 `/opt/bin/chatrtmgr`，运行用户为 `65532:65532`。Syft SBOM、license 摘要和 Trivy 扫描已生成；Trivy 结果为 vulnerabilities=0、misconfigurations=0、secrets=0。当前 NetworkClaw HEAD 的 `govulncheck ./...` 结果为 0 vulnerabilities。正式 GitHub Actions workflow 固定 Ubuntu 22.04、Syft 1.52.0、Trivy 0.74.0 和 govulncheck 1.1.4；本机验证使用 Mac 上的 Linux/amd64 BuildKit，不把 Mac arm64 运行结果冒充 Ubuntu runner。

**发布说明**：I-08 的脚本、锁定输入、目标平台构建和安全门禁已完成；客户启用 GitHub Actions 后，首次 workflow 运行会产生同一组可归档的 Ubuntu runner 证据。生产发布仍应保留该次 runner 运行记录和扫描产物。

### I-09 [P1] 固化 Hermes vendor 升级与兼容性回归流程

**依赖**：I-01、I-05、I-06、I-08。

**主责**：Harness/UE 组负责 vendor 权威变更；构建组负责组合回归、manifest 和门禁集成。

**状态**：已完成（2026-09-24）。

**内容**：

- vendor 更新只在 `networkclaw-harness` 执行：同步、patch、allowlist、hash、runtime closure、Harness tests。
- integration 提供 `vendor-status`、`vendor-compat-test` 和组合回归入口。
- 记录上游 ref、patch series、vendor tree hash、协议变化和升级风险。
- vendor 变更后先验证 Harness 单仓测试，再运行跨仓组合矩阵和 bundle/image provenance 检查；验证失败时报告具体阶段并阻止该变更进入正式交付。
- 保留上一份已验证的 Harness source lock 供版本对照；I-09 只证明新 vendor 输入是否可交付，不负责部署切换、灰度编排或自动回滚。

**产物**：

- `tools/vendor-status.*`
- `tools/vendor-compat-test.*`
- `docs/vendor-upgrade.md`
- vendor upgrade report。

**验收**：至少用一次 vendor 版本变化或等价 fixture 演示升级前后 provenance、Harness 测试和组合验收；注入一次不兼容结果，确认 vendor verifier 在测试和 bundle 之前阻断正式交付输入；恢复原基线后 Harness 测试与组合矩阵再次通过。验证通过后 source lock 可通过显式 `--update-lock` 切换到新基线，且只接受 clean 源码；保留旧 lock 作为人工恢复依据。

**完成证据**：`tools/vendor_status.py` 汇总 Hermes upstream commit、patch series、vendor manifest/tree hash、三仓 commit/tree/dirty 和 source-lock 匹配状态；`tools/vendor_compat_test.py` 串联 Harness vendor verifier、Harness 全量测试、Go↔Harness 组合矩阵和 source-lock gate，默认不修改 lock，`--update-lock` 只在 clean 且全门禁通过后更新并复验。`tools/build-bundle.py --release` 现在强制调用 Harness vendor verifier，失败时不生成 release bundle；`tests/test_bundle.py` 新增 release 阻断测试。2026-09-24 vendor fixture 报告 `.integration-state/evidence/vendor-compat-fixture.json` 证明：模拟 vendor 更新 verifier/Harness/组合矩阵全部通过；注入不兼容文件被阻断；正式交付未生成；恢复原基线后 Harness 和组合矩阵再次通过。

### I-10 [P1] 固化首次部署、运行调试和客户交接

**依赖**：I-08。部署含有新的 Hermes vendor 版本时，同时要求 I-09 的兼容性验收和 provenance；不阻塞基于当前已验证版本的首次非生产部署。

**主责**：部署组；构建组提供可验证 image/bundle/manifest 和部署所需配置。

**状态**：已完成（2026-09-24；客户确认本地 kind 可作为 I-10 的部署验收环境）。

**内容**：

- Kubernetes 是客户主要部署环境，优先提供可配置的 Helm chart 和首次安装说明；同时提供 Docker 命令与 Docker Compose，支持本地或单机验证。systemd 不纳入当前任务范围；本地联合调试继续使用 I-03 的工具直接启动服务。
- 使用 I-08 已验证的 OCI artifact 和 build manifest；推送到客户 registry 后记录可拉取的 image digest，说明其与 bundle、三仓 commit/tree hash 的对应关系，不在部署脚本中重拼源码。
- 验证首次部署路径：最小配置、镜像拉取、必需环境变量/Secret、数据库初始化/迁移和外部依赖连通、持久化配置、Kubernetes Service/Ingress（如适用）、readiness/liveness probe，以及覆盖 Go ↔ Harness 的部署后 smoke test。
- 提供面向开发与运维的调试信息：查看 Go/Harness 日志、检查 Pod/容器状态与 probe、收集脱敏诊断、定位启动/配置/依赖错误；本地调试入口链接到 `docs/local-development.md`。
- Kubernetes 原生发布与切换能力按平台默认方式使用，不额外建设 staged rollout 编排；仅记录如何切换到已验证的 image/digest，非生产阶段不以灰度或自动回滚为验收重点。
- 客户交接文档说明三仓日常修改归属、联合调试、CI/build manifest、首次部署、常见故障定位和问题收集方式。
- I-10 的主验收是首次安装成功、服务 ready、端到端 smoke 通过和问题可诊断；版本切换/恢复只保留为简要人工操作说明。

**产物**：

- `deploy/helm/`（首要交付）
- `deploy/docker/`、`deploy/compose/`
- `docs/deployment.md`
- `docs/customer-handoff.md`
- 首次部署与调试 runbook，附已验证 image/digest 的简要人工切换说明。

**验收**：部署人员可依据 integration 交付的镜像、manifest、Helm chart 和文档，在本地隔离 kind namespace 完成依赖准备、数据库初始化/迁移及首次安装，并通过 readiness/liveness 与 Go ↔ Harness 启动链 smoke test；能够查看 Go/Harness 日志、收集脱敏诊断并按 runbook 定位常见启动故障。Docker/Compose 路径可完成本地或单机 smoke。无需自行拼装源码或理解 Harness 内部 Agent loop；不要求构建独立灰度、自动回滚或 systemd 部署系统。客户 registry 和非生产集群部署按交接文档在客户环境重验，不作为本轮完成门禁。

**完成证据**：`deploy/helm/networkclaw-bundle/`、`deploy/compose/`、`deploy/docker/README.md`、`docs/deployment.md`、`docs/customer-handoff.md`、`tools/deployment_smoke.py`、`tools/collect_k8s_diagnostics.py` 和 `tools/kind-up.py` 已形成首装、手动 kind 验收与排障入口。2026-09-24 使用 I-08 本地 Linux/amd64 combined image 在 Mac Docker Compose 完成 PostgreSQL 迁移（16 张业务表）、所有服务健康检查及登录/创建 Session/manager-service binding/关闭 Session smoke；同一镜像加载到现有 kind 集群的独立 `networkclaw-i10-verify` namespace 后，Helm 安装成功、两个 Pod Ready、迁移与相同 smoke 通过，诊断工具产出仅含状态字段的 `0600` 文件。新增 `make kind-up` 在 `networkclaw-manual` 独立 namespace 启动临时 PostgreSQL/Redis/etcd，先以 kind Job 执行并记录 20 个 migration 文件的 SHA-256，再以 etcd 服务发现安装 **2 个 lobby 和 2 个 chatrtmgr**；两个 manager 分布在两个 kind worker，etcd `/services` 下有两个注册 key，重复执行会跳过内容未变的 migration，手动端口转发后的 healthz/readyz/metrics、Session 创建/绑定/关闭 smoke 通过；`make kind-down` 仅允许删除受保护名单之外的 DNS 合法 namespace。kind provider 配置现可从本地未提交 env 文件读取并经 Secret 注入；模型同步 Job 使前端目录显示 5 个 GPT，旧 Qwen 种子标记为未部署；验证 Secret 配置键非空、模型列表接口返回 5 个已部署 GPT，未执行真实 GPT 对话验收。OCI 归档 SHA-256 与 build manifest 一致，本地 image ID 对应 OCI 配置 blob，镜像标签对应三仓 commit 与 bundle SHA-256。`make test` 通过 53 项；包含部署输入的 customized bundle 已构建并由 verifier 校验，`compose.env.example` 确认在包内。隔离 bundle self-test 最终 `status=passed`、13 个步骤全部成功（含 Harness 测试、Integration 测试、组合矩阵和解包重建），报告在 `.integration-state/evidence/i10-bundle-self-test.json`。测试 namespace 和 Compose 项目及其专用数据库卷已清理；手动验收 namespace 按用户要求保留。

**交付边界**：kind 节点为 arm64、本地镜像用 `image.pullPolicy=Never`；客户 registry digest 核对、私有镜像拉取和客户 Kubernetes 非生产环境的实际首装须在客户环境按同一文档重验，不以本地结果冒充。当前三仓均存在开发期源码树与 `sources.lock.yaml` 不一致，`verify-sources-lock` 非零退出；本轮 bundle 明确标为 customized，不得冒充正式 release provenance。这些是客户正式发布前的后续门禁，不影响用户确认的本地 I-10 范围。

## 任务优先级

### P0：客户能联动、能验证、能交付

```text
I-01 -> I-02 -> I-03 -> I-04 -> I-05 ──┐
                  I-02 -> I-06 -> I-07 ─┴-> I-08
```

P0 未完成前，不应把旧计划中的“组合发布已完成”作为最终结论。

### P1：客户能长期演进和部署

```text
I-01 + I-05 + I-06 + I-08 -> I-09
I-08 -> I-10（引入新 vendor 版本时还需 I-09）
```

P1 是客户接管后持续开发、升级 Hermes 和完成首次部署的交付链路。

## 统一验收门禁

每个阶段必须提交：

1. 变更文件/接口清单；
2. 实际命令和结果；
3. 失败场景和清理证据；
4. 对 Go、Harness、Integration 三仓库的影响；
5. 未完成项、回滚方式和下一阶段依赖。

最终门禁：

```text
make doctor
make test
make integration-test
make bundle
make verify-bundle
Ubuntu 22.04 CI: make ci-test && make image
```

所有命令必须有明确成功/失败退出码；未实现入口不得返回成功。

## M1 进度记录

| 任务 | 状态 | 主要产物与验证 | 遗留/依赖 |
|---|---|---|---|
| I-01 | 已完成 | 三份 JSON Schema、契约文档；schema example validation | 实际 CI lock 与 release manifest 由 I-06/I-08 产出 |
| I-02 | 已完成 | 统一源码解析、doctor、当前 Mac sibling 验收和临时无 Git 源码包单测 | 客户 CI checkout 在 I-08 验收 |
| I-03 | 已完成 | 真实 chatsvc/Harness 启停、restart、健康检查、失败清理、日志/PID/frame artifact | I-04/I-05 已补充故障夹具和组合验收；I-08 仍需目标 Ubuntu 验证 |
| I-04 | 已完成 | provider stub、JSONL fault proxy（drop/reset/sigkill/disconnect/stale epoch）、有界 SIGKILL/EOF 清理、脱敏 event ledger；19 项离线夹具测试和真实组合入口通过 | Ubuntu 22.04 full matrix 属于 I-08 |

M1 验证命令：`make bootstrap`、`make test`（包含四个 Draft 2020-12 schema example 校验）、`make doctor`、Python compile/shell syntax check、真实 `make dev-up` / 两种 restart / `make dev-down` / bad-interpreter failure cleanup、`go test -race ./internal/chatsvc/harness ./internal/chatsvc/config`（Go 命令在 NetworkClaw 仓库执行）。M1 已完成；I-04/I-05 的 Mac 夹具与组合验收、I-06 的本地 bundle 交付线、I-07 的脱离工作区验收和 I-08 的 Ubuntu 22.04 CI/目标平台构建门禁均已完成。

## M2 进度记录

M2 的目标是让三仓库组合具备可重复的故障验证能力和本地首装验收。I-04 至 I-10 已完成；客户环境部署按 I-10 交接文档重验。

| 任务 | 状态 | 主要产物与验证 | 遗留/依赖 |
|---|---|---|---|
| I-04 | 已完成 | provider stub、transport fault proxy、fault plan、event ledger、进程清理 helper、离线夹具和真实 interop 入口；19 项夹具测试通过 | Ubuntu 22.04 full matrix 属于 I-08 |
| I-05 | 已完成 | 跨仓场景矩阵、Go recovery/EOF/backpressure 与 Harness recovery/delegation 支撑验证；2026-09-23 Mac `make integration-test` 全部通过并产出机器报告 | Ubuntu 22.04 full matrix 属于 I-08；reason code 为测试断言预期值，并非从运行时 ledger 自动提取 |
| I-06 | 已完成 | 三仓 deterministic bundle、verifier、provenance manifest；真实 Mac 构建两次 SHA-256 一致，`make test` 38 项通过 | 当前 bundle 是 dirty/customized；脱离工作区验证由 I-07 完成，正式 Ubuntu 构建由 I-08 完成 |
| I-07 | 已完成 | 临时目录解包、独立 venv/锁依赖、doctor、Harness 全量测试、Integration 38 项测试、组合矩阵、原包验证、源码重建和重建包验证全部通过；报告 `.integration-state/evidence/bundle-self-test.json` | 当前证据为 Mac/CPython 3.12；Ubuntu 22.04 wheelhouse、Linux/amd64 镜像和正式 CI 属于 I-08 |
| I-08 | 已完成 | Ubuntu 22.04 目标门禁通过：bootstrap、offline wheelhouse、Go `-race`、Harness 240 项、Integration 38 项、组合矩阵、bundle verifier、bundle self-test、Linux/amd64 OCI/Docker archive、非 root 入口、三仓/bundle provenance、license 摘要、Syft SBOM；Trivy vulnerabilities/misconfigurations/secrets 均为 0，当前 Go HEAD `govulncheck` 为 0 vulnerabilities | 客户首次启用 workflow 时归档 Ubuntu runner 运行记录；I-09 负责 vendor 升级回归 |
| I-09 | 已完成 | `vendor-status` 汇总 Hermes/vendor 与三仓身份；`vendor-compat-test` 串联 vendor verifier、Harness 全量测试、组合矩阵和 source-lock gate；release bundle 强制 vendor verifier；升级/不兼容/恢复 fixture 全部有报告 | 客户实际 Hermes 上游版本变化仍需按同一流程执行；I-10 消费已验证 provenance 和镜像 |
| I-10 | 已完成 | Helm/Compose/Docker 部署输入、首装/排障/交接文档；Mac Compose 与隔离 kind 的迁移、Ready、Session smoke 通过；kind 工具支持 etcd + 2 lobby + 2 chatrtmgr 分布式验收；Integration `make test` 50 项通过；customized bundle 含部署模板并校验通过 | 客户 registry digest/拉取和客户 Kubernetes 首装按交接文档重验；当前 dirty 源码与 source lock 不匹配，非 release 输入 |

## 模型 Snapshot 增量（2026-10-03）

实现与本地验收已完成，发布门禁仍开放；不改变上文历史 I-01 至 I-10 计数。契约见 [model-config-snapshot-v1](../contracts/model-config-snapshot-v1.md)，证据见 [本地验收记录](../evidence/model-snapshot-acceptance.md)。

- NetworkClaw：migration 030、模型/连接管理和版本、私有 Snapshot、模型选择与最低版本传递、30 秒 broker、不可变 run pin/process fencing、管理员与主页面 UI 已实现。
- Harness：显式执行配置、身份变化重建 Agent、保持 Session/历史/权限、逐 turn 参数恢复；全量 304 项通过。
- Integration：部署 Secret/URL 接线、双 Lobby/双 manager/provider stub 矩阵与真实 GPT，27 项通过；最新 `make test` 129 项通过；开发 bundle 已构建和校验。
- 无逐 turn Lobby claim 请求。新鲜缓存可处理已授权请求；process/socket 丢失返回 pin lost，禁止用最新配置自动重执行旧 run。
- 真实浏览器 walkthrough 与 amd64 镜像构建已通过；遗留：共享双节点发现、Ubuntu 22.04 部署、完整解包 self-test（本次 Linux wheelhouse 不含 Mac 所需的兼容 wheel）。现有 Go 全树两个 catalog 测试因 migration 029 失败，不能报告全树通过或正式可发布。
- 下一交接：按现有入口补以上门禁；模型回滚仍推进 revision。三个仓库的其他未提交工作保留，无 Git 提交。
