# Hermes Agent 与 NetworkClaw Agent 重新建模设计

## 1. 状态与目标

**状态：设计稿，准备替换现有 Agent 目录和会话配置模型。**

本文定义 Lobby、Harness Gateway 和 Hermes runtime 之间的 Agent 边界。旧的
`CatalogAgent`、`AgentDefinition`、`skills_json`、`tools_json` 和 chatsvc Agent
结构不再作为新模型的兼容核心；迁移时可以读取旧数据生成一次性 revision，之后以新模型为准。

本文只定义 Agent。工具和 Skill 的详细目录、版本、依赖和加载规则分别见：

- [Hermes 工具对齐设计](hermes-tool-alignment.md)
- [Hermes Skill 与 NetworkClaw Skill 重新建模设计](hermes-skill-alignment.md)

## 2. 核心判断

Hermes 的 Agent 有三个不同层次，不能在 Lobby 中建成一个可变对象：

```text
Agent Profile / Revision       Lobby 持久化的用户配置
        |
        v
Session Agent Snapshot         会话创建时冻结的配置快照
        |
        v
Hermes Agent Runtime Instance  Harness 内部的可变执行对象
```

Lobby 负责 Agent 的目录、编辑、发布和会话绑定；Harness Gateway 负责把 revision
投影为 Hermes Agent 初始化参数；Hermes runtime 继续负责 turn、工具调用、上下文、
取消、steer 和 delegation。

## 3. 生命周期和所有权

```text
user_id
  -> 一个 Harness Gateway 进程
      -> 多个 session_id
          -> 一个冻结的 Agent revision snapshot
              -> 一个独立 Hermes Agent/runtime instance
```

| 对象 | 所有者 | 可变性 | 作用 |
|---|---|---:|---|
| `AgentProfile` | Lobby | 可编辑 | 前端可见的 Agent 逻辑配置 |
| `AgentRevision` | Lobby | 发布后不可变 | 可审计、可复现的配置版本 |
| `SessionAgentSnapshot` | Lobby + Harness | session 内不可变 | Agent 创建时的完整输入 |
| Hermes Agent | Harness/Hermes | session 内可变 | 实际执行对象和缓存 |
| Agent run | Hermes runtime | turn 内可变 | 一次 turn 或 delegation 子任务 |

`agent_id` 是 Profile 的稳定身份，不是进程亲和键。`user_id -> Gateway` 和
`session_id -> _HermesSession` 的边界沿用
[Harness Gateway 亲和设计](harness-gateway-affinity.md)。

## 4. 新的 Agent 数据模型

### 4.1 Agent Profile

Agent Profile 是可编辑的逻辑定义，不直接存放 runtime 对象、工具 handler 或完整
Skill 内容。

```json
{
  "agent_id": "incident-investigator",
  "display_name": "Incident Investigator",
  "description": "Correlates one incident across metrics, logs and traces.",
  "when_to_use": "Use for an incident with multiple evidence sources.",
  "status": "published",
  "default_revision": 4
}
```

建议字段：

| 字段 | 语义 |
|---|---|
| `agent_id` | 稳定 ASCII 标识，唯一 |
| `display_name` | 面向用户的名称 |
| `description` | Agent 能力简介 |
| `when_to_use` | 协调 Agent 选择该 Agent 时使用的提示 |
| `status` | `draft`、`published`、`disabled`、`archived` |
| `default_revision` | 新 session 默认使用的 revision |
| `created_by` / `updated_by` | 管理审计信息 |

### 4.2 Agent Revision

Revision 是真正参与 session 创建的配置。发布后不可变，任何编辑都产生新 revision。

```json
{
  "agent_id": "incident-investigator",
  "revision": 4,
  "system_prompt": "You investigate one incident...",
  "model_ref": "catalog-model:hermescc/gpt-5.6-sol",
  "requested_toolsets": ["networkclaw", "coding"],
  "allowed_tools": [
    "read_file", "search_files", "web_search", "query_promql", "query_logql"
  ],
  "denied_tools": ["terminal"],
  "enabled_skills": ["incident-investigation"],
  "auto_load_skills": ["incident-investigation"],
  "permission_mode": "read-only",
  "max_turns": 32,
  "delegation": {
    "enabled": true,
    "allowed_agent_ids": ["specialist-sre", "specialist-network"],
    "max_children": 4
  },
  "config": {},
  "revision_hash": "sha256:..."
}
```

字段规则：

| 字段 | 规则 |
|---|---|
| `system_prompt` | persona 和行为约束；不放 Skill 内容 |
| `model_ref` | 引用 Lobby model catalog；Gateway 再解析为 provider route |
| `requested_toolsets` | Hermes `enabled_toolsets` 的批量输入 |
| `allowed_tools` | Hermes 原子工具名的 Agent 级上限 |
| `denied_tools` | 原子 deny，优先级高于 `allowed_tools`；不替代 `disabled_toolsets` |
| `enabled_skills` | API/UI 对 Agent 可用 Skill 的投影；数据库使用 `AgentSkillBinding` |
| `auto_load_skills` | API/UI 对 auto-load binding 的投影；数据库使用 `AgentSkillBinding.mode` |
| `permission_mode` | NetworkClaw 的副作用策略，不下沉为 Hermes tool handler 逻辑 |
| `max_turns` | Agent 级执行上限，session grant 可以进一步收窄 |
| `delegation` | Hermes delegation 的 NetworkClaw 业务上限和可选 Agent 集合 |
| `config` | Agent/Profile 级结构化配置；敏感值只引用 secret，不保存明文 |
| `revision_hash` | 所有参与执行的配置内容的稳定 hash |

不保存以下内容：

- Hermes Agent 实例或 transcript；
- Python handler、provider client 或 workspace 路径；
- Skill 的完整正文；
- 运行时生成的 `valid_tool_names`；
- lease、execution epoch 和 process ID。

### 4.3 SessionAgentSnapshot

创建 session 时，Lobby 将 Agent revision、Tool catalog 和 Skill catalog 解析为冻结快照。

```json
{
  "session_id": "session-123",
  "agent_id": "incident-investigator",
  "agent_revision": 4,
  "agent_revision_hash": "sha256:...",
  "requested_toolsets": ["networkclaw", "coding"],
  "loaded_toolset_hash": "sha256:...",
  "allowed_tools": ["read_file", "search_files", "web_search"],
  "skills": [
    {
      "skill_id": "incident-investigation",
      "version": "1.2.0",
      "content_hash": "sha256:...",
      "mode": "auto_load"
    }
  ],
  "model_route": {
    "provider_id": "hermescc",
    "model_id": "gpt-5.6-sol",
    "config_ref": "env:openai"
  }
}
```

快照是恢复、审计和故障接管的依据。Profile 后续发布新 revision 不改变已存在的
session；要使用新配置必须创建新 session 或显式执行受控 session replacement。

## 5. 配置解析顺序

### 5.1 Tool surface

```text
AgentRevision.requested_toolsets
    -> Hermes resolve_toolset / registry
    -> check_fn 和运行环境过滤
    -> Agent.valid_tool_names
    -> AgentRevision.allowed_tools / denied_tools
    -> Host grant.allowed_tools
    -> 本轮 allowed_tools
```

最终本轮集合为：

```text
loaded_schema
  ∩ agent_allowed
  - agent_denied
  ∩ host_grant
  ∩ turn_allowed
```

`allowed_tools` 不能加载新的 toolset。`requested_toolsets` 为空、未知或解析为空时，
Gateway 必须返回结构化错误，不能默默使用 Hermes 的“全部工具”默认语义。

### 5.2 Skill surface

```text
AgentRevision.enabled_skills
    -> Skill catalog / version / trust / dependency validation
    -> available skills

AgentRevision.auto_load_skills
    -> Skill content load
    -> Hermes system prompt/context
```

Skill 不进入 `allowed_tools`。Skill 依赖的 toolset 和原子工具必须在 Agent revision
和 Host grant 中同时满足，具体规则见 Skill 设计文档。

## 6. Harness Gateway 投影

Gateway 创建 Hermes Agent 时只传 Hermes 已支持的参数，并保留 NetworkClaw 的
session 约束：

```python
AIAgent(
    model=model_id,
    provider=provider_id,
    session_id=session_id,
    session_db=session_db,
    cwd=workspace,
    enabled_toolsets=requested_toolsets,
    disabled_toolsets=disabled_toolsets,
    max_iterations=bounded_max_turns,
    **callbacks,
)
```

随后 Gateway 将 Agent revision 的原子权限和 Host grant 投影为 session/turn 工具范围。
Gateway 不实现第二个 Agent loop、工具选择器或 Skill 解释器。

当前 Harness 已有的机制继续沿用：

- `HermesHostAdapter` 管理 `_HermesSession`；
- Agent 按 provider route、profile、预算和 tool signature 缓存/重建；
- Hermes runtime 负责 turn、tool execution、cancel、steer、delegation；
- Host grant、lease、epoch fencing 由 NetworkClaw 控制。

需要新增的输入是完整的 Agent revision/session snapshot，而不是继续增加固定的
`enabled_toolsets` 或旧 JSON 字段。

## 7. Delegation 和子 Agent

Agent Profile 可以声明 delegation 上限，但不创建子 Agent runtime。Hermes `delegate_task`
仍然创建和管理子 Agent。

子 Agent 的能力必须满足：

```text
child toolsets ⊆ parent loaded toolsets
child allowed tools ⊆ parent allowed tools
child skills ⊆ parent enabled skills 或已发布的受允许 Agent Profile
child budget ≤ parent remaining budget
```

Lobby 负责声明可派遣的 Agent Profile 和业务上限；Harness/Hermes 负责执行、继承、
取消和 delegation lineage。

## 8. 前端设计

Agent 编辑页应按用户决策组织，而不是按数据库字段组织：

1. **Identity**：名称、用途、何时使用。
2. **Behavior**：system prompt、关键提醒、默认模型、预算。
3. **Tools**：先选 Hermes toolset，再查看展开的原子工具；允许单工具 deny。
4. **Skills**：选择可用 Skill，单独勾选 auto-load；显示依赖和不可用原因。
5. **Delegation**：是否允许子 Agent、可选 Agent、并发和预算上限。
6. **Review**：显示最终 snapshot、revision、工具 hash、Skill hash 和发布状态。

前端保存的是 draft；只有发布后才产生不可变 revision。正在运行的 session 显示其
revision，不因编辑 draft 而改变。

## 9. 当前完成度

| 能力 | 状态 |
|---|---|
| `user_id -> Harness Gateway` | 已完成 |
| `session_id -> _HermesSession` | 已有并沿用 |
| `agent_id` 从 Lobby 传到 session | 已接线，但旧配置形态仍需替换 |
| Hermes Agent runtime | 已有并沿用 |
| Agent Profile/Revision 新表模型 | 未实现 |
| SessionAgentSnapshot | 未实现 |
| Lobby requested toolsets -> Gateway | 设计完成，实现待接线 |
| Agent skill binding/auto-load | 设计完成，实现待接线 |
| revision 发布和 session 冻结 | 当前 Harness 有 prompt/tool 冻结基础，Lobby revision 尚未实现 |
| 子 Agent Profile 继承约束 | Hermes runtime 有基础约束，Lobby Profile policy 尚未接线 |

## 10. 实施顺序

1. 废弃旧 Agent catalog 数据结构，建立 Profile、Revision、Snapshot 三层模型。
2. 让 Lobby 发布 revision 时解析并校验 toolset、原子工具和 Skill 依赖。
3. 将 session 创建改为保存 `SessionAgentSnapshot`，不再传递 `skills_json/tools_json`。
4. Gateway 使用 snapshot 初始化 Hermes Agent，并把 snapshot hash 纳入 Agent cache route。
5. 接入 Skill catalog 和 auto-load，确保 prompt/schema 在 session 生命周期内稳定。
6. 接入 Agent delegation policy 和子 Agent Profile 选择。
7. 删除 chatsvc 旧 AgentDefinition、旧 JSON 投影和兼容读取路径。

## 11. 依据

- [Harness Gateway 亲和与执行边界](harness-gateway-affinity.md)
- [Hermes 工具对齐设计](hermes-tool-alignment.md)
- [Hermes Skill 与 NetworkClaw Skill 重新建模设计](hermes-skill-alignment.md)
- Harness `vendor/hermes/agent/agent_init.py`
- Harness `vendor/hermes/model_tools.py`
- Harness `src/networkclaw_harness/runtime/hermes_host_adapter.py`
