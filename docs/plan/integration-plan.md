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

## 依赖总图

```text
I-01 组合契约与验收基线
  ├── I-02 源码工作区解析与 doctor
  │     └── I-03 本地启动/调试编排
  │           └── I-04 provider stub/故障夹具
  │                 └── I-05 真实跨仓组合验收矩阵
  ├── I-06 bundle/provenance/manifest
  │     └── I-07 脱离原仓库的 bundle 验证
  │           └── I-08 Ubuntu 22.04 CI 与 Linux/amd64 构建
  │                 └── I-10 部署输入与 rollout 验收
  └── I-09 vendor 升级工作流
        └── I-05、I-06、I-08 回归验证
```

I-02 与 I-06 可以并行；I-04 需要 I-03 的进程控制接口；I-08 必须依赖 I-07，不能只把本地 Mac Docker 结果当成正式目标平台证据。

## 阶段与任务

### I-01 [P0] 冻结三仓库组合契约与验收基线

**依赖**：无。

**内容**：

- 定义三个仓库的职责、源码定位模式、本地模式与 CI/checkout 模式。
- 定义 `workspace.local.yaml`、`sources.lock.yaml` 和 bundle manifest 的 schema。
- 冻结 Host Protocol、terminal schema、epoch semantics、Harness/Go 启动参数和端口/UDS 约定。
- 明确 Mac 只做开发/快速验证，Ubuntu 22.04 Linux/amd64 才是正式镜像基线。
- 将“源码包无 Git 也能构建”“customized build 可构建但必须标记来源”写入契约。

**产物**：

- `schemas/workspace-local.schema.json`
- `schemas/sources-lock.schema.json`
- `schemas/bundle-manifest.schema.json`
- `docs/contracts/source-combination.md`
- 契约版本与兼容性规则。

**验收**：schema 可校验示例；无任何字段要求客户必须保留我们的 Git 仓库历史；关键协议字段与 Harness/NetworkClaw 文档一致。

### I-02 [P0] 实现源码工作区解析与环境诊断

**依赖**：I-01。

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

### I-03 [P0] 实现本地 Go ↔ Harness 启动与调试编排

**依赖**：I-02。

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

**验收**：Mac 上从三个独立仓库启动真实 Go + Harness；能单独重启一侧；健康检查失败时不遗留孤儿进程；本地 provider stub 可接入。

### I-04 [P0] 建立 provider stub、transport fault 和故障注入夹具

**依赖**：I-03。

**内容**：

- localhost-only provider stub，覆盖正常响应、慢响应、半流式断连、HTTP 错误和无效响应。
- transport drop/reset、Harness SIGKILL、Go client disconnect、旧 epoch late frame 注入。
- 可控时序工具：等待 ready、事件账本、bounded timeout、进程清理。
- parent/child、control early registration、completed-turn control 等组合场景的夹具入口。
- 所有故障结果必须使用稳定 reason code，禁止依赖日志文本断言。

**产物**：

- `tests/fixtures/provider_stub/`
- `tests/fixtures/fault_injection/`
- `tests/support/ledger.*`
- 故障场景清单和清理策略。

**验收**：夹具离线可运行；无外部模型密钥；测试结束无子进程、socket、临时 workspace 泄漏。

### I-05 [P0] 完成真实跨仓组合验收矩阵

**依赖**：I-04；协议变更还依赖 I-01。

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

**验收**：Mac smoke 与 Ubuntu CI full matrix 均可执行；每个场景断言客户端终态和 stale frame 处理；不能以单仓库测试替代。

### I-06 [P0] 实现 bundle、源码树身份和 build manifest

**依赖**：I-01、I-02。

**内容**：

- 从当前三个工作树或 CI checkout 生成 `networkclaw-bundle`，排除 `.git`、缓存、密钥和本机绝对路径。
- 记录 NetworkClaw、Harness、Integration 的 tree hash；Git commit 可用时记录，缺 Git 时仍可构建。
- 记录 Harness vendor tree hash、Hermes upstream ref/patch metadata、Host Protocol、target、dirty/customized、diff hash。
- 区分 local/custom bundle 与正式客户发布 bundle，不把 dirty 版本误标为官方来源。
- 支持 deterministic archive、checksums 和可选签名接口。

**产物**：

- `tools/build-bundle.*`
- `tools/verify-bundle.*`
- `manifest/bundle-manifest.schema.json`
- `docs/bundle.md` 更新

**验收**：有 Git 和无 Git 源码快照均可生成 manifest；dirty/customized 结果可构建且明确标记；敏感信息扫描通过。

### I-07 [P0] 验证 bundle 脱离原始工作区可继续开发和构建

**依赖**：I-06。

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

### I-08 [P0] 建立 Ubuntu 22.04 CI 和 Linux/amd64 正式构建

**依赖**：I-05、I-07。

**内容**：

- CI checkout 三仓库或接收 bundle，并验证 lock/tree hash。
- 运行 Go 全量测试与 `-race` 重点门禁、Harness 官方测试/vendor/runtime verifier、组合矩阵。
- 构建 Go linux/amd64 binaries、Harness runtime/image 和 OCI artifact。
- 使用 offline wheelhouse/SBOM/license/security scan；不因 Mac arm64 smoke 通过而跳过目标平台。
- 生成客户可读构建报告和 machine-readable manifest。

**产物**：

- `ci/ubuntu-22.04/`
- `ci/pipelines/`
- `docs/ci.md`
- Linux/amd64 artifact 与 digest。

**验收**：网络受限/禁网复验可执行；Go、Harness、interop、bundle verifier 全绿；失败时按仓库和阶段分层报告。

### I-09 [P1] 固化 Hermes vendor 升级与兼容性回归流程

**依赖**：I-01、I-05、I-06、I-08。

**内容**：

- vendor 更新只在 `networkclaw-harness` 执行：同步、patch、allowlist、hash、runtime closure、Harness tests。
- integration 提供 `vendor-status`、`vendor-compat-test` 和组合回归入口。
- 记录上游 ref、patch series、vendor tree hash、协议变化和升级风险。
- 失败时阻止 bundle/image 生成，除非显式生成标记为实验性的 custom artifact。
- 支持回滚到上一份已验证的 Harness source lock。

**产物**：

- `tools/vendor-status.*`
- `tools/vendor-compat-test.*`
- `docs/vendor-upgrade.md`
- vendor upgrade report。

**验收**：至少用一次 vendor 版本变化或等价 fixture 演示升级、失败、回滚和重跑全套组合验收。

### I-10 [P1] 固化部署消费、rollout、回滚和客户交接

**依赖**：I-08；生产部署前还需 I-09 的 vendor provenance。

**内容**：

- 部署组优先消费 OCI image/digest，必要时消费 bundle 做现场构建或审计。
- 提供 Docker/Compose/Helm/systemd 等客户实际需要的部署输入，不在部署脚本重拼源码。
- staged rollout：single session → multi-session → cancel/steer → delegation → reconnect/failover。
- 记录 image、bundle、manifest 的对应关系、回滚版本和 smoke/health/ready 验收。
- 客户交接文档说明三个仓库的日常修改归属、联调、CI、vendor 升级和问题收集方式。

**产物**：

- `deploy/`
- `docs/deployment.md`
- `docs/customer-handoff.md`
- rollout/runbook 与 rollback procedure。

**验收**：部署组可以只依赖 integration 产物完成部署；能按 manifest 回滚到上一版本；不需要理解 Harness 内部 Agent loop。

## 任务优先级

### P0：客户能联动、能验证、能交付

```text
I-01 -> I-02 -> I-03 -> I-04 -> I-05
I-01 -> I-06 -> I-07 -> I-08
```

P0 未完成前，不应把旧计划中的“组合发布已完成”作为最终结论。

### P1：客户能长期演进和部署

```text
I-08 -> I-09 -> I-10
```

P1 是客户接管后持续开发、升级 Hermes 和生产运维的必需链路。

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

