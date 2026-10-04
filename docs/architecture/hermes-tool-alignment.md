# NetworkClaw 与 Hermes Harness 工具对齐设计

## 1. 目的

本文定义 NetworkClaw 分布式链路如何对齐 Hermes Harness 的工具模型和过程事件：

```text
NetworkClaw Lobby catalog/grant
        |
        v
Harness Gateway: toolset 加载 -> 展开为原子工具名 -> session grant
        |
        v
Hermes Agent/runtime: schema 选择、参数生成、调用、结果处理、继续 turn、delegation
```

本文只修改 integration 层的设计和验收输入，不复制 Go 或 Harness 业务源码，也不在 NetworkClaw 中重写 Hermes 的 Agent loop 或工具 handler。

## 2. 结论摘要

1. **Hermes Agent 保持原有机制。** Agent 已经根据工具 schema 选择工具、生成参数、执行校验、调用 registry handler、接收结果并继续 turn；并发工具段、取消、steer、上下文生命周期和子 Agent 派遣仍由 Hermes runtime 负责。
2. **Harness Gateway 同时理解 toolset 和原子工具名。** 本阶段以 `coding` 覆盖的 17 个 toolset 为目标：Gateway 按 session 选择并加载 Hermes toolset，Host/Lobby grant 与每轮授权仍只使用具体工具名。`networkclaw` 自有 toolset 单独叠加。
3. **Lobby 以原子工具名作为权限和 catalog 的基本单位。** Toolset/tool group 只用于批量配置、模板和界面组织；下发到 Harness 的最终权限必须是具体工具名集合。
4. **工具 handler 仍归 Hermes vendor/registry。** Gateway 不复制 handler，也不实现第二套工具选择器；它负责加载、授权、投影和传输。
5. **事件统一以现有 canonical catalog 为准。** 当前实时事实源是 `canonical_event` envelope。用户语义名称中有些已经有同义 canonical 事件，有些只是 Hermes callback 或内部事实，并非同名 transport event。文档明确区分“来源已存在”“adapter 已投影”“跨进程已验收”和“同名事件仍未建立”。

## 3. 分层职责

| 层 | 负责什么 | 不负责什么 |
|---|---|---|
| **Hermes Agent** | 根据 schema 选择工具、生成参数、调用工具、处理结果、继续 turn、并发分段、子 Agent 派遣 | NetworkClaw 用户亲和、lease authority、跨节点 takeover、Lobby catalog |
| **Harness Gateway** | 加载 toolset；得到 Hermes 工具定义；将 grant 展开为原子工具名；每轮传入 allowed tools；转发 tool-call、tool-result、progress、plan、delegation 事件 | 重写 Agent loop、复制 vendor handler、决定 Lobby 的业务授权 |
| **NetworkClaw Lobby** | 用原子工具名建立 catalog、授权、审计和 Agent 权限；toolset/group 仅做批量组织；向 Harness 下发最终原子集合 | 解释模型文本、执行工具、持有 Hermes transcript 事实 |

### 3.1 身份和生命周期绑定

```text
user_id
  -> 一个 Harness Gateway 进程
      -> 多个 session_id
          -> 各自独立的 Hermes session/runtime
              -> 各自按 agent_id 选择或重建 Agent
                  -> 各自的 toolset/grant 投影
```

| 绑定关系 | 责任 |
|---|---|
| `user_id -> Harness 进程` | chatrtmgr 负责用户亲和、进程启动、UDS、readiness、故障重启 |
| `session_id -> _HermesSession` | Gateway/`HermesHostAdapter` 负责 workspace、runtime、lease、turn、事件流 |
| `session_id -> Agent cache` | Harness 负责 provider route、profile、tool grant、预算变化时的 session 内 Agent 重建 |
| `agent_id -> Agent 配置` | 选择 model、provider、profile、tool grant、预算；不作为当前进程亲和键 |
| `toolset -> 原子工具集合` | Hermes 原生解析；允许递归 includes 和 registry 合并 |
| `tool name -> handler/schema` | Hermes registry 提供；Lobby 只保存名称和授权元数据 |

同一个 Agent 配置可以服务多个 session，但不能共享可变的 Agent 上下文对象。每个 session 的历史、工具会话、并发边界和 runtime 状态必须独立。

## 4. Hermes 工具选择和执行流程

Hermes 的实际流程是：

1. 目标状态下，Gateway 根据 session 配置解析 toolset，并应用 registry/plugin/MCP 合并、profile 限制、Host grant 和 check function；当前 Gateway 仍固定加载 `networkclaw`、`todo`、`delegation`、`clarify`。
2. Hermes Agent 将最终可用工具的 schema 发送给 provider。
3. 模型返回 tool call；Agent 在 `turn_tool_validation` 中校验名称、参数和当前 allowed tools。
4. `tool_executor` 通过 Hermes registry dispatch handler，并执行前后置 hook、超时和错误归一化。
5. `turn_tool_round` 将工具结果写回上下文，继续当前 turn；需要时启动并发工具段、取消、steer 或 delegation。
6. Hermes callback 经 `HermesHostAdapter` 投影为 canonical event，再由 Gateway/forwarder/Lobby 原样转发。

因此 NetworkClaw 不需要另写“AI 选择工具”和“工具使用”核心逻辑。需要对齐的是：

- Lobby grant 的原子工具名与 Hermes registry 名称一致；
- Gateway 把 toolset 展开结果和原子 grant 交给正确 session；
- 每个工具调用的 invocation、parent item、session、turn 和 delegation lineage 不丢失；
- 前端消费 canonical tool/delegation/plan 事件，而不是从文本或旧 chunk 推断事实。

## 5. Toolset、registry 和可用性边界

### 5.1 三种不同的集合

| 集合 | 含义 | 责任 |
|---|---|---|
| 静态 `TOOLSETS` | `vendor/hermes/toolsets.py` 中的 60 个原名 toolset | Hermes 默认分组和平台 bundle |
| registry 工具 | 启动发现后注册的内置、插件和连接器工具 | Hermes registry 动态加入 schema/handler |
| 当前 session 工具 | toolset 展开后再经过 profile、grant、check function、provider 能力和运行环境过滤的集合 | Gateway 下发给 session 的最终 allowed tools |

静态 toolset 不等于某个 session 最终可用工具。`context_engine`、`bot_room` 等静态 toolset 没有固定原子工具，运行时由 active context engine 或 plugin 提供；MCP 工具也可能在运行期间注册。

### 5.2 工具选择与授权公式

```text
enabled_toolsets / disabled_toolsets
  -> Hermes 展开、合并 registry、做 disabled_toolsets 末端减法
  -> registry check_fn / 动态 schema 过滤
  -> Agent.tools / Agent.valid_tool_names (实际已加载 schema)
  -> 与 session Host grant.allowed_tools 求交集
  -> 与本轮 allowed_tools 求交集
  -> 模型只看到最终 schema；Hermes Agent 选择、校验和执行
```

记 `L` 为 Hermes 实际加载的原子 schema 名称，`H` 为 Host grant 的原子工具集合，`R` 为本轮原子工具集合，则本轮可见集合为 `L ∩ H ∩ R`。本轮未显式提供 `allowed_tools` 时，`R=H`；显式提供空数组时，`R=∅`。在任何阶段都不能把 toolset 名称误当作原子工具名。

`enabled_toolsets=None` 在 Hermes 中表示遍历全部可用 toolset，不适合作为 NetworkClaw 的授权默认值。显式列表表示多个 toolset 的并集；`disabled_toolsets` 最后执行整组减法，可能连其他组共享的工具一起删除。例如 `enabled_toolsets=[coding]` 再 `disabled_toolsets=[search]` 会移除 `web_search`，即使它也属于 `web`。因此单工具 deny 应由 `H/R` 表达，`disabled_toolsets` 只用于整个能力组确实不可用或被禁用的情形。

目标实现需要结构化区分“未授权”“当前不可用”和“校验失败”；错误码应在 Host Protocol 中统一定义，不能直接把这些示例词当作已实现代码。不能静默把被拒绝的工具伪装成模型没有选择。

## 6. Hermes 原生 toolset 与原子工具清单

以下清单来自 Harness 当前 `vendor/hermes/toolsets.py` 的静态 `TOOLSETS`，使用 Hermes 原名。原子工具名称不改成 NetworkClaw 别名。`resolve_toolset(..., include_registry=False)` 的展开结果按字典序列出。

### 6.1 基础和场景 toolset

| Toolset | 静态展开的原子工具 |
|---|---|
| `web` | `web_extract`, `web_search` |
| `search` | `web_search` |
| `x_search` | `x_search` |
| `vision` | `vision_analyze` |
| `video` | `video_analyze` |
| `image_gen` | `image_generate` |
| `video_gen` | `video_generate`, `xai_video_edit`, `xai_video_extend` |
| `computer_use` | `computer_use` |
| `terminal` | `process_manage`, `terminal` |
| `skills` | `skill_manage`, `skill_view`, `skills_list` |
| `browser` | `browser_back`, `browser_cdp`, `browser_click`, `browser_console`, `browser_dialog`, `browser_exec`, `browser_get_images`, `browser_navigate`, `browser_press`, `browser_scroll`, `browser_snapshot`, `browser_type`, `browser_vault_enter_code`, `browser_vault_fill`, `browser_vault_list`, `browser_vault_save_login`, `browser_vault_unlock`, `browser_vision` |
| `cronjob` | `cronjob_manage` |
| `file` | `patch`, `read_file`, `search_files`, `write_file` |
| `tts` | `text_to_speech` |
| `todo` | `todo_list` |
| `memory` | `memory` |
| `context_engine` | 无静态原子工具；运行时由 context engine/plugin 提供 |
| `session_search` | `session_search` |
| `connections` | `manage_connections` |
| `project` | `desktop_project` |
| `bot_room` | 无静态原子工具；运行时由 Group Chat capability 提供 |
| `desktop_ui` | `annotate_preview`, `close_terminal`, `desktop_preview`, `drive_preview`, `focus_pane`, `gui_tour`, `react_to_message`, `read_terminal`, `read_window_below`, `show_tip` |
| `clarify` | `clarify` |
| `code_execution` | `execute_code` |
| `delegation` | `delegate_task` |
| `homeassistant` | `ha_call_service`, `ha_get_state`, `ha_list_entities`, `ha_list_services` |
| `kanban` | `kanban_attach`, `kanban_attach_url`, `kanban_attachments`, `kanban_block`, `kanban_comment`, `kanban_complete`, `kanban_create`, `kanban_heartbeat`, `kanban_link`, `kanban_list`, `kanban_request_changes`, `kanban_request_review`, `kanban_show`, `kanban_unblock` |
| `discord` | `discord` |
| `discord_admin` | `discord_admin` |
| `yuanbao` | `yb_query_group_info`, `yb_query_group_members`, `yb_search_sticker`, `yb_send_dm`, `yb_send_sticker` |
| `feishu_doc` | `feishu_doc_read` |
| `feishu_drive` | `feishu_drive_add_comment`, `feishu_drive_list_comment_replies`, `feishu_drive_list_comments`, `feishu_drive_reply_comment` |
| `spotify` | `spotify_albums`, `spotify_devices`, `spotify_library`, `spotify_playback`, `spotify_playlists`, `spotify_queue`, `spotify_search` |
| `debugging` | `patch`, `process_manage`, `read_file`, `search_files`, `terminal`, `web_extract`, `web_search`, `write_file`（等价于 `includes=[web,file]` 加 terminal） |
| `safe` | `image_generate`, `vision_analyze`, `web_extract`, `web_search`（等价于 `includes=[web,vision,image_gen]`） |
| `coding` | `browser_back`, `browser_cdp`, `browser_click`, `browser_console`, `browser_dialog`, `browser_exec`, `browser_get_images`, `browser_navigate`, `browser_press`, `browser_scroll`, `browser_snapshot`, `browser_type`, `browser_vault_enter_code`, `browser_vault_fill`, `browser_vault_list`, `browser_vault_save_login`, `browser_vault_unlock`, `browser_vision`, `clarify`, `delegate_task`, `execute_code`, `manage_connections`, `memory`, `patch`, `process_manage`, `read_file`, `search_files`, `session_search`, `skill_manage`, `skill_view`, `skills_list`, `terminal`, `todo_list`, `vision_analyze`, `web_extract`, `web_search`, `write_file` |

### 6.2 Hermes 平台和 API bundle

平台 bundle 的原名和展开规则如下。除特别注明外，`hermes-*` bundle 都是 `_HERMES_CORE_TOOLS` 的完整集合；下面的 core 表列出其全部原子工具，因此每个 bundle 的原子集合是可机械确定且不会改名。

**`_HERMES_CORE_TOOLS` 全部原子工具：**

```text
web_search, web_extract, terminal, process_manage, read_file, write_file, patch,
search_files, vision_analyze, image_generate, skills_list, skill_view, skill_manage,
browser_navigate, browser_snapshot, browser_click, browser_type, browser_scroll,
browser_back, browser_press, browser_get_images, browser_vision, browser_console,
browser_cdp, browser_dialog, browser_vault_list, browser_vault_unlock,
browser_vault_fill, browser_vault_save_login, browser_vault_enter_code, browser_exec,
text_to_speech, todo_list, memory, session_search, clarify, execute_code, delegate_task,
cronjob_manage, ha_list_entities, ha_get_state, ha_list_services, ha_call_service,
kanban_show, kanban_list, kanban_complete, kanban_block, kanban_request_review,
kanban_request_changes, kanban_heartbeat, kanban_comment, kanban_create, kanban_link,
kanban_unblock, kanban_attach, kanban_attach_url, kanban_attachments, computer_use,
manage_connections
```

| Toolset | 原子工具展开 |
|---|---|
| `hermes-acp` | `_CODING_TOOLS` 去掉 `clarify`：即 `coding` 集合减去 `clarify` |
| `hermes-api-server` | `_HERMES_CORE_TOOLS` 去掉 `text_to_speech`、`clarify`、`computer_use` 和全部 `kanban_*` |
| `hermes-cli` | 完整 `_HERMES_CORE_TOOLS` |
| `hermes-cron` | 完整 `_HERMES_CORE_TOOLS` |
| `hermes-telegram` | 完整 `_HERMES_CORE_TOOLS` |
| `hermes-discord` | 完整 `_HERMES_CORE_TOOLS` + `discord`, `discord_admin` |
| `hermes-whatsapp` | 完整 `_HERMES_CORE_TOOLS` |
| `hermes-slack` | 完整 `_HERMES_CORE_TOOLS` |
| `hermes-signal` | 完整 `_HERMES_CORE_TOOLS` |
| `hermes-bluebubbles` | 完整 `_HERMES_CORE_TOOLS` |
| `hermes-homeassistant` | 完整 `_HERMES_CORE_TOOLS` |
| `hermes-email` | 完整 `_HERMES_CORE_TOOLS` |
| `hermes-mattermost` | 完整 `_HERMES_CORE_TOOLS` |
| `hermes-matrix` | 完整 `_HERMES_CORE_TOOLS` |
| `hermes-dingtalk` | 完整 `_HERMES_CORE_TOOLS` |
| `hermes-feishu` | 完整 `_HERMES_CORE_TOOLS` + `feishu_doc_read`, `feishu_drive_list_comments`, `feishu_drive_list_comment_replies`, `feishu_drive_reply_comment`, `feishu_drive_add_comment` |
| `hermes-weixin` | 完整 `_HERMES_CORE_TOOLS` |
| `hermes-qqbot` | 完整 `_HERMES_CORE_TOOLS` |
| `hermes-wecom` | 完整 `_HERMES_CORE_TOOLS` |
| `hermes-wecom-callback` | 完整 `_HERMES_CORE_TOOLS` |
| `hermes-yuanbao` | 完整 `_HERMES_CORE_TOOLS` + `yb_query_group_info`, `yb_query_group_members`, `yb_send_dm`, `yb_search_sticker`, `yb_send_sticker` |
| `hermes-sms` | 完整 `_HERMES_CORE_TOOLS` |
| `hermes-webhook` | `web_search`, `web_extract`, `vision_analyze`, `clarify` |
| `hermes-gateway` | 递归 union：`hermes-telegram`, `hermes-discord`, `hermes-whatsapp`, `hermes-slack`, `hermes-signal`, `hermes-bluebubbles`, `hermes-homeassistant`, `hermes-email`, `hermes-sms`, `hermes-mattermost`, `hermes-matrix`, `hermes-dingtalk`, `hermes-feishu`, `hermes-wecom`, `hermes-wecom-callback`, `hermes-weixin`, `hermes-qqbot`, `hermes-webhook`, `hermes-yuanbao` 的去重 union |

`hermes-*` bundle 的重复不是新的工具注册；它们是平台入口对 core 工具和少量平台扩展的命名组合。Lobby 不应把这些重复名称当成不同能力，catalog 中只保留原子工具一份，并记录它属于哪些 toolset。

### 6.3 本阶段范围：`coding` 的覆盖关系

按当前 vendor 的 `resolve_toolset(name, include_registry=False)` 比较，`coding` 静态展开为 37 个原子工具，完整覆盖下面 17 个其他 toolset。覆盖仅表示原子名称集合包含，不表示这些 toolset 的平台姿态、运行环境或 `check_fn` 一定相同。

| 类别 | 被 `coding` 完整覆盖的 Hermes toolset | NetworkClaw 使用方式 |
|---|---|---|
| 基础工具集 | `web`, `search`, `vision`, `terminal`, `skills`, `browser`, `file`, `todo`, `memory`, `session_search`, `connections`, `clarify`, `code_execution`, `delegation` | Lobby 按原子工具授权，并可按这些原名组织批量勾选；Gateway 可选择 `coding` 一次加载候选 schema，或只加载更窄的所选基础组 |
| 组合工具集 | `debugging`, `hermes-acp`, `hermes-webhook` | 仅记录静态覆盖关系；`hermes-acp` 是编辑器入口 bundle，`hermes-webhook` 是外部 webhook 场景 bundle，不因集合被覆盖就把其平台语义带入 NetworkClaw |

`safe` 不在完整覆盖名单：它还需要 `image_generate`。`context_engine`、`bot_room` 没有静态原子工具，不能用空集子集关系判定运行时覆盖。`coding` 不含 Harness 自有的 `networkclaw_workspace_read`；该工具由动态注册的 `networkclaw` toolset 提供，目标 session 需显式加载 `networkclaw` 并给予同名原子 grant。

目标优先采用 `enabled_toolsets=["networkclaw", "coding"]` 作为完整 coding 候选池；需要最小上下文和更窄能力时可以直接加载所选基础组，例如 `enabled_toolsets=["networkclaw", "file", "terminal", "todo"]`。这两种选择都必须与 Lobby 的原子 grant 对账，不能依赖 Hermes 自动选择 `coding` 姿态或 `enabled_toolsets=None`。

### 6.4 动态 toolset 和原子工具

| 来源 | Hermes 机制 | NetworkClaw 处理 |
|---|---|---|
| registry/plugin | `tools.registry` 在发现阶段注册 handler、schema、toolset 和 alias | Gateway 每次生成 session 工具快照时读取 registry；Lobby 只接受带版本/来源的 catalog 条目 |
| MCP | `mcp-*` toolset 和 alias 在连接或 profile 范围内出现 | 不把 MCP 工具硬编码进静态表；以 `server/tool name` 的 Hermes 原名注册和授权 |
| `check_fn` | 检查凭证、平台、二进制、运行时能力，可能使已注册工具不可用 | Gateway 返回结构化不可用原因；Lobby 不把“已注册”误当成“当前可执行” |
| `context_engine` / `bot_room` | toolset 静态存在但原子工具运行时注入 | catalog 只登记 capability/toolset，待运行时发现后再发原子工具 snapshot |

## 7. NetworkClaw 的设计落点

### 7.1 Lobby catalog

本节的 catalog 是新模型，不要求兼容现有 `catalog_tools` 或 Agent `tools_json`。
旧表可以通过一次性导入生成新 revision，之后不再作为运行时事实源。

目标 Lobby catalog 的基本记录应以原子工具为一行，至少包含：

```text
tool_name                 Hermes 原名，例如 terminal
toolset_names             所属 Hermes toolset 名称集合
description/schema_hash   来自 Hermes registry 的定义摘要
source                    builtin / plugin / mcp / runtime
availability              discovered / available / unavailable
grantable                 是否允许作为 Host grant 项
required_capabilities     provider、credential、平台或 workspace 条件
catalog_version           用于 Gateway snapshot 和审计
```

用户或 Agent 配置可以勾选 `toolset_names`，但保存和下发时必须展开成原子集合。以下是**目标协议示例**，其中 `toolset_snapshot` 和 `catalog_version` 尚未成为现行 Host Protocol 字段：

```json
{
  "allowed_tools": ["read_file", "search_files", "terminal"],
  "toolset_snapshot": ["file", "terminal"],
  "catalog_version": "..."
}
```

目标 Gateway 必须拒绝不在 catalog snapshot、Host grant 或 session capability 中的原子工具名。当前 `host_grant.allowed_tools` 和每轮 `allowed_tools` 已有子集校验，但没有 Hermes toolset/catalog 对账。

### 7.1.1 新工具数据库边界

Tool 数据库与 Agent、Skill 数据库一起重建。新模型不把 toolset、原子工具、handler
和某个 Agent 的权限放在同一张表或 JSON 数组中：

```text
toolsets
    -> toolset_tools
        -> tool_revisions
            -> Hermes registry/tool schema identity

agent_revisions
    -> requested_toolsets
    -> allowed_tools / denied_tools

skill_revisions
    -> required_toolsets / required_tools
```

建议的持久化对象：

| 对象 | 持久化内容 | 不持久化 |
|---|---|---|
| `Toolset` | Hermes 原名、描述、来源、状态 | 运行时 handler |
| `ToolsetTool` | toolset 与 tool revision 的关系 | Agent session 权限 |
| `ToolRevision` | 原子名称、schema hash、版本、来源、availability、grant policy | Python callable、provider client |
| `AgentRevision` | requested toolsets、原子 allow/deny、Skill binding | `valid_tool_names` 运行时结果 |
| `SessionCapabilitySnapshot` | 解析后的 toolset hash、原子工具集合、Agent/Skill revision hash | 可变全局配置 |

工具权限的最终来源是 Agent revision、Host grant 和当前 turn 的交集；toolset 只负责
批量加载候选 schema。Lobby 不保存 Hermes handler 的第二份实现，Gateway 也不注册第二套
工具。

旧字段按以下规则废弃：

| 旧字段/模型 | 新模型处理 |
|---|---|
| `CatalogTool` | 导入为 `ToolRevision` |
| `CatalogAgent.ToolsJSON` | 展开为 `AgentRevision.requested_toolsets` 和原子 allow/deny |
| `CatalogAgent.SkillsJSON` | 导入为 `AgentSkillBinding`，由 Skill 文档定义 |
| chatsvc `fullScopeJSON()` | 不再作为 catalog 或授权来源 |
| chatsvc/Go Tool handler | 由 Harness Hermes registry 作为唯一执行来源 |

Agent 和 Skill 的完整 revision/snapshot 关系见：

- [Hermes Agent 重新建模设计](hermes-agent-alignment.md)
- [Hermes Skill 重新建模设计](hermes-skill-alignment.md)

### 7.2 Harness Gateway

目标 Gateway 需要保留两层输入：

- `requested_toolsets`: 便于 Agent/profile 批量加载 Hermes toolset；
- `allowed_tools`: 已经展开的最终原子集合，便于每轮授权和审计。

Gateway 不注册第二份 handler。目标是调用 Harness 已有的 Hermes registry/`resolve_toolset`，将最终集合传入 session 的 Agent 初始化和每轮 tool policy。当前 `HermesHostAdapter._ensure_agent` 固定传入 `enabled_toolsets=["networkclaw", "todo", "delegation", "clarify"]`；`allowed_tools` 只过滤该 Agent 已加载的 schema，不会自动加载其他 Hermes toolset。因此 Lobby 即使传来 `terminal`，当前 Agent 也不会因此获得 `terminal` schema。当前 Agent cache key 已含 tool signature/grant signature，grant 变化会重建受影响 session 的 Agent；动态 toolset 加载仍待实现。

目标 Gateway 的 session 配置应至少有以下两个不同字段：

```json
{
  "requested_toolsets": ["networkclaw", "coding"],
  "allowed_tools": [
    "networkclaw_workspace_read", "read_file", "search_files", "terminal", "todo_list", "delegate_task"
  ]
}
```

处理顺序必须是：

1. 解析 `requested_toolsets`，得到 `L`，并在 Agent 创建时传为 `enabled_toolsets`；
2. 校验 `allowed_tools ⊆ L`，否则报告 `allowed_tools_not_loaded`，不要静默过滤；
3. 将 Host grant 保存到 `_HermesSession`，把其 toolset/原子签名纳入 Agent cache route；
4. 每轮接收 `allowed_tools` 时，再验证它是 Host grant 的子集，然后由 Hermes 现有 runtime 过滤 Agent schema；
5. Agent 重建后重新报告实际 `valid_tool_names`，供 Gateway readiness/debug 和 Lobby 诊断使用。

这使“toolset 没加载”和“工具未被本轮授权”成为两个可区分的故障：前者是 session/Agent 配置问题，后者是 turn 授权问题。

### 7.3 Hermes Agent

Hermes Agent 这一层沿用 vendor 机制，不新增 NetworkClaw 选择器：

| 输入 | Hermes 现有职责 | NetworkClaw 约束 |
|---|---|---|
| `enabled_toolsets` | `model_tools.get_tool_definitions` 展开 toolset、includes、registry，并生成 `agent.tools` 与 `agent.valid_tool_names` | Gateway 只传已通过 Lobby/catalog 校验的 toolset 名称 |
| `disabled_toolsets` | 最后从工具集合中删除整组工具 | 只用于能力组级别禁用；单工具权限不要借此表达 |
| `allowed_tools` | 当前 turn 暂时过滤已加载 schema；`turn_tool_validation` 拒绝不在 `valid_tool_names` 的调用 | Gateway 保证它是 Host grant 和已加载集合的子集 |
| provider tool call | Hermes 选择工具、生成参数、校验、执行和继续 turn | 不从 Lobby 传入“应该调用哪个工具”的指令 |
| `delegate_task` | Hermes 管理子 Agent 的执行和工具继承约束 | child toolset 不能扩大 parent enabled toolsets |

对于本阶段的 coding agent，推荐的 Agent 初始化输入是：

```text
enabled_toolsets = ["networkclaw", "coding"]
disabled_toolsets = []
agent.valid_tool_names = coding 的 37 个原子工具 + networkclaw_workspace_read
```

随后每轮由 Lobby/Host 传入更小的 `allowed_tools`。如果某个用户只需要文件和终端能力，可以初始化为 `networkclaw`, `file`, `terminal`, `todo`，减少 schema 上下文；不需要为了使用 `read_file` 再额外加载整个 `coding`。

### 7.4 Agent 和前端过程视图

Agent 继续选择和执行工具。为了让前端看到真实过程，Gateway/adapter 必须保留以下关联字段：

```text
session_id, run_id, turn_id, event_id, sequence,
invocation_id, parent_item_id, tool_name,
allocation_id, parent_session_id, child_session_id
```

前端使用 `tool.generating`/`tool.started`/`tool.progress`/`tool.completed`、`plan.updated`、`delegation.*` 和 `subagent.*` 构建过程视图；不从 assistant 文本猜测“正在调用什么工具”或“是否派遣了子 Agent”。

当前 `tool.generating` callback 只给工具名，未给稳定 `invocation_id`；前端只能把它显示为暂态提示，直到 `tool.started` 才创建可关联的调用节点。`tool.progress` 是否出现取决于具体工具的 callback，不能作为每次调用都必有的状态。

## 8. 用户语义事件核对

### 8.1 现有 canonical 事实

现有 `docs/contracts/event-catalog-v1.md` 和 E-07 证据已确认实时链路使用 canonical envelope：

```text
Harness Gateway -> chatrtmgr -> lobby -> WebSocket -> web2
```

已在 catalog/adapter/组合验收中出现的相关 canonical 事件包括：

```text
turn.started, turn.completed, turn.failed, turn.cancelled,
assistant.delta, plan.updated,
tool.generating, tool.started, tool.progress, tool.completed,
subagent.start, subagent.complete, subagent.text, subagent.thinking,
subagent_progress, delegation.requested, delegation.resolved,
context.started, context.continued, usage.updated
```

`subagent.start`/`subagent.complete` 等 Hermes 原生扩展保留原名；旧的 `subagent.started`/`subagent.completed` 只用于历史兼容，不作为实时 alias。

### 8.2 14 个用户语义名称的完成度

“完成”分为四层：`S` = Hermes source 已产生，`A` = Harness adapter 已投影，`T` = Gateway/transport canonical 已验收，`F` = Lobby/web2 有真实消费。名称不相同但语义可映射时，不标成同名完成。

| 用户语义名称 | 当前 canonical/source | S | A | T | F | 当前判断 |
|---|---|---:|---:|---:|---:|---|
| `assistant_message_started` | `turn.started` | 是 | 是 | 是 | 是 | 有 turn 起始事实；没有同名独立事件 |
| `assistant_text_delta` | `assistant.delta` | 是 | 是 | 是 | 是 | canonical 名称不同，语义已打通 |
| `assistant_tool_call` | `tool.generating`，随后 `tool.started` | 是 | 是 | 是 | 是 | `tool.generating` 无稳定 invocation ID；`tool.started` 才能建立调用节点；没有同名独立事件 |
| `tool_call_validated` | Hermes `turn_tool_validation` 内部状态 | 是（内部） | 否 | 否 | 否 | 当前没有独立 transport producer；需决定是否公开为受限诊断事件 |
| `tool_execution_started` | `tool.started` | 是 | 是 | 是 | 是 | canonical 名称不同，语义已打通 |
| `tool_execution_progress` | `tool.progress` | 是 | 是 | 是 | 是 | web2 reducer 已处理；并非每种工具都产生 progress callback |
| `tool_execution_completed` | `tool.completed` | 是 | 是 | 是 | 是 | canonical 名称不同，语义已打通 |
| `tool_result` | Hermes transcript result；用户侧为 `tool.completed.payload.summary` | 是 | 部分 | 部分 | 部分 | 完整结果仅在 Hermes 内部；用户事件只传受限 summary/状态，没有同名独立事件 |
| `assistant_turn_continued` | 普通 tool round continuation；另有 `context.continued` | 是（内部） | 否 | 否 | 否 | `context.continued` 只表示 compaction 后继续，不能当作每轮工具后继续 |
| `todo_updated` | `plan.updated`（由 `todo_list` 结果投影） | 是 | 是 | 是 | 是 | 前端应使用 `plan.updated`，不新增别名 |
| `delegation_started` | `delegation.requested` / `subagent.start` | 是 | 是 | 是 | 是 | allocation 请求和 child start 分开表达 |
| `delegation_progress` | `subagent_progress`、`subagent.text` | 是 | 是 | 是 | 是 | web2 reducer 已处理；需保持 lineage 和限长 preview |
| `delegation_completed` | `delegation.resolved` / `subagent.complete` | 是 | 是 | 是 | 是 | allocation resolution 与 child completion 是两个事实，不能合并成一个终态 |
| `assistant_message_completed` | `turn.completed` | 是 | 是 | 是 | 是 | turn terminal 已有；没有同名独立事件 |

**事件结论：** 当前工程不是“14 个用户语义同名事件全部已经完成”，而是它们大部分已经由 Hermes native callback 和 Harness canonical projection 覆盖。web2 的 `canonicalProjection.ts` 已投影工具、plan、delegation 和 subagent 事件；真实用户对局仍需用具体工具/子 Agent 验收进度密度和展示效果。`tool_call_validated` 与普通 turn continuation 没有独立 producer；`tool_result` 只有受限摘要跨传输。除非产品明确要求同名兼容事件，否则不应再增加一套 alias。

### 8.3 用户可见过程的推荐顺序

```text
turn.started
  -> assistant.delta* / tool.generating
  -> tool.started
  -> tool.progress*
  -> tool.completed (tool result summary)
  -> plan.updated                         (todo_list 时)
  -> delegation.requested
       -> delegation.resolved (allocation decision)
       -> subagent.start
       -> subagent.text / subagent_progress*
       -> subagent.complete
  -> assistant.delta*
  -> turn.completed
```

这是事件 lineage 的示意，不是客户端可以假定的全局时间排序。客户端必须按 `event_id` 去重、按 `sequence`/lineage 排序，并允许 child stream 与 parent stream 交错。

## 9. 安全和授权规则

- 工具授权以 `tool_name` 为原子单位；toolset 不能绕过单工具 deny。
- 工具参数和结果只传 bounded summary；凭证、完整 prompt、原始 transcript 和原始 reasoning 不进入普通用户事件。
- `reasoning.delta`、`subagent.thinking`、`usage.updated` 默认受限；未授权时发送结构化摘要或 warning。
- 工具和 delegation 事件必须带稳定的 invocation/allocation/lineage ID，便于重放、去重和审计。
- replay 只重放 canonical tail，不重新执行 user input、tool 或 delegation。
- `check_fn` 失败、grant 缺失和 catalog 版本不一致都必须生成可诊断错误，不得静默降级为“模型没有调用工具”。

## 10. 当前完成度与缺口

| 能力 | 状态 | 证据/缺口 |
|---|---|---|
| Hermes 原生 toolset/registry/handler | 已有 | `vendor/hermes/toolsets.py`、`vendor/hermes/tools/registry.py` |
| Agent 的 schema 选择、参数校验、执行和继续 turn | 已有 | `agent_init.py`、`turn_tool_validation.py`、`turn_tool_round.py`、`tool_executor.py` |
| `coding` 覆盖的 17 个目标 toolset 清单 | 已确认 | 静态原子集合比较；完整名单见 6.3 |
| `user_id -> Gateway` 进程亲和 | 已完成 | `docs/architecture/harness-gateway-affinity.md`、Gateway replacement plan G-01~G-06 |
| `session_id -> _HermesSession` 独立 runtime | 已有并沿用 | `HermesHostAdapter` session map 和多 session 验收 |
| `agent_id` 参与 session 内 Agent 选择/重建 | 已接线 | 不改变进程亲和键；配置变化只影响目标 session |
| Gateway UDS + JSONL + canonical relay | 已完成 | G-01/G-03、E-07 组合证据 |
| Lobby 原子工具 catalog/grant | 旧模型存在，新模型未实现 | 现有 `CatalogTool`、Agent `ToolsJSON` 和每轮 `allowed_tools` 只作为迁移输入；目标改为 `Toolset`/`ToolRevision`/`AgentRevision`/`SessionCapabilitySnapshot`，并与 Hermes registry 的 source/schema hash/version 对账。新路径必须 fail closed |
| Gateway toolset 加载和每轮 allowed tools | 每轮收窄已有；`coding` 按配置加载未做 | Harness 固定加载 `networkclaw`、`todo`、`delegation`、`clarify`；每轮 `allowed_tools` 只能过滤已加载 schema，不能扩出 `terminal` 等 Hermes 工具 |
| Lobby toolset -> 原子 grant | 设计完成，实现待接线 | Lobby 应保存 `requested_toolsets` 和展开后的 `allowed_tools`；必须在 Gateway 侧校验 `allowed_tools ⊆ loaded atom names` |
| Agent cache 对 toolset 变化重建 | 部分已有 | 当前 cache route 含原子 `tool_signature`；目标还要把 `requested_toolsets`/展开签名纳入 route，保证 coding 与窄 toolset 切换不会复用错误 schema |
| tool handler 在 Gateway 不复制 | 已满足设计边界 | handler 继续由 vendor/registry 提供 |
| 14 个用户语义事件 | canonical 语义大部分已完成 | 三项边界最明显：validation 无独立事件、完整 tool result 不跨传输、普通 turn continuation 无独立事件；见 8.2 矩阵 |
| 前端工具、todo、delegation 过程视图 | reducer 已有；真实体验待验收 | `web2/src/api/canonicalProjection.ts` 已消费相关事件，仍需具体工具和双 child 对局验证进度密度、终态顺序和展示效果；`tool.generating` 不得凭工具名误关联 invocation |

## 11. 后续任务顺序

1. **工具 catalog 对账**：从 Harness 当前 registry 生成带 schema hash、source、check capability 的原子 catalog，与 Lobby catalog 做 drift 检查。
2. **Coding toolset 接线**：将 Agent 初始化的固定 `enabled_toolsets` 改为 Host grant/session 配置；默认 coding session 使用 `["networkclaw", "coding"]`，窄能力 session 使用目标基础 toolset 子集。
3. **Gateway grant fixture**：覆盖 toolset -> atomic expansion、`allowed_tools_not_loaded`、deny、unknown tool、check_fn unavailable、catalog version mismatch 和 Agent cache 重建。
4. **Lobby grant fixture**：证明 `requested_toolsets` 只用于批量配置，最终传给 Harness 的 `allowed_tools` 是 17 个目标 toolset展开后的具体 Hermes 原子名。
5. **端到端事件 fixture**：至少覆盖普通工具、工具 progress、`todo_list`、双 child delegation、child failure/timeout 和 replay；校验前端只依赖 canonical event。
6. **事件缺口决策**：对 `tool_call_validated` 和普通 `assistant_turn_continued` 做产品决策；默认保留为内部事实或由现有 canonical 事件表达，不新增 alias。
7. **动态工具协议**：为 registry/plugin/MCP/context engine 建立 capability snapshot 和版本化 catalog 更新，不把动态工具硬编码进 integration。

事件统一仍以后于 Gateway replacement 的顺序执行；工具对齐的实现必须复用 Harness 原生 Agent/runtime，不在 integration 增加第二套执行循环。

## 12. 源码和文档依据

- Harness `vendor/hermes/toolsets.py`
- Harness `vendor/hermes/tools/registry.py`
- Harness `vendor/hermes/model_tools.py`
- Harness `vendor/hermes/agent/agent_init.py`
- Harness `vendor/hermes/agent/turn_tool_validation.py`
- Harness `vendor/hermes/agent/turn_tool_round.py`
- Harness `vendor/hermes/agent/tool_executor.py`
- Harness `src/networkclaw_harness/runtime/hermes_host_adapter.py`
- Harness `src/networkclaw_harness/host/server.py`
- Integration [`event-catalog-v1.md`](../contracts/event-catalog-v1.md)
- Integration [`harness-gateway-affinity.md`](harness-gateway-affinity.md)
- Integration [`harness-gateway-replacement-plan.md`](../plan/harness-gateway-replacement-plan.md)
- Integration [`event-unification-design-and-plan.md`](../plan/event-unification-design-and-plan.md)
- Integration [`event-e07-canonical-only.md`](../evidence/event-e07-canonical-only.md)
