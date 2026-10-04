# Hermes Skill 与 NetworkClaw Skill 重新建模设计

## 1. 状态与目标

**状态：设计稿，准备替换现有 Skill 目录和 Agent 技能数组模型。**

本文定义 Skill 在 Lobby、Harness Gateway 和 Hermes Agent 之间的边界。旧的
`CatalogSkill`、Agent `skills_json` 和 chatsvc 直接执行 Skill 的结构不再作为新模型
的核心；迁移时只允许生成一次性 release/import 数据。

Skill 不是 Tool 的别名：

```text
Tool  = schema + registry handler + execution result
Skill = instructions + references/templates/assets/scripts + metadata
```

Skill 可以依赖 Tool，但 Skill 不注册 Tool handler，也不能绕过 Host grant。

## 2. Hermes Skill 语义

Hermes 的 Skill 主要由 `SKILL.md` 和可选支持文件组成：

```text
SKILL.md
references/
templates/
assets/
scripts/
```

Hermes 支持三种不同动作：

| 动作 | 作用 |
|---|---|
| discovery | 把 Skill 元数据加入 Agent 的可用 Skill 索引 |
| explicit load | `skill_view` 或 `/skill-name` 将内容加载到当前 turn/context |
| auto-load | 新 Agent 初始化时把 Skill 内容注入 system prompt |

因此“启用 Skill”和“自动加载 Skill”必须是两个字段。

## 3. 新的 Skill 数据模型

### 3.1 Skill Identity

Skill Identity 是稳定的用户可见能力，不包含某个版本的正文：

```json
{
  "skill_id": "systematic-debugging",
  "display_name": "Systematic Debugging",
  "description": "A structured debugging workflow.",
  "category": "software-development",
  "status": "published"
}
```

字段：

| 字段 | 语义 |
|---|---|
| `skill_id` | 稳定 ASCII 标识 |
| `display_name` | 前端名称 |
| `description` | 简介 |
| `category` | 前端分组和搜索标签 |
| `status` | `draft`、`published`、`disabled`、`deprecated` |

### 3.2 `SkillRevision`

`SkillRevision` 对应一个可验证的发布包，不允许 Agent 在运行时修改：

```json
{
  "skill_id": "systematic-debugging",
  "version": "1.0.0",
  "source": "builtin",
  "release_ref": "hermes-skill-pack:v3",
  "content_hash": "sha256:...",
  "manifest_hash": "sha256:...",
  "content_path": "systematic-debugging/SKILL.md",
  "required_toolsets": ["file", "terminal"],
  "required_tools": ["read_file", "search_files"],
  "fallback_for_toolsets": [],
  "fallback_for_tools": [],
  "platforms": ["linux"],
  "session_platforms": ["gateway"],
  "config_schema": {},
  "trust_state": "trusted",
  "release_status": "available"
}
```

重要字段：

| 字段 | 规则 |
|---|---|
| `version` | Skill 发布版本，不随 session 修改 |
| `content_hash` | `SKILL.md` 正文 hash；支持文件也应纳入 manifest hash |
| `release_ref` | Harness 可获取的只读发布包引用 |
| `required_toolsets` | Hermes Skill frontmatter 的 toolset 依赖 |
| `required_tools` | Hermes Skill frontmatter 的原子工具依赖 |
| `fallback_for_*` | 依赖主能力存在时隐藏该 Skill 的条件 |
| `platforms` | Hermes 主机平台条件，例如 `linux`、`darwin` |
| `session_platforms` | Hermes gateway/session 平台条件，例如 `gateway` |
| `config_schema` | `metadata.hermes.config` 的结构化配置声明 |
| `trust_state` | `trusted`、`quarantined`、`unknown` |
| `release_status` | `available`、`unavailable`、`revoked` |

Skill 内容不存入 Agent 表，也不以任意用户提交的 Markdown 直接覆盖运行时目录。

### 3.3 AgentSkillBinding

Agent 与 Skill 是多对多关系，绑定必须引用明确的 revision：

```json
{
  "agent_id": "incident-investigator",
  "agent_revision": 4,
  "skill_id": "systematic-debugging",
  "skill_version": "1.0.0",
  "mode": "available",
  "config": {}
}
```

`mode` 只允许：

| mode | 含义 |
|---|---|
| `available` | Skill 可被发现和显式加载 |
| `auto_load` | 新 session 自动加载到 Hermes prompt |
| `disabled` | 该 Agent 不可使用该 Skill |

同一个 Agent revision 中，同一 Skill 只能有一个有效 binding。`auto_load` 是
`available` 的加强形式，不能绕过依赖和信任检查。

## 4. Skill 依赖与工具对齐

Skill 的依赖必须引用 Hermes 原名：

```text
required_toolsets = Hermes toolset names
required_tools     = Hermes atomic tool names
```

校验顺序：

```text
Skill required_toolsets
    ⊆ Agent requested_toolsets

Skill required_tools
    ⊆ Agent loaded tool schemas
    ∩ Agent allowed_tools
    ∩ Host grant.allowed_tools
```

依赖不满足时，Gateway 必须区分：

```text
skill_not_found
skill_not_published
skill_not_trusted
skill_toolset_not_loaded
skill_tool_not_authorized
skill_config_missing
```

不能把缺少依赖的 Skill 静默隐藏后继续创建一个语义不完整的 Agent；除非 Profile
明确把该 Skill 标记为 optional，并在 snapshot 中记录 omitted reason。

## 5. Skill 加载生命周期

### 5.1 Catalog 到 session

```text
Lobby AgentRevision
    -> AgentSkillBinding
    -> SkillCatalog revision lookup
    -> trust/status/dependency/config validation
    -> SessionSkillSnapshot
    -> Harness Gateway
    -> Hermes prompt builder / skill discovery
```

### 5.2 SessionSkillSnapshot

```json
{
  "session_id": "session-123",
  "skills": [
    {
      "skill_id": "systematic-debugging",
      "version": "1.0.0",
      "content_hash": "sha256:...",
      "mode": "auto_load",
      "config_hash": "sha256:..."
    }
  ],
  "skill_set_hash": "sha256:..."
}
```

Gateway 使用 snapshot 加载只读 Skill 内容。session 创建后，Skill 列表、版本和内容
hash 固定；Skill catalog 发布新版本只影响新 session。

正在运行的 session 不允许通过前端 toggle 直接改变 system prompt。需要变更时，创建
新的 session 或执行受控的 session replacement，并生成新的 snapshot。

## 6. Hermes Gateway 接入方式

有两种合法接入方式：

### 静态预加载 Skill

Gateway 在 Agent 创建前读取 snapshot，将选定 Skill 内容交给 Hermes prompt 构建路径。
这种方式不要求模型拥有 `skills_list`、`skill_view`、`skill_manage` 工具。

适用于：

- NetworkClaw 内置 Skill；
- 已审核的 release skill；
- 需要稳定 prompt cache 的生产 Agent。

### Hermes 原生 Skill 工具

当产品希望 Agent 在对话中浏览或显式加载 Skill 时，Gateway 才加载 Hermes `skills`
toolset：

```text
skills_list
skill_view
skill_manage
```

生产默认只建议开放 `skills_list` 和 `skill_view`。`skill_manage` 涉及写入、供应链、
审批和审计，不应因为 Skill catalog 已接入就自动开放。

无论哪种方式，Skill 内容都不能改变：

- `Agent.valid_tool_names`；
- Host grant；
- 每轮 `allowed_tools`；
- lease、epoch fencing 或 workspace ownership。

## 7. Trust、发布和安装边界

第一阶段只支持：

- builtin/release Skill catalog；
- 内容 hash 和 manifest hash；
- 只读加载；
- trusted/quarantined 状态；
- Agent 绑定和依赖校验。

暂不纳入生产 session：

- Agent 通过 `skill_manage` 创建或修改 Skill；
- Skills Hub 在线安装；
- 未信任项目目录自动发现；
- 任意 URL 或 Git 内容直接进入 prompt；
- 运行中的 Skill 热替换。

这些功能需要独立的供应链、审批、沙箱和回滚设计，不能混入 Agent/Tool 基础授权。

## 8. Lobby 前端设计

Skill 页面负责 catalog，不直接替某个 session 执行 Skill：

1. **Catalog**：搜索、分类、来源、版本、状态。
2. **Detail**：用途、内容摘要、依赖 toolset、依赖工具、配置项、信任状态。
3. **Agent binding**：在 Agent 编辑页选择 Skill。
4. **Mode**：`available` 与 `auto_load` 分开显示。
5. **Validation**：显示“缺少 toolset”“缺少工具”“未信任”“缺少配置”等原因。
6. **Revision review**：显示内容 hash、release ref 和会影响哪些 Agent revision。

前端不应该用一个简单的“Skill enabled”布尔值同时表达安装、信任、可用和 auto-load。

## 9. NetworkClaw 当前完成度

| 能力 | 状态 |
|---|---|
| Hermes Skill discovery / `skill_view` / `auto_load` | vendor 已有，Gateway session 输入未接通 |
| NetworkClaw 只读 `SkillCatalog` | 已有基础实现，使用 release root、`skill.json` 和 `SKILL.md` hash |
| Skill session 冻结 | NetworkClaw 基础类已有，尚未绑定 Hermes Agent 创建流程 |
| Skill 内容进入 Hermes prompt | 未完成 |
| Agent-Skill 多对多 revision binding | 未完成 |
| Skill toolset/tool 依赖校验 | Hermes 有 frontmatter 过滤逻辑，Lobby/Gateway 对账未完成 |
| Skill install/manage | 当前关闭，保持关闭 |
| Skill 事件和审计事实 | 只有基础 durable `SKILL loaded` 事实，完整 session snapshot 尚未接线 |
| 旧 `CatalogSkill` / `skills_json` 替换 | 未开始；本设计明确允许直接重建数据库 |

## 10. 数据库重建建议

新模型不再复用旧表的 JSON 数组字段。建议采用独立关系：

```text
skill_catalog
skill_revisions
skill_revision_dependencies
agent_profiles
agent_revisions
agent_skill_bindings
session_skill_snapshots
```

工具关系由 [hermes-tool-alignment.md](hermes-tool-alignment.md) 定义，至少需要能够被
Agent revision 和 Skill dependency 引用：

```text
toolsets
toolset_tools
tools
tool_revisions
```

数据库中保存名称、版本、hash、来源和状态；不保存 Python handler、Hermes Agent 实例、
session transcript 或敏感凭证。

## 11. 实施顺序

1. 建立 Skill catalog/revision 和只读 release manifest。
2. 建立 Agent profile/revision 与 Agent-Skill binding。
3. 建立 Toolset/Tool revision 引用和 Skill 依赖校验。
4. 在 Lobby 创建 `SessionCapabilitySnapshot` / `SessionSkillSnapshot`。
5. Gateway 按 snapshot 创建 Hermes Agent，并接入 auto-load prompt。
6. 接入 `skills_list`/`skill_view` 的受限生产权限。
7. 用新表替换旧 `CatalogSkill`、`skills_json` 和 chatsvc Skill registry。
8. 最后评估 Skills Hub、skill_manage 和项目 Skill trust。

## 12. 依据

- [Hermes Agent 与 NetworkClaw Agent 重新建模设计](hermes-agent-alignment.md)
- [Hermes 工具对齐设计](hermes-tool-alignment.md)
- Harness `vendor/hermes/agent/skill_utils.py`
- Harness `vendor/hermes/agent/skill_commands.py`
- Harness `vendor/hermes/agent/prompt_builder.py`
- Harness `vendor/hermes/tools/skills_tool.py`
- Harness `src/networkclaw_harness/skills/catalog.py`
