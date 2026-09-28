# Harness 事件统一设计与执行计划

## 前置条件

本计划在 [Harness Gateway 替代 chatsvc 执行方案](harness-gateway-replacement-plan.md) 的 G-08 完成后开始。Gateway 先以兼容 stream chunk 替代 chatsvc；事件统一不与进程拓扑迁移绑定发布。

G-08 已完成。Gateway 现在是实时执行入口，事件统一不再需要兼容 chatsvc 的生产消费者，可以直接从 Harness Gateway 的 Host Protocol 贯通到 chatrtmgr、lobby 和 web2。旧兼容 chunk 只保留为迁移期对照和历史回放输入。

## 重新评估结论（2026-09-27）

原计划把 Harness Host Protocol 的 36 个事件当作完整目标，这足以覆盖生命周期和工具终态，但不足以表达用户在一次对话中看到的真实过程。结合当前 `networkclaw-harness` 的 Hermes 适配代码和 vendor 源码，前端还需要看到：

- 委派请求、授权结果、子 Agent 启动、持续进度、文本增量、思考状态和完成/失败原因；
- 模型生成工具参数、工具开始、工具进度、工具完成，以及计划（`todo_list`）的更新；
- 澄清和审批的请求/解决，以及它们与 `interaction_id`、`run_id` 的关联；
- 产物创建和可访问引用，而不是从工具输出文本猜测文件；
- 长任务的 heartbeat、上下文压缩、provider retry 和 usage 摘要，让界面能区分运行中、重试中、等待用户和已结束。

因此，“36 事件统一”要升级为“基线 36 事件 + 过程事件扩展 + 明确排除清单”。扩展事件也必须保持稳定原名；不允许为了适配 Go oneof 或前端旧类型把它们再压成 `run_state`、`tool_start` 或 `chunk`。

### Hermes 源码对账结果

当前 vendor 中已确认的原生来源包括：

| Hermes 来源 | 观察到的事件/回调 | 计划处理 |
|---|---|---|
| `tools/delegate_tool_progress.py`、`delegate_tool_child_run.py` | `subagent.start`、`subagent.complete`、`subagent.text`、`subagent.thinking`、`subagent_progress` | 纳入用户面过程流；保留 parent/child lineage、task index、status、summary 和 failure reason |
| `HostDelegationBroker` | `delegation.requested`，以及 host grant/deny 的解决结果 | 纳入控制与用户过程流；子 Agent 创建前必须先看到 allocation 和 resolution |
| `agent/stream_delivery.py` | reasoning delta、tool argument generation callback | 作为权限受控的 `reasoning.delta`、`tool.generating`；默认不暴露原始思维链 |
| Hermes native turn / Host Adapter | assistant delta、tool lifecycle、todo/plan、turn terminal | 作为主用户面事实，原名和 envelope 直通 |
| `projection/events.py` | `context.started`、`context.continued`、`checkpoint.updated`、`provider.attempt`、`provider.retry`、`grace.summary`、`finalizer.fallback` | 纳入过程/诊断扩展，不能静默丢弃；按订阅面决定是否展示 |
| `moa_loop.py` | `moa.reference`、`moa.progress`、`moa.phase`、`moa.aggregating` | 作为 provider/MoA 过程扩展；无 MoA 时不产生 |
| Hermes usage/session state | token、cost、model/provider route 摘要 | 以 `usage.updated` 或同等冻结名称提供摘要，不传内部 prompt 或原始 reasoning |

Hermes 完整 TUI/桌面契约中的 `pet.*`、`voice.*`、桌面窗口和平台通知事件不是 NetworkClaw 会话协议目标；它们属于 Hermes 的交互壳，必须在 E-00 的排除清单中明确写出，避免把 UI 壳事件误当成分布式对局事实。

## 当前完成度

| 层次 | 当前状态 | 说明 |
|---|---|---|
| Gateway UDS/JSONL | 已完成 | G-08 已让 Gateway 成为默认实时入口；不再需要经过 chatsvc 承接事件 |
| 36 事件声明 | 已完成但未贯通 | `protocol/catalog.py` 已声明 36 个事件，不能等同于 36 个事件都能从真实 Hermes turn 到达前端 |
| Harness producer | E-02 已完成 | Gateway/Host Adapter 已直接 emit Hermes 原生 subagent/delegation/tool/interaction 过程事件，以及 context/provider/usage/reasoning/MoA 扩展；受限事件通过 capability gate 和 bounded summary/warning 处理 |
| Go/lobby relay | E-01/E-03 已完成 | 已具备 opaque canonical event carrier、未知事件保留、身份/大小校验、upstream cursor/replay、重复幂等、乱序排序、慢消费者背压和 epoch fencing；跨节点共享 durable ledger 留待后续组合验收 |
| web2 用户面 | E-04 已完成 | lobby 保留 canonical envelope；web2 已按 event_id、lineage、sequence 和 terminal latch 重建 delegation/subagent/tool/plan/artifact/interaction 过程树；旧 chunk 仅作迁移读取 |
| 事件统一计划 | E-00 至 E-07 已完成（2026-09-27） | canonical-only 实时链路、旧 projection 生产消费者清理、Go/web2/Harness interop、replay、fencing 和迁移文档均有证据；旧 chatsvc 仅保留隔离回退/历史读取兼容 |

这意味着本计划不是“把一张 36 项清单搬过去”就完成；完成标准必须包含一次真实的前端过程 fixture，并能从事件 ledger 重建截图式过程。

### 目标过程时序（前端验收基线）

以下不是新的协议示例，而是 E-00a/E-06 必须能够重建的用户可见过程。事件到达可以交错，前端通过 lineage 和 sequence 还原层级：

```text
turn.queued -> turn.started
  -> delegation.requested (allocation-1, task 1/2)
  -> delegation.requested (allocation-2, task 2/2)
  -> delegation.resolved (allocation-1, grant child-session-a)
  -> delegation.resolved (allocation-2, grant child-session-b)
  -> subagent.start (child-a)
  -> subagent.start (child-b)
  -> subagent.thinking / subagent.text / subagent_progress (child-a|child-b)
  -> tool.generating -> tool.started -> tool.progress -> tool.completed (child-a)
  -> plan.updated (parent or child session)
  -> artifact.created (child-a, artifact-1)
  -> subagent.complete (child-a, status=succeeded)
  -> subagent.complete (child-b, status=failed, failure_reason=...)
  -> provider.retry / heartbeat (parent turn)
  -> approval.requested OR clarification.requested
  -> approval.resolved OR clarification.resolved
  -> assistant.delta
  -> turn.completed | turn.failed | turn.cancelled
```

前端应能把它显示为“主任务 -> 两个子任务 -> 各自工具/计划/产物 -> 汇总结果”的过程树。`subagent.text` 可以被折叠为摘要，`heartbeat` 可以限频，`reasoning.delta` 可以默认不展示；这些展示选择不能删除原始事件或改变终态。

## 目标

以 Harness Host Protocol catalog 和已对账的 Hermes 原生来源为跨仓库事件词汇源，保留事件原名和完整 envelope：

```text
Harness event
  -> Gateway canonical event
      -> chatrtmgr relay
          -> lobby/client transport
```

中间层只负责传输、排序、背压、重连和权限边界，不把 `tool.started` 改成 `tool_start`，不把 `subagent.start` 压成一个不可追踪的 `run_state`，也不把多个 `turn.*` 压成同一个 `run_state`。前端可以把事件组合成过程卡片和树状视图，但事件本身仍是唯一事实源。

## 设计原则

- 事件 `type` 沿用 Harness catalog 名称；payload 保留原始字段。
- envelope 至少包含 `protocol_version`、`session_id`、`run_id`、`turn_id`、`request_id`、`sequence` 和事件类型。
- sequence 由权威生产端产生，中间层不得按连接重造。
- 未知事件默认保留并可观测，不静默改写为文本；控制面事件可以按订阅权限过滤，但不能在传输层丢失事实。
- replay、cursor、重复事件和背压语义必须显式定义。
- UI 可以把多个事件组合成卡片或状态，但不成为事件真相源。
- `capabilities.report`、事件注册表、生成的 Go/TypeScript 类型和组合测试必须有一致性校验。
- 事件必须区分“事实事件”和“展示摘要”：摘要可以折叠或限频，但不得替代事实事件；丢弃必须有权限、采样或背压原因。
- 不把原始思维链、secret、内部 prompt、完整工具输出和 provider 凭证作为用户事件；安全过滤发生在 producer/adapter 边界并留下可观测的摘要事件。

## 事件分类

| 类别 | 示例 | 默认处理 |
|---|---|---|
| 用户执行事实 | `turn.*`、`tool.*`、`subagent.*`、`artifact.created` | 保留原名并交给用户面订阅 |
| 交互控制 | `approval.*`、`clarification.*`、`turn.controlled` | 保留原名，支持请求关联和幂等解析 |
| 过程可见性 | `delegation.*`、`subagent.*`、`tool.generating`、`reasoning.delta`、`context.*`、`usage.updated` | 按权限和订阅面传输；前端用于过程树、进度和摘要 |
| 活性/诊断 | `heartbeat`、`warning`、`error`、`metrics.snapshot` | 传输保真，按权限进入 UI 或运维面 |
| 会话/租约控制 | `session.*`、`protocol.negotiated`、`health.status` | 保留原名，控制面消费，不默认展示 |
| 流终止 | `end`、`shutdown.completed` | 明确终止语义，不伪造成功终态 |

## 依赖图

```text
G-08
  -> E-00
      -> E-00a
          -> E-01
              -> E-02
                  -> E-03
                      -> E-04
                          -> E-05
                              -> E-06
                                  -> E-07
```

## 任务

### 事件统一当前状态

| 任务 | 状态 | 当前证据/缺口 |
|---|---|---|
| E-00 | 已完成（2026-09-27） | [event-catalog-v1.json](../../schemas/events/event-catalog-v1.json)、[event-envelope-v1.schema.json](../../schemas/events/event-envelope-v1.schema.json)、[event-catalog-v1.md](../contracts/event-catalog-v1.md)；36 baseline、20 process extensions、排除项、权限、终态和兼容规则已冻结 |
| E-00a | 已完成（2026-09-27） | [hermes-event-inventory.json](../evidence/hermes-event-inventory.json)、[process-tree-state-machine.json](../contracts/process-tree-state-machine.json)、[process-tree-fixture.json](../../tests/fixtures/events/process-tree-fixture.json)、[test_event_contracts.py](../../tests/test_event_contracts.py)；覆盖两个并行 child、tool progress、approval、artifact、retry、failure 和 terminal latch |
| E-01 | 已完成（2026-09-27） | [event-e01-transport.md](../evidence/event-e01-transport.md)；chatrtmgr/lobby 已增加 opaque canonical event carrier、未知事件保留、身份/大小校验、终止和背压测试 |
| E-02 | 已完成（2026-09-27） | [event-e02-gateway.md](../evidence/event-e02-gateway.md)；Gateway/Host Adapter 已直接 emit Hermes 原生过程事件、交互事件、provider/context/usage 扩展，并完成 capability gate 与 envelope event_id |
| E-03 | 已完成（2026-09-27） | [event-e03-relay.md](../evidence/event-e03-relay.md)；chatrtmgr 已实现按 session/run 的 canonical relay ledger、upstream cursor/replay、重复幂等、乱序排序、有限 retention、慢消费者背压和 epoch fencing |
| E-04 | 已完成（2026-09-27） | [event-e04-web2.md](../evidence/event-e04-web2.md)；lobby canonical envelope 保真，web2 过程树消费覆盖 delegation、subagent、tool、plan、artifact、approval/clarification、诊断过滤、乱序、去重和终态 latch |
| E-05 | 已完成（2026-09-27） | [event-e05-catalog-drift.md](../evidence/event-e05-catalog-drift.md)；canonical catalog、Harness capabilities、Go opaque relay 和 web2 explicit/unknown consumer 已自动对账，新增/删除事件会失败 |
| E-06 | 已完成（2026-09-27） | [event-e06-combination.md](../evidence/event-e06-combination.md)；Mac/Ubuntu 22.04 amd64 矩阵、11 份真实链路/fixture 账本、新 bundle 隔离验收、durable child replay 及 customized 镜像部署 smoke 通过 |
| E-07 | 已完成（2026-09-27） | [event-e07-canonical-only.md](../evidence/event-e07-canonical-only.md)；Gateway/chatrtmgr/lobby/web2 canonical-only、落库摘要、生产入口强制 Gateway、完整 interop 和迁移边界已验证 |

E-00/E-00a 的设计交付与源码对账已完成。E-01 至 E-06 保留已有完成记录；E-07 已完成实时路径收敛、兼容边界、迁移文档和组合验收。

## 下一步

E-07 已完成：Gateway gRPC 只接受 canonical event 与 `done/error` 控制帧；lobby 落库和 web2 实时投影均以 canonical 事实为源；chatrtmgr/lobby 生产入口强制 Gateway/Harness 100% admission；旧 chatsvc projection 和固定 chunk oneof 没有生产消费者。完整 Harness interop race 矩阵、Go 包测试、web2 测试和构建通过。重新构建当前 bundle 的镜像仍受本机 Docker Hub token 超时影响，已有 customized Linux/amd64 部署 smoke 证据仍单独保留。

### E-00/E-00a 复核记录（2026-09-27）

- E-00 与 E-00a 全部任务已完成，下表完成项全部为 `[x]`。E-01 至 E-07 已有完成记录。
- 本轮执行 `.venv/bin/python -m unittest tests.test_event_contracts -v`：9 项通过、0 跳过。覆盖 catalog 冻结、排除项、当前 Harness 来源路径/行范围、权限一致性、敏感字段、envelope 身份、双 child lineage 和 terminal latch。
- 本轮执行 `python3 tools/check_event_catalog.py`：36 个 baseline + 20 个过程扩展，共 56 个 canonical event，与 Harness catalog/capabilities、Go opaque relay 和 web2 consumer 对账无漂移；未知事件有受控保留入口。
- 已冻结字段/权限表、序号范围、cursor/replay、冲突和 retention/epoch 边界、projection gap 分类。`subagent.thinking` 为 `restricted`；`subagent.complete/text` 来源登记为 `delegate_tool_child_run.py`。schema 包含 `subagent_progress`、`grace.summary`、`finalizer.fallback` 的过程身份校验，进程级 `end` 不误要求 session。
- 过程 fixture 覆盖两个并行 child、delegation、tool progress、plan、artifact、approval、provider retry、heartbeat、失败 child 和 terminal latch；节点通过事件 identity/lineage 关联，无需解析 assistant 文本。
- 本轮更新 Integration 计划与 E-06 证据：Ubuntu runner 中 Go race、Harness 全套测试、Integration 68 项、组合矩阵和新 bundle 隔离 self-test 均通过且清理 clean；NetworkClaw 和 Harness 的既有未提交修改保留。镜像构建的 Docker Hub token 超时单独记录，不覆盖已有 customized Linux/amd64 部署 smoke 证据。
- 再次执行 `.venv/bin/python -m unittest tests.test_event_contracts -v`：9 项通过；`python3 tools/check_event_catalog.py`：36 baseline + 20 extensions，漂移错误 0；`python3 tools/check_event_process.py`：前端 fixture 3 项通过、1 项按测试条件跳过，过程账本检查通过。这是 E-00/E-00a 契约和 fixture 复核，不扩展为 56 个真实生产事件的端到端验收。
- E-07 验收：`go test -race ./tests/integration/harnessinterop -count=1` 通过；真实 Gateway canonical ledger 覆盖 stream、todo、reset、usage、context、delegate、delegate-failure、delegate-deny、delegate-timeout 和 clarification，并验证 replay、子 Agent lineage、工具副作用与 epoch fencing。`npm test -- --run` 为 37 个测试文件、324 项测试（323 通过、1 跳过），`npm run build` 通过。新增证据见 [event-e07-canonical-only.md](../evidence/event-e07-canonical-only.md)。
- 当前 E-07 bundle 交付闭环：`/private/tmp/networkclaw-e07.tar.gz` 的 `verify-bundle` 通过；隔离 self-test 13/13 阶段通过，`failures=[]`、`missing_inputs=[]`，并完成重建 bundle 的再次校验。报告见 [.integration-state/evidence/bundle-self-test-e07-final.json](../../.integration-state/evidence/bundle-self-test-e07-final.json)，bundle SHA-256 为 `a7d0cc5e7e18c53edb32753975be038b4a688fc6f2f248d37a7faf498a7ff500`。

### E-00/E-00a 逐项完成清单

| 任务 | 完成项 | 证据 |
|---|---|---|
| E-00 | [x] versioned envelope、字段表、baseline/扩展/实验性/排除分类 | schema、catalog、合同；v1 无实验性事件 |
| E-00 | [x] sequence 范围、cursor、replay、幂等、未知事件和兼容规则 | 合同“序号、Cursor 和 Replay”“兼容和终态” |
| E-00 | [x] 用户/控制/诊断/终止订阅面与权限 | 36 baseline 映射、20 extension 映射、权限表和 inventory |
| E-00 | [x] 缺事件、名称损失、权限降级、有意非用户面差异 | 合同“目录状态和 Projection Gap”及原 projection-gap 评估 |
| E-00 | [x] 最小过程事件集合冻结 | catalog + fixture；权限与身份反例测试 |
| E-00a | [x] Hermes/Host source inventory、源码路径/行号 | inventory + 当前 checkout 路径/行范围复验 |
| E-00a | [x] 原生名称、Host-derived 名称与最小 payload 字段 | extension 映射、inventory；不把旧 baseline 名称当作实时 alias |
| E-00a | [x] 主 turn、allocation、child、tool、plan、interaction、artifact 关联模型 | process-tree-state-machine + fixture |
| E-00a | [x] 展示摘要与原始事实区分、安全默认 | 权限表、state machine projection_rules、敏感字段测试 |
| E-00a | [x] 双并行 child、tool progress、approval、artifact、失败重试稳定过程树 | fixture evt-1 至 evt-24；合同过程树和 lineage 测试，不解析 assistant 文本 |

E-00/E-00a 全部设计验收项已完成。该完成状态仅指契约、来源对账和 fixture，不表示 56 个事件已经逐项经过真实分布式链路。

### E-00 [P0] 冻结 canonical event envelope 和目录对账

**依赖**：Gateway 计划 G-08。

**主责**：Integration；Harness/UE 与 NetworkClaw 评审。

**内容**：

- 以 Harness `catalog.py` 的 36 个事件为 baseline catalog，并把 E-00a 对账出的过程扩展事件加入同一 versioned catalog；文档必须标出 baseline、扩展、实验性和排除项。
- 定义 envelope、sequence 范围、cursor、replay、重复事件和未知事件策略。
- 明确用户面、控制面、诊断面和终止事件的订阅边界。
- 记录现有 projection gap，区分真正缺事件、降级事件和有意非用户面事件；特别记录当前 `subagent.start/complete/text` 被 adapter 映射成 `subagent.started/completed` 的名称损失。
- 固定用户过程视图需要的最小事件集合：delegation allocation/resolution、subagent lifecycle/progress/text、tool generation/progress、plan、approval/clarification、artifact、heartbeat、context、usage 和 terminal。

**验收**：形成 versioned schema、字段表、兼容规则、36 个 baseline 逐项映射表、过程扩展逐项映射表和排除清单；没有未声明的静默丢弃。每个扩展事件必须标明 Hermes 生产点、是否默认用户面、权限/脱敏规则和降级策略。

**完成证据**：

- [event-catalog-v1.json](../../schemas/events/event-catalog-v1.json)
- [event-envelope-v1.schema.json](../../schemas/events/event-envelope-v1.schema.json)
- [event-catalog-v1.md](../contracts/event-catalog-v1.md)
- `python3.12 -m unittest tests.test_event_contracts`

### E-00a [P0] 建立 Hermes 过程事件与前端过程视图契约

**依赖**：E-00。

**主责**：Harness/UE 与 NetworkClaw web 组；Integration 负责跨仓登记。

**内容**：

- 从 `vendor/hermes/tools/delegate_tool_progress.py`、`delegate_tool_child_run.py`、`agent/stream_delivery.py`、`moa_loop.py` 和 Harness projection 层建立机器可读 source inventory。
- 冻结过程事件原名和 payload 最小字段。Hermes 已有原生来源的名称必须原样保留：`subagent.start`、`subagent.complete`、`subagent.text`、`subagent.thinking`、`subagent_progress`、`moa.reference`、`moa.progress`、`moa.phase`、`moa.aggregating`。由 Host Protocol 或 Harness projection 补充的事件必须在 inventory 中标明来源并单独冻结：`delegation.resolved`、`tool.generating`、`reasoning.delta`、`context.started`、`context.continued`、`provider.attempt`、`provider.retry`、`usage.updated`、`checkpoint.updated`、`grace.summary`、`finalizer.fallback`。
- 明确前端过程模型：一条主 turn 下有 delegation 节点，节点下有 child session/subagent，child 可以有自己的 assistant delta、tool lifecycle、plan 和 terminal；事件必须能按 `parent_session_id`、`parent_turn_id`、`subagent_id` 和 `allocation_id` 关联。
- 定义“显示”和“事实”两层：前端可以把 `subagent.text` 合并成摘要、把 heartbeat 限频、把 reasoning 默认折叠，但不能用摘要替代原事件或丢失失败/取消/超时终态。
- 定义安全默认：`reasoning.delta` 默认关闭或仅摘要；`subagent.text`、tool output、artifact content 均有长度、权限和脱敏限制；原始思维链永不进入普通用户事件。

**最小产物**：`hermes-event-inventory.json`、前端过程树状态机、事件字段/权限表、截图对应的用户过程时序图和 vendor 来源行号。

**验收**：给定一个包含 `delegate_task`、两个并行 child、一个 child tool progress、一个 approval、一个 artifact 和一次失败重试的 fixture，能够画出稳定的过程树；每个过程节点都能回到原始事件，且没有依赖解析 assistant 文本。

**完成证据**：

- [hermes-event-inventory.json](../evidence/hermes-event-inventory.json)
- [process-tree-state-machine.json](../contracts/process-tree-state-machine.json)
- [process-tree-fixture.json](../../tests/fixtures/events/process-tree-fixture.json)
- [test_event_contracts.py](../../tests/test_event_contracts.py)
- Fixture 校验 sequence、event_id 去重、parent/child lineage、terminal latch、权限敏感字段和 catalog membership。

### E-01 [P0] 建立跨仓库事件载体

**依赖**：E-00a。

**主责**：NetworkClaw 后台组；Harness 提供 producer 约束。

**内容**：

- 扩展 chatrtmgr/lobby 的响应载体，能够携带 canonical event envelope，而不是固定语义 oneof 的唯一入口。
- 透传 session/run/turn/request identity、sequence、protocol version 和 payload。
- 保留控制面错误和终止帧的结构化表达。

**验收**：单元测试覆盖完整 envelope、未知事件、过大 payload、非法 identity、终止和背压。

**完成证据**：[event-e01-transport.md](../evidence/event-e01-transport.md)。

### E-02 [P0] 让 Gateway 直接产生 canonical events

**依赖**：E-01。

**主责**：Harness/UE 组。

**内容**：

- Gateway 将 `HermesHostAdapter`/projection 输出转换为 canonical event，不经过 chatsvc projection。
- 补齐 `turn.queued`、`tool.generating`、`tool.progress`、`subagent.*`、`delegation.*`、`approval.*`、`clarification.*`、`artifact.created`、`context.*`、`provider.*`、`usage.updated` 等已确认缺口。
- 保留 Hermes 原生委派事件的来源名和 lineage；不得只发一个 `subagent.completed` 而丢失 spawn、progress、text、thinking、failed 或 interrupted 中间态。
- 对 reasoning、MoA 和 usage 提供 capability/permission gate；未授权时发送结构化摘要或 `warning`，不能静默消失。
- 保留控制面事件和 capabilities 对账。

**验收**：Harness 单仓测试确认声明事件与实际 emit 集合一致；事件 payload、身份和顺序可复验。

**完成证据**：[event-e02-gateway.md](../evidence/event-e02-gateway.md)。

### E-03 [P0] 贯通 chatrtmgr relay、排序和 replay

**依赖**：E-02。

**主责**：NetworkClaw 后台组。

**内容**：

- chatrtmgr 只转发 canonical events，不按连接重造 sequence，不改事件名。
- 实现 per-session/run cursor、断线重连、重复事件幂等和慢消费者背压。
- 保留用户亲和和 lease fencing 对事件流的约束。

**验收**：跨进程测试覆盖乱序输入、断线、重连、重复、旧 epoch、慢消费者和未知事件。

**完成证据**：[event-e03-relay.md](../evidence/event-e03-relay.md)。chatrtmgr relay ledger 以 Harness upstream `sequence` 作为 cursor、以 `event_id` 做幂等键，支持 bounded replay、replay-only reconnect、epoch takeover fencing 和 subscriber backpressure；Gateway、gRPC、Lobby 和 transport tests 已覆盖事件身份保真。

### E-04 [P0] 更新 lobby 和前端消费模型

**依赖**：E-03。

**主责**：NetworkClaw lobby/web 组。

**内容**：

- lobby 保留 canonical event type，按订阅面过滤而不是改名。
- 前端建立事件驱动的过程视图：主 turn、delegation allocation、subagent/child session、tool、plan、approval/clarification、artifact 和终态各自是可关联节点。
- 前端可以把事件组合成现有卡片和状态；approval、clarification、subagent、artifact 使用事件事实，不再从 tool chunk 反推。
- 提供截图式过程反馈：用户提交后先看到 `turn.queued/turn.started`；派遣时看到 delegation 和子 Agent 节点；运行中看到 tool/plan/progress/heartbeat；等待用户时看到 approval/clarification；完成、失败、取消和重试必须保留完整时间线。
- `reasoning.delta` 默认折叠且受权限控制；界面显示“正在分析/规划”等摘要时，必须由显式事件或 producer 状态生成，不得把隐藏思维链转发到浏览器。
- 控制面事件不默认进入用户聊天视图。

**验收**：前端契约测试和端到端 UI 测试覆盖事件渲染、关联 ID、去重和终态 latch。

**完成证据**：[event-e04-web2.md](../evidence/event-e04-web2.md)。web2 36 个测试文件、322 项通过；Go lobby/chatrtmgr 包测试通过。

### E-05 [P0] 建立目录生成与 capability 漂移门禁

**依赖**：E-04。

**主责**：Harness/UE 与 NetworkClaw 联合。

**内容**：

- 从 canonical catalog 生成 Go/TypeScript 类型或校验数据。
- `capabilities.query/report` 对账实际 producer、transport 和 consumer。
- 未处理事件必须在构建或组合测试中显式失败或进入受控 unknown bucket。

**验收**：新增/删除事件会触发漂移测试；不存在三份手工清单互相不一致的情况。

**完成证据**：[event-e05-catalog-drift.md](../evidence/event-e05-catalog-drift.md)。`make validate-events`、漂移 mutation tests 和 Harness runtime capability 对账通过；生成的 [consumer report](../../schemas/events/event-catalog-consumer-report-v1.json) 列出 56 个事件的显式处理和受控 unknown bucket。

### E-06 [P0] 完成 baseline + process extension 组合验收

**依赖**：E-05。

**主责**：Integration；三仓联合。

**内容**：

- 每个 baseline 和扩展 canonical event 至少有 producer、transport、consumer 或明确非用户面声明。
- 覆盖多 session、两个并行 subagent、delegation grant/deny/timeout、subagent progress/text/failure、approval/clarification、tool generating/progress、plan、artifact、heartbeat、context compaction、usage、lease takeover、replay 和故障终态。
- 生成一份前端过程 ledger，验证同一 `parent_turn_id` 下的子 Agent、工具和产物可以按 lineage 重建，不依赖到达顺序恰好与生产顺序相同。
- 生成机器可读事件 ledger 和丢失/降级/重命名报告。

**验收**：Mac smoke、Ubuntu 22.04 full matrix、bundle self-test 和部署 smoke 均通过；没有静默丢弃；截图式过程 fixture 能在 web2 端到端测试中重建 delegation/subagent/tool/plan/approval/artifact 时间线。

**阶段证据**：[event-e06-combination.md](../evidence/event-e06-combination.md)。Mac/Ubuntu 22.04 amd64 组合矩阵、真实链路/fixture 账本、bundle 校验与隔离 self-test、跨进程 child replay 和 customized 镜像部署 smoke 均已有证据。

**E-06 逐项进度（2026-09-27）**：

- [x] 导出实际 web2 parser/reducer/render 的 fixture 过程 ledger；两个 child、allocation、tool、plan、approval、artifact 的 lineage 可重建。
- [x] 正序/倒序/child 先到/terminal 先到/交错/重复输入验收；终态不被冲突事件改写。
- [x] 56 个 catalog 名称的 browser envelope/payload 保留与受控 unknown 对账；报告含源码 hash 和 fixture loss/downgrade/rename 列表。
- [x] 前端门禁纳入 `make combination-matrix`，Mac 矩阵通过且清理 clean；web2 37 文件 325 项、typecheck/build 通过，runtime 账本测试在矩阵中另行执行。
- [x] Go 保留原始 canonical envelope；兼容去重继续发送 canonical 事实，前端最终快照去重仅影响展示。
- [x] 实际 Hermes stream/todo/reset 生产帧与 Gateway、TCP gRPC/lobby、web2 reducer/render 账本对账；未由真实 Hermes 产生的事件族按 fixture/受控 unknown bucket 验收，不冒充生产覆盖。
- [x] 共享 24-event child 过程 fixture 穿过 gRPC/lobby/web2；修复 root-only 身份校验，保留 grant、parent lineage、child run/turn 和 allocation 边界。
- [x] 真实 Hermes 双 child grant、deny、allocation timeout 穿过 UDS/Gateway/gRPC/lobby/web2；两 child 均在首个完成前启动，allocation 与 child identity 对账通过。修复 timeout 缺少 `delegation.resolved`，拒绝迟到 grant，前端保留 timeout reason；此项不代表 child 独立流 replay 已完成。
- [x] Child replay 在 grant/start 之后恢复时的 authority 重建；Lobby forwarder 共享权威 lineage registry，按 root session/run/turn、allocation 和 child session 恢复，伪造 parent lineage 仍拒绝；跨进程 durable registry/restart 已由 E-06 contract fixture 和组合矩阵验收。
- [x] Catalog 检查使用已有 source resolver，避免 Linux/bundle checkout 名称或大小写导致定位错误。
- [x] 对真实 Hermes 已覆盖的 stream/todo/reset 账本，以及共享 child contract fixture 执行 producer → Gateway → gRPC/lobby → web2 完整 envelope 对账；其余事件族仍不能用 fixture 探针冒充真实来源。
- [x] 将 child failure、tool progress、clarification 和 usage 加入真实事件账本；`gateway-delegate-failure.json`、`gateway-todo.json`、`gateway-clarification.json` 和 `gateway-usage.json` 均完成 producer → Gateway → gRPC/lobby → web2 对账。context compaction 仍缺真实触发场景。
- [x] 上一增量 bundle 完成 `verify-bundle` 和隔离 `bundle-self-test`；SHA-256 为 `496c33a26942e98a159c30ef04e2bb8bb7519fdd4d8cbbdf2fc552ada9afbd02`，self-test 的 13 个阶段全部通过并清理 workspace；此快照不含本轮 context/history 修复。
- [x] context compaction 的真实 producer → Gateway → gRPC/lobby → web2 ledger；四轮成功 warmup 后由 native Hermes 压缩历史，`context.started/continued` 各一次且 version=1，16 个原始事件全程对账无丢失/降级/改名。本轮 Mac 八阶段矩阵通过且清理 clean。
- [x] 包含本轮 context/history 修复的 bundle 重建、verify-bundle 和隔离 self-test；SHA-256 `23708419f68a92c89e0aeb22bffbbe0f3e946950d8ae498875aeab0fc9c52f08`，13 阶段通过，workspace 已清理。
- [x] 跨进程 durable child lineage/restart 后 replay 恢复证据；Lobby 在已有 PostgreSQL run admission 中保存经过校验的 allocation/child run/turn，转发前提交；不同 OS worker 在游标越过 grant/start 后恢复 child progress，跨 tenant、旧 epoch 与冲突 identity 拒绝。`event-e06-child-restart.json` 为 TCP gRPC + PostgreSQL contract fixture 证据，不冒充 native child producer；组合矩阵已加入必跑门禁。
- [x] 包含 durable child authority 增量的新 bundle、隔离 self-test 与镜像部署 smoke；bundle SHA-256 `4813b6f86bb74570d65a5dc7cb72a63bbfb2bda35ba663e275ff1e55be7f2422`，镜像 `sha256:2a6fe03887dab96593733b0128560ead7f99db75c712d25cb4b5ab753022b0a2`，部署 cleanup=0。
- [x] Ubuntu 22.04/amd64 full matrix；独立 Ubuntu runner 中 Go race、Harness 全套测试、Integration 68 项、组合矩阵和 bundle self-test 全部通过，清理 clean。证据见 `.integration-state/evidence/event-e06-ubuntu-*.log/json`。
- [x] 当前 customized Linux/amd64 镜像与部署 smoke；从包含 durable child authority 的 bundle `4813b6f86bb74570d65a5dc7cb72a63bbfb2bda35ba663e275ff1e55be7f2422` 构建，镜像 ID `sha256:2a6fe03887dab96593733b0128560ead7f99db75c712d25cb4b5ab753022b0a2`。使用已有 BASE_IMAGE override 指定缓存 amd64 Python 3.12.11 Bookworm，不能作为默认 pinned base 成功证据。隔离 Compose 项目验证 healthz/readyz/metrics、gRPC、真实 Gateway 会话创建/绑定/关闭及 web2 readyz，cleanup=0；builder 为 macOS，不替代 Ubuntu gate。

### E-07 [P1] 移除兼容 chunk 和旧事件投影

**依赖**：E-06。

**主责**：NetworkClaw 后台组；Integration 发布门禁。

**内容**：

- 删除 chatsvc projection、固定 chunk oneof 的生产依赖和前端旧反推路径。
- 保留必要的历史回放兼容读取，但不再作为实时生产协议。
- 更新合同、文档、bundle 和版本迁移说明。

**验收**：新 canonical event 流成为唯一实时事实源；旧兼容路径没有生产消费者。

**完成证据**：

- [event-e07-canonical-only.md](../evidence/event-e07-canonical-only.md)
- [event-catalog-v1.md](../contracts/event-catalog-v1.md) 的 E-07 实时生产边界
- Go race interop、web2 全量测试和构建记录

**逐项完成清单**：

- [x] Gateway UDS/JSONL 到 chatrtmgr 只生产 canonical event；`done/error` 仅作控制帧。
- [x] gRPC/lobby 保留并校验原始 envelope；旧固定 oneof 不再进入 Harness 实时路径。
- [x] lobby recording emitter 从 canonical assistant/tool/reasoning summary 读取落库事实，并保留 child tool lineage。
- [x] web2 实时 reducer 只消费 canonical event；审批、澄清、子 Agent、工具、计划和产物不再由旧帧反推。
- [x] chatrtmgr 强制 Gateway target，lobby 强制 Harness enabled + 100% rollout；生产不再选 legacy execution path。
- [x] replay、terminal、epoch fencing、未知事件和 canonical-only 负向测试通过。
- [x] 历史读取与隔离 legacy 对照保留；合同、部署、handoff、bundle 相关说明已更新。

## 完成定义

- 36 个事件的原名、payload 和 envelope 在 Gateway 到客户端路径可验证地保持一致。
- Hermes 过程扩展事件的原名、payload 和 parent/child lineage 在 Gateway 到客户端路径可验证地保持一致。
- sequence、run/session identity、cursor、replay、背压和幂等有组合证据。
- capability/catalog/生成类型不会漂移。
- 用户面和控制面事件有明确订阅边界。
- 前端可以展示一次真实对话的排队、执行、工具、计划、委派、子 Agent、审批/澄清、产物、重试和终态全过程。
- chatsvc 的 projection 和兼容 chunk 不再是实时生产依赖。
