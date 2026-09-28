# Harness 事件投影缺口梳理

> 状态：**调研完成，决策待定**。本文只做事实梳理与影响分析，不含改动。
> 落点说明：本文是跨仓库分析（Go 侧 + Harness 侧 + 前端），按 `repo-routing.md` 的边界判据，
> 权威修改必须回到对应源码仓库；本文放在 Integration 侧仅作为协调与验收输入。

## 1. 一句话结论

Harness 的 Host Protocol 目录里有 **36 个事件**，Go 侧真正投影给用户的只有 **10 个**，
前端最终能渲染的词汇量是 **9 个**。缺口本身可控，但真正的问题是两类更隐蔽的形态：

- **降级**：事件到了，但身份在中途被压扁 / 字段被丢弃 / 类型被硬编码覆盖（比缺口更紧急，因为每层单看都自洽）。
- **静默**：丢弃无日志、无计数、无声明。产品侧和排障侧双重不可见，组合测试抓不到。

---

## 2. 链路与词汇表换算

Harness 事件到用户屏幕，中间经过 **四次词汇表替换**：

```
36 个 harness 事件                    networkclaw-harness/src/networkclaw_harness/protocol/catalog.py
  ↓ projectHarnessFrame 投影          NetworkClaw/internal/chatsvc/session/harness_handler.go:753
 8 种 chatsvc StreamChunk             NetworkClaw/internal/chatsvc/model/response.go:30-64
  ↓ UDS JSONL → chatrtmgr（透明转发，无事件语义）
 9 个 proto oneof 臂                  NetworkClaw/api/chatrtmgr/v1/chatrtmgr.proto:196-227
  ↓ gRPC → lobby 再映射
10 种 lobby WS chunk                  NetworkClaw/internal/lobby/model/response.go:356-412
  ↓ WebSocket /ws
 9 个前端联合类型变体                  NetworkClaw/web2/src/api/chat.ts:257-267
```

**关键结构性事实：存在两条独立的生产者路径。** 只有 harness 路径经过 `projectHarnessFrame`；
原生路径（`internal/chatsvc/ai/`）直接产出 chunk，完全绕过 Layer 1。
`reasoning` 和 `turn_end` 两个 chunk kind **只有原生路径有生产者**，harness 路径永远产不出来。
这是下文多处不对称的根源。

`chatrtmgr` 是路由/亲和性代理，不携带任何事件语义
（其 `streamChunkProbe` 在 `internal/chatrtmgr/transport/grpc/server.go:752` 只做类型探测，
注释明确写着「chatrtmgr 与 chatsvc 是不同 domain，禁止直接依赖（零侵入红线）」）。

---

## 3. 事件逐条状态表

图例：**已投影** 用户可见 · **非用户面** 有意由控制/运维层消费 · **静默丢弃** 无处理无日志 · **前端已就绪后端缺生产者**

| # | 事件 | Go 侧 | 用户可见 | 备注 |
|---|---|---|---|---|
| 1 | `assistant.delta` | 已投影 | ✅ | `final=true` 且已见 live delta 时静默丢弃 payload（`:505-509`） |
| 2 | `turn.started` | 已投影 | ⚠️ 降级 | 压成 `run_state`，与 warning 撞 |
| 3 | `turn.completed` | 已投影 | ⚠️ 降级 | 同上 |
| 4 | `turn.failed` | 已投影 | ✅ | |
| 5 | `turn.cancelled` | 已投影 | ✅ | |
| 6 | `turn.controlled` | 静默丢弃 | ❌ | `:713` 已消费为 controlState，只差投影 |
| 7 | **`turn.queued`** | 静默丢弃 | ❌ | **真缺口**。harness 发两次（`host/server.py:504`、`host/interactions.py:46`） |
| 8 | `plan.updated` | 已投影 | ⚠️ 降级 | 压成 `run_state{state:planned}` |
| 9 | `tool.started` | 已投影 | ✅ | 但 `card_kind` 被硬编码成 `"terminal"`（`:810`） |
| 10 | `tool.completed` | 已投影 | ✅ | 同上 |
| 11 | **`tool.progress`** | 静默丢弃 | ❌ | **真缺口**。在 `isLatePublicEvent` 白名单里但无 switch case |
| 12 | **`subagent.started`** | 静默丢弃 | ❌ | **真缺口** |
| 13 | **`subagent.completed`** | 静默丢弃 | ❌ | **真缺口** |
| 14 | **`delegation.requested`** | 静默丢弃 | ❌ | 真缺口。两端都未实现（Go 也不发 `delegation.resolve`） |
| 15 | **`artifact.created`** | 静默丢弃 | ❌ | **真缺口**。产物落盘但无帧 |
| 16 | **`approval.requested`** | 静默丢弃 | 🕳️ | **最严重**：前端完整+有测试，后端零生产者 |
| 17 | **`approval.resolved`** | 静默丢弃 | 🕳️ | 同上 |
| 18 | **`clarification.requested`** | 静默丢弃 | 🟡 | 用户能看到，但走 `tool_start` 反推的侧门 |
| 19 | **`clarification.resolved`** | 静默丢弃 | ❌ | 全仓库零引用，解析无法关联问题 ID |
| 20 | `warning` | 已投影 | ⚠️ 降级 | 压成 `run_state{state:coordinating}`，与 turn.started 撞 |
| 21 | `error` | 已投影 | ✅ | |
| 22 | `end` | 短路 | ❌ | 流终止记账，正确 |
| 23 | `heartbeat` | 静默丢弃 | ❌ | 建议做成活性指示 |
| 24 | `request.accepted` | 短路 | ❌ | 控制面，正确 |
| 25 | `protocol.negotiated` | 非用户面 | ❌ | `client.go:160`，正确 |
| 26 | `health.status` | 非用户面 | ❌ | `client.go:360`，正确 |
| 27 | `metrics.snapshot` | 非用户面 | ❌ | `client.go:373` 合并进 UDS 健康指标，运维通道 |
| 28 | **`capabilities.report`** | 静默丢弃 | ❌ | **防复发关键**：Go 从不调用 `capabilities.query`（零命中） |
| 29 | `session.opened` | 非用户面 | ❌ | `:673`，正确 |
| 30 | `session.closed` | 非用户面 | ❌ | `:315` containsAnyEvent 观察，正确 |
| 31 | `session.draining` | 非用户面 | ❌ | `:315`，正确 |
| 32 | `session.lease.updated` | 非用户面 | ❌ | `:237`，正确 |
| 33 | `session.lease.revoked` | 非用户面 | ❌ | `:237` + 本地 fencing `:216-224`，正确 |
| 34 | `session.lease.replaced` | 非用户面 | ❌ | `:237`，正确 |
| 35 | `session.lease.takeover` | 非用户面 | ❌ | `:237` + 陈旧性检查 `:212`，正确 |
| 36 | `shutdown.completed` | 非用户面 | ❌ | `client.go:407`，靠进程退出确认，够用 |

**统计：已投影 10 · 非用户面消费 11 · 静默丢弃 15（其中真缺口 8）**

### 3.1 目录之外、harness 内部还在产但完全无映射的事件

这些不在 36 的冻结目录里，但 harness 的投影层确实在产出：

| 事件 | 出处 |
|---|---|
| `tool.round.{state}` | `networkclaw-harness/src/networkclaw_harness/projection/events.py:294` |
| `context.started` / `context.continued`（上下文压缩） | `projection/events.py:296-304` |
| `checkpoint.updated` | `projection/events.py` |
| `provider.attempt` / `provider.retry` | `host/server.py` 附近 |
| `grace.summary` / `finalizer.fallback` | `host/server.py` 附近 |

---

## 4. 用户体验影响（本文重点）

按「用户会感受到什么」组织，而不是按协议结构。每项都写明**触发场景**和**用户实际看到的现象**。

### 4.1 会让用户以为系统坏了

| 事件缺口 | 触发场景 | 用户看到的现象 |
|---|---|---|
| `turn.queued` | 用户提交后轮次排在队列里等（如 `runtime_not_ready` 恢复期） | **界面完全无反馈，像卡死。** `queue_position` 被丢弃，无法显示「前面还有 N 个」 |
| `heartbeat` | 长任务执行中（例如长时间工具调用） | **无法区分「在跑」和「死了」**。缺少活性指示，用户倾向手动刷新或重提，可能产生重复轮次 |
| `tool.progress` | 一次工具调用耗时较长 | 工具卡片停在静态的「进行中」直到终态才跳变。**用户无法判断是慢还是卡** |
| `turn.controlled` | 用户点了 steer / cancel | **没有生效确认**。用户不知道自己的干预是否被接受，容易重复点击 |

### 4.2 会让用户看不到 agent 的真正工作

| 事件缺口 | 触发场景 | 用户看到的现象 |
|---|---|---|
| `subagent.started` / `subagent.completed` | agent 拆解任务、并行派发子代理 | **子代理完全不可见。** 用户只看到主线程长时间沉默，然后突然出结果。并行度、每个子任务状态都无从得知 |
| `delegation.requested` | 委派发生时 | 同上，且委派关系不可追溯 |
| `reasoning`（无 harness 生产者） | agent 进行推理 | **思维链完全不可见。** 注意：`reasoning` chunk kind 在前端联合类型里**已经有位置**，传输管道也通，只是 harness 投影这一跳没有生产者 —— 属于「管道铺好、源头未接」 |
| `plan.updated`（降级） | agent 更新执行计划 | 计划更新被压成通用的 `run_state`，**用户看到状态变了但不知道变的是什么**。计划内容丢失 |

### 4.3 会让用户无法完成操作（功能不可用，非体验问题）

| 事件缺口 | 触发场景 | 用户看到的现象 |
|---|---|---|
| **`approval.requested` / `approval.resolved`** | agent 要执行写类工具 | **功能整体不可用。** 现状是写类工具被**直接拒绝**（`ai/tool_execution.go:402,424,428` 返回 `approval_required` 后拒绝），而不是弹出审批询问。前端 `parseApprovalInput`（`web2/src/api/chat.ts:601`）和 `card_kind === 'approval'` 分支（`web2/src/pages/HomePage.tsx:253`）**已完整实现并有测试**（`semanticProjection.test.ts:42`），但 Go 侧**从来没有任何地方产出过 `card_kind="approval"`** —— `CardKind` 常量表（`ai/tools_impl.go:250-257`）里根本没有这个值。`ApprovalCard.tsx:24` 自己的注释写着「审批控制通道尚未连接」。<br><br>另有硬阻断：`internal/chatsvc/session/control_router.go:24-32` 对 harness 会话的 `ResolveInteraction` **直接返回错误**「harness interaction control is not supported by this Host Protocol revision」，且 `HarnessHandler` 连 `ResolveInteraction` 方法都不存在。 |
| `clarification.requested` / `clarification.resolved` | agent 需要向用户提问 | **能弹窗，但机制脆弱。** 澄清卡片不是由协议事件驱动，而是从 `tool_start` 帧里靠 `card_kind === 'clarify'` **反推重建**（`web2/src/pages/HomePage.tsx:250` → `parseClarifyInput`）。`clarification.resolved` 全仓库零引用 —— **用户的回答无法与先前的问题 ID 建立关联**。两个真相源描述同一件事 |

### 4.4 会让用户丢失产出

| 事件缺口 | 触发场景 | 用户看到的现象 |
|---|---|---|
| `artifact.created` | agent 生成文件（报告、图表、代码） | **产物无法被发现。** 文件确实落盘（见 `docs/architecture/hermes-headless-harness.md:170-185` 的 workspace 布局），但没有任何帧宣告它存在。用户只能从工具调用的文本里猜 |

### 4.5 用户看不见但运维/排障受影响

| 项 | 影响 |
|---|---|
| `capabilities.report` | Go 从不调用 `capabilities.query`。**harness 主动提供了一份权威的 36 事件清单，却没人去对账** —— 这是缺口能潜伏至今的机制本身 |
| 8 个死指标 | 声明了但零写入路径，**根本不会出现在 exposition 里**（registry 只遍历实际存在的名字）。照着 `HARNESS_METRICS` 建的看板会显示一排 no-data 面板，且无任何提示说明是 harness 从未发出 |
| `HarnessHandler` 无 logger | 该结构体（`harness_handler.go:30-37`）**连一个 logger 字段都没有**，整个文件零日志调用。被丢弃的事件在排障侧完全无痕 |

### 4.6 用户永远不该看到（明确排除，非缺口）

`protocol.negotiated`、`health.status`、`metrics.snapshot`、`request.accepted`、`end`、`shutdown.completed`、
`session.closed`、`session.draining`、四个 lease 事件。

这些是**控制平面应答**，由 client 层 waiter 按 `RequestID` 对号入座消费
（`harness/client.go:297-330` 的 `readLoop` 按 `RequestID` 分派，**不是按事件类型**）。
把它们投影到用户界面是设计错误。`metrics.snapshot` 尤其 —— 那是运维通道，不是用户体验通道。

---

## 5. 降级问题（比缺口更隐蔽，建议一并评估）

### 5.1 事件身份被压扁，不可逆

`plan.updated`、`turn.started`、`turn.completed`、`turn.failed`、`turn.cancelled`、`warning`
六个语义完全不同的事件，在 `harness_handler.go:762-840` **全部被压成同一个 `run_state` 帧类型**。

三个具体后果：

1. **事件身份到 lobby 层不可恢复。** 下游再也分不清「计划更新」和「轮次开始」。
2. **`warning` 与 `turn.started` 相撞。** 两者都映射到 `state:"coordinating"`（`:768` vs `:836`），
   **一条告警在 Layer 4 和「轮次开始」完全无法区分**。
3. `assistant.delta` 携 `final=true` 且在流式路径上已见过 live delta 时，**整个 payload 被静默丢弃**（`:505-509`），
   而非合并。

> 这一类比缺口更值得优先评估：缺口是「少了东西」，容易发现；降级是「东西到了但变形了」，
> 每一层单看都自洽，只有端到端看才暴露。

### 5.2 `card_kind` 被硬编码覆盖

`harness_handler.go:810` 把 `CardKind` 无条件设为字面量 `"terminal"`，
**覆盖了工具注册表本应提供的真实值**。原生路径拿到的是注册表真实值，harness 路径永远是 `"terminal"`。
这可能直接影响 UI 卡片渲染形态，建议优先确认。

### 5.3 信封字段在中途丢失

| 字段 | L1 harness | L2 chatsvc | L3 proto | L4 lobby | L5 web2 |
|---|---|---|---|---|---|
| `request_id` | ✅ | — | — | — | — |
| `turn_id` | ✅ | — | — | — | — |
| `sequence` | ✅ | ✅ | — | **按连接重造** | 前端按它去重 |
| `run_id` | ✅ | ✅ | — | **永不赋值** | 隔离检查**失效** |
| `protocol_version` | 字符串 | **硬编码 1** | — | 又硬编码 1 | — |

四条要点：

1. **Layer 3 丢掉整个信封。** `decodeStreamChunk(payload []byte)` 只接收 payload，proto 里也没有信封 message。
2. **`sequence` 是断的。** L3 丢弃 → lobby 用**每连接自增计数器重造**（`emitter.go:89-93`）→
   前端按这个伪造的序去重。**harness 的真实顺序在下游不存在。**
3. **`run_id` 在 WS 线上永远为空。** emitter 只设 `Version` 和 `SessionID`，
   源码注释自述「run_id is left empty until the runtime contract supplies it」（`emitter.go:81-82`）。
   因此前端 `web2/src/api/chat.ts:740` 那个 `run_id` 隔离检查**当前是死逻辑**。
4. **`protocol_version` 被两次硬编码为 `1`**，不是传递值。harness 实际协商出的版本在下游不可见。

---

## 6. 观测面（22 声明 / 14 实现）

`networkclaw-harness/src/networkclaw_harness/observability.py:17-25` 声明了 22 个名字的 allowlist
（`HARNESS_METRICS`）。枚举 `src/` 下所有 `.gauge/.inc/.observe(` 调用点，得到 **18 个写入点、14 个真正有写入路径的名字**。

**已实现（14）**：`readiness`、`active_sessions`、`queue_depth`、`protocol_errors_total`、
`turns_started_total`、`turns_terminal_total`、`health_queries_total`、`tools_started_total`、
`tools_terminal_total`、`provider_requests_total`、`provider_latency_ms`、
`provider_input_tokens_total`、`provider_output_tokens_total`、`protocol_latency_ms`

**声明即死（8）**：`recoveries_total`、`recovery_unknown_total`、`active_runs`、
`rss_bytes`、`cpu_ticks`、`turn_latency_ms`、`tool_latency_ms`、`recovery_latency_ms`

两个接近命中值得注意：

- **`active_runs`**：`host/interactions.py:14` 确实维护 `_active_runs` dict，但那是 run 归属的内部查找表，
  **从不推入 registry 当 gauge**。
- **`rss_bytes` / `cpu_ticks`**：`lifecycle/supervisor.py:360-370` 真的从 `stat` 算出了这两个值，
  但只塞进普通 dict 供 `DiagnosticService.snapshot` 使用。**资源占用其实可见，只是走 diagnostics 而非 Prometheus** ——
  两条通道一条通一条不通，从声明上完全看不出区别。

**缺口会向下游传播**：k8s 侧 `collect_k8s_diagnostics.py` 只能通过 chatsvc UDS 路径拿 Prometheus
（`client.go:367-379` 把 harness exposition 合并进 chatsvc 健康指标并打 `chatsvc="..."` label），
所以这 8 条缺失序列在合并之后依然缺失。

---

## 7. 五层改名映射

### 7.1 概念对照

| 概念 | L1 harness | L2 chatsvc | L3 proto | L4 lobby | L5 web2 |
|---|---|---|---|---|---|
| 文本增量 | `assistant.delta`(`content`) | `content` | `content=1` | **`chunk`** | `'chunk'` |
| 工具开始 | `tool.started` | `tool_start` | `tool_start=4` | `tool_start` | `'tool_start'` |
| 工具结束 | `tool.completed` | `tool_end` | `tool_end=5` | `tool_end` | `'tool_end'` |
| 工具进行中 | `tool.progress` | — | — | — | — |
| 轮次边界 | `turn.*` | `turn_end`（仅原生） | `turn_end=7` | `turn_end` | `'turn_end'` |
| 计划/运行状态 | `plan.updated`,`turn.*`,`warning` | `run_state`（压扁） | `run_state=8` | `run_state` | `'run_state'` |
| 流结束 | `turn.completed`(`end:true`) | `done` | `done=2` | `done` | `'done'` |
| 错误 | `error` | `error` | `error=3` | `error` | `'error'` |
| 推理 | **无此事件** | `reasoning` | `reasoning=6` | `reasoning` | `'reasoning'` |
| 记忆增量 | — | `memory_delta` | `memory_delta=9` | 内部拦截 | **永不发送** |
| 旧工具帧 | — | — | — | `tool_call`(legacy) | `'tool_call'`(legacy) |
| Agent 归因 | — | `.Agent` | `agent=20`（oneof 外） | `.Agent` | `agent` |
| 子代理 | `subagent.*` | — | — | — | — |
| 审批 | `approval.*` | — | — | — | 前端已就绪 |
| 澄清 | `clarification.*` | — | — | — | 靠 tool_start 反推 |
| 产物 | `artifact.created` | — | — | — | — |

### 7.2 字段级改名

| # | 从 | 到 | 位置 |
|---|---|---|---|
| 1 | `content`（L1 payload） | `content`(L2) → `chunk`(L4 类型) → `content`(L4 字段) | `harness_handler.go:762`、`grpc_forwarder.go:388` |
| 2 | `tool_name` | `.Tool` → proto `name` → lobby `tool` | `harness_handler.go:797`、`server.go:852` |
| 3 | `invocation_id` | `.ID` → proto `tool_call_id` → `id` | `harness_handler.go:798`、`server.go:849` |
| 4 | `display_arguments` | `.Input` → proto `args_json` → `input` | `harness_handler.go:801-804`、`server.go:850` |
| 5 | `result` / `summary` | `.Output` → proto `result_json` → `output` | `harness_handler.go:805-808`、`server.go:851` |
| 6 | `TurnEnd.Turn` | proto `turn_index` → lobby `turn_index` | `server.go:952` |
| 7 | 状态 `succeeded`/`success`/`observed` | `success` | `harness_handler.go:889-897` |
| 8 | `item_id`（payload 键） | `.ItemID` → web2 `item_id` | `harness_handler.go:883` |
| 9 | `protocol_version`（字符串） | `.Version`（int，**硬编码 1**） | `harness_handler.go:879` |

### 7.3 存在但没有上游/下游对应物的名字

**下游有定义、无生产者（死代码）**：

- **`tool_call`** — L4 `StreamChunkToolCall` 已明确标记为 legacy、被两阶段类型取代，
  `recordingEmitter` 仍处理它但无人发出。前端保留 `'tool_call'` 分支纯粹为了旧历史回放。
- **`memory_delta`** — L4 声明了它，但 `recordingEmitter` 拦截并保留
  （`routing.go:1797-1801` 存下后 `return nil`，从不 `Emit`），字段标了 `json:"-"`。
  前端联合类型里**没有**这个成员，所以连意外收到的可能都没有。
- **`turn_end`** — 没有 Layer 1 祖先，由 chatsvc 自己的轮次边界检测合成。
- **前端 `parseApprovalInput` + `card_kind === 'approval'` 分支** — 有实现有测试，无生产者。

---

## 8. 根因：三份手工清单无一致性校验

Go 侧存在**三份互相独立、手工维护**的清单，**彼此之间没有任何一致性校验**：

| 清单 | 位置 |
|---|---|
| 投影 switch | `internal/chatsvc/session/harness_handler.go:753-846` |
| 迟到帧白名单 | `internal/chatsvc/harness/client.go:334-336`（`isLatePublicEvent`） |
| 指标 allowlist | `networkclaw-harness/src/networkclaw_harness/observability.py:17-25` |

已确认前两份**内容已不完全一致**（白名单含 `warning`/`heartbeat`/`end`/`turn.started` 而 switch 无对应处理）。

**对照组 —— hermes 是怎么做的**：它的 73 个前端事件**不是手写清单**。
`scripts/gen_gateway_contracts.py` 从 Python 的 `registry.EVENTS` 生成 TypeScript 的 `GATEWAY_EVENT_TYPES`，
而 `tests/tui_gateway/contracts/test_generated.py` **会在两份漂移时失败**，Python 是唯一真相源。
另有 `registry.assert_complete` 强制「声明 ⇔ 实际发出」，不一致直接抛错并打出两个列表。

**共同的失败形态**：上游有 → 中游有个看起来完备的清单 → 下游实际少一截 → **中游没有任何日志或断言标记这个差**。
这个形态在产品侧（36→10）和运维侧（22→14）**同时出现**。

---

## 9. 协议记录层面的连带问题

按 `cross-repo-protocol.md`，协议变更要求三侧留下一致记录。当前状态：

| 侧 | 状态 |
|---|---|
| Harness | **正确** —— 它发出自己声明的东西 |
| Go | **缺投影** —— 36 声明、9 处理 |
| Integration | **无组合测试能抓到** —— `tests/integration/harnessinterop/matrix_test.go` 只断言 `session.closed` + end（`:39`）和 lease 转换（`:129,141`） |

另外，`docs/architecture/hermes-headless-harness.md:155-159`（Go 侧文档）**已经写了**
`clarification.requested` / `approval.requested` / `artifact.created` 的**预期映射** ——
即**文档断言了一个实现不存在的映射**。按规则文件的说法，这正是「下一个上下文会从错误的一侧开始推理」的形态。

---

## 10. 待验证项（明确未结论，不应据此行动）

1. **记忆轮次的 `done` 帧可能重复。** `ForwardStreamResponse` 中 `done=2` 与 `memory_delta=9` 都带终止语义。
   在记忆分支上 `decodeStreamChunk` 返回 `memory_delta` 臂**不带 `done`**（`server.go:891-896`），
   lobby 补发一个合成 `done`（`grpc_forwarder.go:395-402`）；同时 chatsvc 又从 `adapter.go:434` 和
   `manager.go:344` 独立发 `done`。**到底到前端是一个还是两个 `done`，取决于哪条 emit 路径跑了** ——
   前端 terminal latch（`chat.ts:711,747`）会吞掉第二个，把重复**掩盖**而非防止。
   **这需要针对性测试，不是读代码能定的。**
2. **harness 侧声明的 36 是「声明集」，非「运行期实际发出集」。**
   `registry.assert_complete` 强制二者一致，但它跑在测试隔离下，本次调研**未执行测试套件**验证。
3. **`clarification` 经 `tool_start` 反推的完整性未验证** —— 未逐路径确认该重建在复杂场景下是否完整。
4. **其余 `harness_handler.go` 方法是否对某些事件有边带处理未穷尽审计** —— 本次聚焦投影 switch 与
   client 分派路径。

---

## 11. 建议的决策输入（不预设结论）

以下排序是**影响面**排序，不是工作量排序。最终取舍取决于产品形态，尤其第 3、4 项与
「是否做多端接管 / Remote Control 类功能」强相关。

| 级别 | 项 | 性质 | 为什么排这个位置 |
|---|---|---|---|
| **P0** | 审批通道（`approval.*`） | 功能不可用 | 前端完整+有测试、后端零生产者；写类工具当前直接拒绝。**唯一一处「看起来能用、实际是死的」** |
| **P0** | 澄清收敛（`clarification.*`） | 双真相源 | 能用但机制脆弱；`resolved` 无法关联问题 ID |
| **P0** | `run_state` 压扁 | 已有事件降级 | warning 与轮次开始相撞；事件身份不可恢复 |
| **P1** | `turn.queued` | 真缺口 | 排队时界面像卡死 |
| **P1** | `subagent.*` | 真缺口 | agent 归因管线只接在遗留循环上，`AgentCard` 是死代码 |
| **P1** | `capabilities.report` | 防复发 | Go 从不问。**这是缺口能潜伏至今的机制本身** |
| **P1** | `card_kind` 硬编码 | 已有事件降级 | 可能直接影响 UI 渲染，建议优先确认 |
| **P2** | `tool.progress` / `artifact.created` / `heartbeat` / `turn.controlled` | 真缺口 | 长任务反馈、产物发现、活性指示 |
| **P2** | 8 个死指标 | 运维缺口 | 接上或从 allowlist 删除 |
| **P2** | `default` 静默 + 无 logger | 根因 | 把「静默」变成「可查」 |
| **P2** | 三份清单收敛 | 根因 | 单一定义源 + 生成 + 漂移即失败 |
| **P2** | 信封丢失（`run_id`/`sequence`） | 结构性 | 前端去重与隔离检查当前失效 |
| **待定** | `session.*` lease 组 | 视产品形态 | 若做多端接管/断线重连则升至 P1 |

---

## 12. 附：hermes 侧对照数据（供判断「要不要对齐」）

Hermes 的前端契约是 **73 个事件**（`tui_gateway/contracts/events.py` 66 + `display.py` 4 +
`connectors_operation.py` 2 + `server_requests.py` 1），注册表在 `registry.py:49`，
生成的 TS 侧 `GATEWAY_EVENT_TYPES` 独立验证为 73 个、集合一致。
传输是 JSON-RPC 2.0 换行分隔、`method: "event"`，stdio 与 WebSocket 共用同一线协议（**不是 SSE**）。

**重要：`vendor/hermes/` 里看不到这份契约。** vendored 树是 allowlist 裁剪产物，
整个 `tui_gateway/` 包被排除（`upstream/hermes-runtime-files.txt` 中 grep `tui_gateway` 命中 0），
73 个名字在 vendored 树里**只命中 21 个**。契约需看完整上游 checkout。

**对齐判断**：hermes 的 73 里包含大量 GUI 外壳事件（`pet.*` 3 个、`voice.*` 4 个、
桌面 GUI 8 个、`display.*` 4 个），这些与服务端会话协议定位不同，**不应作为对齐目标**。
有参考价值的集中在 agent 行为可见性：`subagent.*`（6 个）、`tool.generating`、`todo.updated`、
`reasoning.delta`、`session.usage`、`status.update`、`message.interim`、`notification.show`。
