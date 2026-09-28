# Harness Gateway 亲和与执行边界

## 状态

**目标设计和 Gateway 迁移已完成；事件统一的 E-07 实时边界已落地。**

本文记录 Harness Gateway 替代 chatsvc 成为用户亲和执行进程后的目标边界，以及当前三个仓库的完成度。它是跨仓库设计和验收输入，不在 integration 中复制 Go 或 Harness 业务实现。

## 目标拓扑

```text
user_id
  -> 一个 Harness Gateway 进程
      -> 多个 session_id
          -> 各自独立的 Hermes session/runtime
              -> 各自按 agent_id 选择或重建 Agent
```

这四层绑定解决的是不同问题：

| 层级 | 绑定关系 | 负责什么 |
|---|---|---|
| chatrtmgr | `user_id -> Harness 进程` | 用户亲和、进程启动、UDS、故障重启 |
| Harness Gateway | `session_id -> _HermesSession` | 会话状态、workspace、lease、turn、事件流 |
| Hermes Adapter | `session_id -> Agent 实例/缓存` | Agent 生命周期、provider route、上下文和工具绑定 |
| Agent 配置 | `agent_id -> 配置选择` | model、provider、tool grant、profile、预算 |
| Hermes runtime | `turn/supervisor` | 执行循环、工具调用、取消、steer、delegation |

### 亲和键的含义

`user_id` 是进程亲和键，不是 Agent 的身份，也不是 session 的替代品。一个用户可以在同一个 Gateway 进程中拥有多个独立 session；一个 session 使用一个 agent 配置，但不同 session 不共享可变的 Agent 上下文。

`agent_id` 先作为会话内的配置选择使用，不提升为进程亲和键。目标是让 Gateway 根据它选择 model、provider、tool grant、profile 和预算；当前 Harness 已有按 session 缓存和重建 Agent 的机制，但 `agent_id` 作为显式跨进程输入还需要接线。只有当某类 Agent 需要独立资源配额、独立重启或独立部署时，才评估把进程键扩展为 `user_id + agent_id`。

## 职责边界

### chatrtmgr

- 根据 `user_id` 复用或启动 Harness Gateway 进程。
- 为每个 Gateway 注册唯一 service/socket，并处理 UDS 连接、健康检查、退出和重启。
- 参与服务级故障恢复，但不持有 Hermes transcript、Agent loop 或工具执行事实。
- 保持用户亲和；不能把 `agent_id` 当作 session 状态的替代品。

### Harness Gateway

- 成为 chatsvc 当前用户亲和执行入口的替代者。
- 接收 Host Protocol 命令，校验 session 身份、lease、execution epoch 和 host grant。
- 在一个进程内管理多个 session，并将请求路由到对应的 `_HermesSession`。
- 负责完整事件流的产生、顺序、背压和传输信封；事件名沿用 Harness Host Protocol。
- 负责 Gateway 进程内的会话级隔离。一个 session 的 fence 或 Agent 重建不能影响同一进程中的其他 session。

### HermesHostAdapter 与 Hermes runtime

这一层**沿用当前 Harness 的实现，不重新设计一套**。当前代码中的 `HermesHostAdapter` 已经承担 session 到 Hermes 执行层的适配职责；`_HermesSession` 是它的会话状态对象。

- 每个 `_HermesSession` 持有自己的 workspace、runtime、工具会话和执行状态。
- `HermesHostAdapter` 负责把 Host Protocol 的 session/turn/control 请求交给对应的 `_HermesSession`。
- Agent 是 session 内的可替换缓存，不是跨 session 的共享可变对象；当前已有按 provider route、profile、tool grant 和预算变化重建 Agent 的机制。
- 目标是让 session 根据 `agent_id` 参与 Agent 配置选择；`agent_id` 目前还没有作为完整的显式跨进程输入接入，需要补齐请求、session state 和选择逻辑。
- Hermes runtime 继续负责 turn 执行、工具调用、取消、steer、delegation 和上下文生命周期。
- NetworkClaw 的用户亲和、lease authority、epoch fencing、跨节点接管不下沉为 Hermes 的职责；Harness 只接收并执行这些控制结果。

目标代码关系是：

```text
Harness Gateway
  -> HermesHostAdapter
      -> _HermesSession
          -> Hermes Agent/runtime
```

因此，`HermesHostAdapter` 是**现有会话执行适配器**，不是新的分布式控制面；新增的主要组件是直接承接 chatrtmgr 的 Harness Gateway 外壳。

### supervisor 的边界

本文中的 `supervisor` 只表示 Hermes runtime 内部的 Agent/turn 执行生命周期管理。它不表示 NetworkClaw 的分布式 supervisor，也不负责：

- 用户到进程的 affinity；
- Gateway 进程启动、重启和服务发现；
- lease authority、epoch takeover 和跨节点接管；
- chatrtmgr 的 UDS 连接管理；
- Gateway 到 lobby/client 的事件传输。

## 故障范围

| 故障 | 预期影响 |
|---|---|
| Agent/provider route 变化 | 重建一个 session 的 Agent，保留该 session 的身份和历史 |
| 一个 session 被 fence | 只停止该 session 的执行和事件，不影响同一进程的其他 session |
| 一个 Agent 执行失败 | 由该 session 产生终态或错误事件；不重启整个用户 Gateway |
| 一个 Harness Gateway 进程崩溃 | 影响该用户在该进程中的所有 session；由 chatrtmgr/lease 恢复 |
| chatrtmgr 或节点故障 | 由服务发现、lease、takeover 和重连流程处理 |

因此，`user_id -> 进程` 提供用户级隔离，但不等于“每个对局一个进程”。对局级隔离由 `session_id -> _HermesSession` 提供。

## 当前完成度

| 能力 | 当前状态 | 证据或缺口 |
|---|---|---|
| chatrtmgr 按用户复用服务 | **已有** | 当前 binding manager 以 `user_id` 查找和复用服务；`agent_id` 尚未组成绑定键 |
| Gateway 进程承载多个 session | **已完成，默认入口已接线** | `python -m networkclaw_harness.host --socket-path ...` 已通过真实 UDS + JSONL 验收；chatrtmgr、Compose、Helm 和本地入口已使用 Gateway target |
| `session_id -> _HermesSession` | **已有** | `HermesHostAdapter` 使用 session map 保存会话对象，并校验 session/tenant/user/lease 身份 |
| session 独立 workspace/runtime | **已有** | session open 创建独立 workspace/runtime；已有多 session 和恢复测试 |
| `HermesHostAdapter -> _HermesSession` 执行适配 | **已有，沿用** | 当前 Harness 已用 `HermesHostAdapter` 管理 session、turn、control 和 runtime，不需要在 Gateway 迁移中重写 |
| session 内 Agent 缓存/重建机制 | **已有，沿用** | Agent 按 provider route、profile、tool signature 和 grant signature 缓存；变化时重建 |
| `agent_id ->` 配置选择接线 | **已完成** | `agent_id` 已从 Lobby/HarnessBinding 经 proto、chatrtmgr、Gateway 接入 session state 和 Agent cache 选择逻辑 |
| Hermes turn/control/delegation 生命周期 | **已有，Gateway 组合验收通过** | Harness 与 Go 跨进程测试覆盖 turn、cancel、steer、delegation、lease/fence 和 recovery |
| Gateway 直接接 chatrtmgr | **已完成，G-01 至 G-06** | chatrtmgr target、UDS process starter、Forwarder、Compose、Helm 和本地入口均已切换为 Gateway；不替换 `HermesHostAdapter` |
| chatsvc 移除 | **生产路径已完成** | Gateway 是唯一实时入口；旧 chatsvc 仅保留隔离回退和历史读取兼容代码 |
| baseline 36 + Hermes 过程事件原名透传 | **E-07 已完成** | canonical envelope 原样穿过 Gateway、chatrtmgr、lobby 和 web2；固定 chunk 不再作为生产事实源 |
| 完整 envelope、sequence、replay | **E-07 已完成并有组合证据** | Gateway relay 保留原始 envelope；replay 只重放 canonical tail，`done` 是控制帧 |

## 迁移顺序

详细的可执行任务和依赖顺序见：

- [Harness Gateway 替代 chatsvc 执行方案](../plan/harness-gateway-replacement-plan.md)：先完成 Gateway 接入、兼容传输、组合验收和 chatsvc 移除。
- [Harness 事件统一设计与执行计划](../plan/event-unification-design-and-plan.md)：Gateway 替代完成后，推进 baseline 36 个事件和 Hermes 过程事件扩展的 canonical envelope、原名透传和下游统一，并打通前端过程视图。

顺序摘要：

1. **Gateway 接入 chatrtmgr**：让 Harness Gateway 直接承担当前 chatsvc 的用户亲和进程入口、UDS readiness、Host Protocol 命令和 lease/session 承接。
2. **保留 session/Agent 分层**：不把 `agent_id` 提升为进程键；先复用 Harness 已有的 session registry、runtime 和 Agent cache 机制。
3. **兼容传输验收**：先保持现有 stream chunk 行为，证明新拓扑没有用户可见回归。
4. **删除 chatsvc**：只有新 Gateway 完成生产路径且旧 chatsvc 没有消费者后，才移除 chatsvc 的启动和适配代码。
5. **最后统一事件**：在 Gateway 计划完成后，单独推进事件原名、envelope、sequence、replay 和下游消费统一。

## 不采用的边界

- 不让一个全局 Harness 进程承载所有用户；这会扩大故障范围并削弱用户级资源控制。
- 不让多个 session 共享同一个可变 Agent 对象；session 历史、上下文和并发边界必须独立。
- 不把 NetworkClaw 的 lease、affinity、takeover 和跨节点控制交给 vendor Hermes。
- 不在 integration 仓库实现第二套 Gateway、Agent loop 或 Hermes runtime。
