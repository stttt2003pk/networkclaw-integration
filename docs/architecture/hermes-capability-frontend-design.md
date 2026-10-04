# Hermes Capability 前端重做设计

## 1. 状态与目标

**状态：前端设计稿，暂不包含实现代码。**

本文定义 NetworkClaw Web 如何管理和调用新的 Agent、Skill、Toolset、Atomic
Tool 和 Session Snapshot。设计依据包括：

- [Hermes Agent 对齐设计](hermes-agent-alignment.md)
- [Hermes Skill 对齐设计](hermes-skill-alignment.md)
- [Hermes Tool 对齐设计](hermes-tool-alignment.md)
- [Capability Snapshot contract](../contracts/capability-snapshot-v1.md)
- Hermes 官方桌面端 Capabilities 源码：
  `~/.hermes/hermes-agent/apps/desktop/src/app/capabilities/`
- Hermes 官方 Bot 配置源码：
  `~/.hermes/hermes-agent/apps/desktop/src/plugins/hermes-bots/profile-config.tsx`

目标是形成以下闭环：

```text
Capability Catalog
    -> Agent Profile / Draft Revision
    -> Published Agent Revision
    -> Session Agent/Capability/Skill Snapshot
    -> Hermes Runtime Activity
```

旧的 `tools_json`、`skills_json` 和扁平 Agent 编辑器只作为一次性迁移输入，不能
继续作为新运行时事实源。

## 2. 设计原则

### 2.1 配置事实和运行时事实分离

管理页面编辑的是 Agent draft/revision；会话页面读取创建时冻结的 snapshot；运行态
页面读取 Gateway/Hermes 事件。前端不能把当前 Catalog 状态推断为已运行 session 的
权限。

```text
Catalog availability
  ∩ Agent revision grant
  ∩ Session snapshot
  ∩ Host grant
  ∩ Current turn allowed_tools
```

### 2.2 Toolset 是选择入口，Atomic Tool 是授权事实

Toolset 用于批量配置和分组展示，最终授权必须显示原子工具。Skill 是带版本、依赖和
加载模式的能力包，不能显示成 Tool，也不能绕过 Host grant。

### 2.3 发布产生不可变身份

发布会生成 `revision_hash` 和有效能力快照 hash，只影响新 Session。运行中的 Session
继续使用原有 snapshot；权限变化必须通过新的 Session 或显式 replacement 生效。

### 2.4 复用 Hermes 的交互模式，不复制其 profile 语义

Hermes 官方 UI 的以下模式直接复用：

- Capabilities 分页：Skills、Toolsets、Connectors、Plugins。
- master-detail：左侧列表/搜索，右侧详情和配置。
- profile scope selector：明确正在配置哪个 profile。
- Bot 编辑器内嵌 Capabilities：在 Agent 编辑上下文中查看同一能力目录。
- 工具调用作为会话消息流中的独立活动项。

NetworkClaw 将 Hermes 的“profile 开关”改成“Agent draft binding”，发布后由
Session Snapshot 固化。

## 3. 信息架构与路由

```text
/capabilities
  ?tab=skills
  ?tab=toolsets
  ?tab=tools
  ?tab=connectors

/agents
/agents/:profileId
/agents/:profileId/revisions/:revisionId

/sessions/new
/sessions/:sessionId
```

### 3.1 Capability Catalog

Catalog 是只描述能力来源和可用性的公共目录。它不显示 Agent 私有授权，也不直接
创建 Session。

#### Skills Tab

列表字段：

- `skill_id`、名称和描述
- version/revision
- source
- release status
- trust status
- platform status
- dependency count
- 可用于新 revision 的状态

详情字段：

- `skill_id@version`
- `content_hash`
- release/trust/platform 结果
- required toolsets
- required atomic tools
- config requirements
- dependency resolution result

操作：查看 revision、查看依赖、进入 Agent binding。Skill 正文不是 Lobby 的事实
字段；需要查看正文时由 Harness 的受控 detail API 提供。

#### Toolsets Tab

采用 Hermes 的展开方式：

```text
coding
  ├── read_file
  ├── search_files
  └── patch
```

列表字段：toolset 名称、revision、source、availability、原子工具数量、使用次数。

详情字段：schema hash、required capabilities、原子工具列表、unavailable/retired
原因。

#### Atomic Tools Tab

用于审计和细粒度授权，字段包括工具名、所属 toolset、revision、schema hash、source、
grant policy、required capabilities 和 availability。

### 3.2 Agent Profile 页面

列表显示：

- profile ID 和 display name
- published revision
- draft revision
- revision hash
- 最近发布时间
- 使用中的 Session 数量
- 是否存在未发布修改

操作：创建 draft、复制 revision、查看 diff、发布、停用、查看关联 Session。

## 4. Agent Revision 编辑器

编辑器分为四步，保存对象始终是 draft revision：

```text
Identity & Runtime
    -> Tool Surface
    -> Skill Bindings
    -> Review & Publish
```

### 4.1 Identity & Runtime

字段：

- display name、description、system prompt
- model/provider
- permission mode
- turn budget
- delegation policy
- child budget
- max delegation depth

system prompt 只保存 Agent 行为约束，不把 Skill 正文复制进去。

### 4.2 Tool Surface

页面同时显示：

```text
Requested Toolsets
Final Atomic Grant
```

工具状态必须区分：

| 状态 | 含义 |
|---|---|
| `allowed` | 已包含在 Agent revision grant 中 |
| `not_granted` | Catalog 存在，但 Agent 未授权 |
| `not_loaded` | Agent 请求，但当前 runtime 未加载 |
| `unavailable` | 环境检查或 provider 能力不可用 |
| `turn_disabled` | 本轮 allowed_tools 被进一步收窄 |
| `retired` | 引用的 tool revision 已退役 |

草稿保存至少包含：

```json
{
  "requested_toolsets": [{"toolset_id": "coding", "revision": 1}],
  "allowed_tools": [{"tool_id": "read_file", "revision": 1}],
  "denied_tools": []
}
```

前端不得自行把 toolset 名称当作最终 `allowed_tools` 提交结果；服务端负责展开和
校验。

### 4.3 Skill Bindings

绑定字段：

- `skill_id`
- skill revision/version
- mode
- config reference
- dependency result

可保存模式固定为：

```text
auto_load | explicit | disabled
```

行为说明：

- `auto_load`：Session 创建时由 Harness 以受控 prompt block 注入。
- `explicit`：通过 Hermes 原生 `skill_view`/`skill_manage` 路径使用，仍受 tool grant
  限制。
- `disabled`：不注入、不提供显式调用建议，但保留依赖失败信息供排查。

绑定行必须同时显示 required toolsets/tools、缺失 grant、不可用、未信任、未发布、
过期和平台限制原因。

### 4.4 Review & Publish

发布前显示：

- revision diff
- requested toolsets
- final allowed/denied tools
- Skill bindings 和 mode
- dependency failures
- model/provider
- delegation policy
- revision hash/effective snapshot hash
- “只影响新 Session”提示

草稿可以存在依赖错误；发布必须通过服务端依赖校验。发布失败不能产生半套 revision。

## 5. Session 创建和运行态

### 5.1 创建 Session

流程：

```text
选择 Agent Profile
    -> 选择 Published Revision
    -> 预览有效能力
    -> 创建 Session
```

请求使用：

```json
{
  "agent_profile_id": "incident-investigator",
  "agent_revision_id": "rev-4"
}
```

创建前预览显示 Agent revision hash、model/provider、allowed tools 数量、Skill mode
统计、依赖警告和 delegation budget。

### 5.2 Session 顶部状态

```text
Agent: Incident Investigator
Revision: rev-4
Model: gpt-6-sol
Tools: 12 granted
Skills: 2 auto-load / 1 explicit
Snapshot: sha256:...
```

点击后打开 Runtime Capability Drawer。

### 5.3 Runtime Capability Drawer

分为 Tools、Skills、Snapshot 三个面板：

**Tools**：loaded、granted、unavailable、current-turn disabled、deny reason。

**Skills**：auto-loaded、explicit available、disabled、dependency failure、stale
revision。

**Snapshot**：Agent revision、Agent/Capability/Skill snapshot hash、model/provider、
创建时间、replacement 状态。

Drawer 只读。修改权限必须进入新的 draft/revision 或创建 Session replacement。

## 6. Tool 与 Skill 活动展示

前端消费现有 canonical event，不另造运行时协议。至少支持：

- `tool.started`
- `tool.completed`
- `tool.failed`
- `tool.denied`
- Skill loaded/rejected 事件
- delegation child created/resolved 事件

每个 Tool invocation 显示：

- atomic tool name 和 toolset
- invocation ID
- started/completed 时间
- success/failed/denied
- failure/deny reason
- session snapshot hash
- turn ID
- parent/child lineage

示例：

```text
skill_view
status: denied
reason: skill_tool_not_authorized
required grant: skill_view
```

## 7. 前端 API 约定

NetworkClaw Web 需要按领域拆分 API client：

```text
web/src/api/
  capabilityCatalog.ts
  skillCatalog.ts
  agents.ts
  sessions.ts
  snapshots.ts
```

核心类型：

```text
AgentProfile
AgentRevision
AgentToolGrant
AgentSkillBinding
CapabilityCatalogEntry
SessionAgentSnapshot
SessionCapabilitySnapshot
SessionSkillSnapshot
EffectivePermission
ToolInvocation
```

服务端响应需明确区分：

```text
catalog state
revision configuration
effective published projection
session snapshot
runtime activity
```

前端不得从多个旧接口自行拼出 snapshot，也不得在浏览器端重新计算授权结果。

## 8. 组件边界

建议结构：

```text
web/src/components/capabilities/
  CapabilityScopeSelector.tsx
  CapabilityStatusBadge.tsx
  ToolsetRow.tsx
  ToolDetailPane.tsx
  SkillRow.tsx
  SkillDetailPane.tsx
  DependencyResult.tsx
  EffectivePermissionTable.tsx

web/src/components/agents/
  AgentProfileList.tsx
  AgentRevisionWorkspace.tsx
  AgentRuntimeForm.tsx
  AgentToolSurface.tsx
  AgentSkillBindings.tsx
  AgentRevisionReview.tsx
  RevisionDiff.tsx

web/src/components/sessions/
  AgentRevisionPicker.tsx
  SessionSnapshotSummary.tsx
  RuntimeCapabilityDrawer.tsx
  ToolInvocationRow.tsx
```

边界规则：

- Catalog 组件只负责目录查询和详情。
- Agent 组件负责 draft/revision 编辑与发布。
- Session 组件只选择 published revision 和读取 snapshot。
- Runtime drawer 只读，不修改授权。
- Activity 组件只消费 canonical events。

## 9. 开发阶段

### F-01 类型和 API client

完成新模型 TypeScript 类型、查询 key、错误映射和 snapshot 响应解析；不再增加旧
`tools_json`/`skills_json` 写接口。

### F-02 Capability Catalog

先实现 Skills、Toolsets、Atomic Tools 的只读 master-detail 页面，再接 scope selector
和依赖详情。

### F-03 Agent Revision Editor

实现四步编辑器、draft 保存、toolset 展开、atomic deny、Skill mode、依赖提示、diff
和 publish。

### F-04 Session Revision Picker

创建 Session 时选择 published revision，接收三类 snapshot 和 hash，并在 session
页面显示 revision 与 snapshot 差异。

### F-05 Runtime Activity

接入 tool/skill/delegation canonical events，完成 Tool invocation 行和 Runtime
Capability Drawer。

### F-06 旧页面收口

新页面稳定后，`web2` 的旧 `skills_json`/`tools_json` 编辑改为只读兼容或移除写入口。
旧数据只允许通过一次性迁移进入新模型。

### F-07 验收与交付

完成浏览器验收、TypeScript 构建、跨仓 contract 验证和文档进度记录。

## 10. 验收矩阵

### 管理端

- 可以创建 profile 和 draft revision。
- 可以选择 toolset 并看到原子工具展开。
- 可以单独 deny atomic tool。
- 可以绑定 Skill revision 和三种 mode。
- 可以看到依赖失败、trust/release/platform 失败原因。
- 未通过依赖校验的 revision 不能发布。
- 发布得到稳定 revision hash。

### Session

- Session 必须绑定 published revision。
- 创建结果返回 Agent、Capability、Skill 三类 snapshot 和 hash。
- resume 保持原 snapshot。
- 发布新 revision 不改变旧 Session。
- 页面不把 Catalog 当前状态误认为运行时状态。

### Runtime

- 能区分 unavailable、not granted、not loaded、turn disabled。
- 能显示 auto-load、explicit、disabled Skill 状态。
- Tool invocation 显示 invocation ID、状态和失败原因。
- child session 保留 parent/child lineage。

建议门禁：

```bash
cd ../NetworkClaw/web
npm run typecheck
npm run build
npm test -- --run

cd ../networkclaw-integration
make validate-contracts
make test
```

## 11. 非目标和迁移限制

- 不在前端实现 Agent loop、tool resolver、Skill dependency resolver 或授权计算。
- 不把 Skill 正文复制进 Lobby Agent revision。
- 不在运行中的 Session 上直接修改权限。
- 不让 `web2` 继续提交 `skills_json`、`tools_json` 或旧 `/catalog/agents` 写请求。
- 不复制或修改 `networkclaw-harness/vendor/hermes`。

## 12. 相关实现文件

NetworkClaw 当前入口：

- `NetworkClaw/web/src/pages/Agents.tsx`
- `NetworkClaw/web/src/pages/Skills.tsx`
- `NetworkClaw/web/src/api/agents.ts`
- `NetworkClaw/web/src/api/skillCatalog.ts`
- `NetworkClaw/web/src/api/chat.ts`
- `NetworkClaw/web2/src/pages/agent-skill-tool/AgentsSection.tsx`

Hermes 官方参考入口：

- `~/.hermes/hermes-agent/apps/desktop/src/app/capabilities/index.tsx`
- `~/.hermes/hermes-agent/apps/desktop/src/app/capabilities/scope-selector.tsx`
- `~/.hermes/hermes-agent/apps/desktop/src/app/capabilities/skills/skills-tab.tsx`
- `~/.hermes/hermes-agent/apps/desktop/src/app/capabilities/toolsets/toolsets-tab.tsx`
- `~/.hermes/hermes-agent/apps/desktop/src/plugins/hermes-bots/profile-config.tsx`
