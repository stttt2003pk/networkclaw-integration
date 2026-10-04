# Hermes Capability 重建实施计划

## 1. 目标

本计划按依赖顺序落地以下三份设计：

- [Hermes Tool 对齐设计](../architecture/hermes-tool-alignment.md)
- [Hermes Skill 对齐设计](../architecture/hermes-skill-alignment.md)
- [Hermes Agent 对齐设计](../architecture/hermes-agent-alignment.md)

目标是让 Lobby 的持久化模型、Harness Gateway 的 session 投影和 Hermes
runtime 使用同一套 capability 事实：

```text
Hermes registry/toolset
        ↓
Lobby capability catalog + revision
        ↓
Agent revision
        ↓
session capability/skill/agent snapshot
        ↓
Harness Gateway
        ↓
Hermes Agent/runtime
```

Tool、Skill、Agent 的新模型都允许废弃旧字段和旧表。旧数据只做一次性导入，
不在运行时保留双模型或复杂兼容层。

## 2. 仓库边界

| 仓库 | 责任 |
|---|---|
| `NetworkClaw` | Lobby 数据库迁移、repository/usecase、HTTP API、chatrtmgr 输入模型和 Web 前端 |
| `networkclaw-harness` | Hermes registry/toolset 投影、Gateway session 配置、Skill 注入、Agent cache route 和 Harness 单仓测试 |
| `networkclaw-integration` | 跨仓协议夹具、组合测试、drift 检查、bundle/provenance、计划和完成证据 |

Integration 不复制 Go 或 Harness 业务源码；代码必须回到所属源码仓库。

## 3. 当前完成度基线

| 能力 | 当前状态 | 主要缺口 |
|---|---|---|
| Tool/Toolset 设计 | 设计完成 | 新 catalog、revision、toolset 展开和 Gateway 动态加载未完成 |
| Hermes registry handler | 已存在 | 需要生成可对账的 catalog/schema hash，不复制 handler |
| Lobby Tool 模型 | 旧模型存在 | `CatalogTool`、`tools_json` 不能作为新运行时事实源 |
| Gateway toolset | 部分完成 | 每轮 `allowed_tools` 已有收窄；Agent 初始化仍固定 `networkclaw/todo/delegation/clarify` |
| Skill 设计 | 设计完成 | Harness 只有只读 `SkillCatalog`，尚未完整注入 Agent prompt/auto-load |
| Lobby Skill 模型 | 旧模型存在 | `CatalogSkill`、`skills_json` 需要替换为 release/revision/dependency/binding 模型 |
| Agent 设计 | 设计完成 | 需要新 profile/revision、session snapshot 和 Gateway 投影；Hermes Agent loop 本身沿用 |
| Session/lease/Gateway | 已完成 | 继续复用 `user_id -> Gateway`、`session_id -> _HermesSession` 的现有机制 |
| Canonical events | 已完成 | 新 capability 投影必须保留已有 tool/delegation/plan/session 事件和 lineage |
| 前端 | 有旧 Agents/Skills 页面 | 需要按 revision、toolset、skill binding 和 snapshot 重新建模 |

现有 Gateway、事件统一和 Hermes runtime 不在本计划中重写；本计划只接入
capability 配置和其投影。

## 4. 总依赖图

```text
C-00 公共 capability contract
  ↓
T-01 Hermes tool inventory
  ↓
T-02 Tool/Toolset schema + migration
  ↓
T-03 Lobby tool catalog API
  ↓
T-04 Harness registry → catalog projection
  ↓
T-05 Gateway requested_toolsets / atomic grant
  ↓
T-06 Agent schema/cache route + capability snapshot
  ↓
T-07 Tool vertical slice
  ↓
S-01 Skill release manifest
  ↓
S-02 Skill database + bindings
  ↓
S-03 Skill dependency resolver + session snapshot
  ↓
S-04 Harness SkillCatalog → Hermes prompt/auto-load
  ↓
S-05 Skill API/UI
  ↓
S-06 Skill vertical slice
  ↓
A-01 Agent profile/revision database
  ↓
A-02 Agent API/usecase
  ↓
A-03 Session Agent/Capability snapshots
  ↓
A-04 Gateway Agent projection
  ↓
A-05 Delegation and policy integration
  ↓
A-06 Agent UI
  ↓
A-07 Full end-to-end acceptance
  ↓
X-01 Remove old model
  ↓
X-02 Bundle, drift and delivery verification
```

严格依赖只约束进入共享验收和生产切换的顺序。每个阶段内部标出的并行任务，
可以在其共同前置任务完成后同时实施。

## 5. 执行任务

### C-00 [P0] 冻结公共 capability、revision 和 snapshot 契约

**依赖**：无。  
**主责**：Integration；NetworkClaw 与 Harness 联合评审。  
**状态**：已完成（2026-09-28）。

**模块**：

- Integration：`schemas/`、`docs/contracts/`、`tests/fixtures/`
- NetworkClaw：Lobby/Harness binding 的字段定义
- Harness：`runtime/context.py`、`hermes_host_adapter.py` 的输入边界

**任务**：

- 冻结 `toolset revision`、`tool revision`、`skill revision`、`agent revision` 的
  ID、version、content/schema hash、source、release/status 和 catalog version。
- 冻结 `SessionCapabilitySnapshot`、`SessionSkillSnapshot`、`SessionAgentSnapshot`
  的结构、创建时机、不可变规则和序列化方式。
- 明确 Lobby 请求字段与 Harness 字段：`requested_toolsets` 是候选 schema
  输入，`allowed_tools` 是最终原子授权，Skill/Agent 是 revision 引用和配置快照。
- 冻结 unknown、unavailable、not-loaded、denied、stale-revision 的错误语义。
- 将 capability snapshot hash 纳入 Gateway debug/readiness 和事件关联字段；不把
  transcript、provider client、workspace 路径或 Hermes Agent 实例放进持久化模型。

**验收**：生成 versioned schema/字段表和 fixture；Go、Python、Integration 三侧
能够校验同一 snapshot hash；旧模型字段不出现在新协议必填字段中。

**完成记录（2026-09-28）**：

- 新增 `schemas/capability-snapshot-v1.schema.json`，冻结 Catalog、Tool、Skill、Agent revision 及三类 session snapshot 的必填字段和枚举。
- 新增 `docs/contracts/capability-snapshot-v1.md`，冻结 canonical JSON、`sha256:` hash、快照不可变规则、Lobby/Harness 字段边界和错误语义。
- 新增 `tests/fixtures/capabilities/session-capability-snapshot-v1.json`；`tools/capability_contract.py` 提供跨语言可复现的 `snapshot_hash` 规则，并在 Skill 快照中冻结 `resolved_dependencies`。
- `tools/validate-contracts.py` 和 `tests/test_capability_contract.py` 已接入 schema 与 hash 校验；当前 fixture 验证 hash 为 `sha256:6752dc7864f4ee7ca2e2326fcdffb683cd69103c1573173b787bc1a5077e6054`。
- 未把 Go/Harness 业务源码复制到 integration；旧 `tools_json`、`skills_json` 未进入新协议。
- 验证：`make validate-contracts` 通过；C-00/Catalog projection/vertical slice 聚焦测试通过；`make test` 通过 80 项 Python 测试及 `go test -race ./tools/web2-server`；`git diff --check` 通过。
- 本轮复核（2026-09-28）：使用仓库 `.venv` 重新执行 `make validate-contracts` 和 `make test`，均通过；系统 Python 未安装 pytest，因此聚焦测试通过仓库标准 unittest 入口验证。

**下一步**：C-00 的公共契约已被 T-01 至 S-04 使用并通过组合验证；当前进入 **S-05 Skill API、前端 catalog 和绑定配置**，由 NetworkClaw 接入 revision/dependency 查询、Agent binding mode 和新 session 生效边界。

### T-01 [P0] 对账 Hermes registry、toolset 和动态工具清单

**依赖**：C-00。  
**主责**：Harness；Integration 负责机器可读证据。  
**状态**：已完成（2026-09-28）。

**模块**：

- `vendor/hermes/toolsets.py`
- `vendor/hermes/model_tools.py`
- `vendor/hermes/tools/registry.py`
- `src/networkclaw_harness/tools/supply_chain.py`
- Integration：`docs/evidence/`、catalog drift 检查工具

**任务**：

- 读取 Hermes 原名 toolset 和原子工具，不创建 NetworkClaw 别名。
- 记录 `coding` 以及基础 toolset、组合 toolset、`networkclaw` 动态 toolset 的
  展开关系。
- 从 registry 输出工具名称、schema 摘要/hash、source、availability、check
  capability 和 toolset membership。
- 区分静态 `TOOLSETS`、registry/plugin 工具、MCP 工具和运行时注入工具。
- 为重复 bundle 去重；catalog 只存一份原子工具，toolset 关系单独建模。

**验收**：同一 Harness checkout 可重复生成 inventory；静态清单、registry 输出和
`resolve_toolset` 展开结果无漂移；unknown/dynamic 工具不会被静默丢弃。

**完成记录（2026-09-28）**：

- 新增 `tools/generate-hermes-inventory.py`，在 Harness checkout 子进程中导入 Hermes `toolsets`、`model_tools`、registry 和 NetworkClaw host tool installer，避免复制业务源码。
- 生成 `docs/evidence/hermes-tool-inventory.json`：包含 60 个静态 toolset、34 个 registry toolset、101 个 registry 工具和 101 个去重原子工具；记录 direct/include/resolved membership、schema hash、source、availability、check capability。
- `networkclaw_workspace_read` 被标记为 `runtime_injected`；MCP toolset、插件 toolset 与 Hermes registry 工具使用独立 kind，静态空展开 toolset 标记为 runtime injection surface。
- `--requested-toolset` 对未知名称输出 `resolution_errors`，不会静默丢弃；`tests/test_hermes_inventory.py` 验证同一 checkout 两次生成完全一致、动态工具保留及 unknown fail-closed。
- 新增 `make hermes-inventory` 入口；Harness checkout 当前为 commit `43796097255c2c98ea0a945867ca51d4c14bb445`。

**下一步**：进入 **T-02 Tool/Toolset 数据库模型**，在 NetworkClaw 中建立 catalog、toolset membership 和 tool revision 持久化及一次性旧模型导入。

### T-02 [P0] 重建 Tool/Toolset 数据库模型

**依赖**：T-01。  
**主责**：NetworkClaw。  
**状态**：已完成（2026-09-28）。

**模块**：

- `internal/lobby/model/catalog.go`
- `internal/lobby/repository/catalog.go`
- `internal/lobby/repository/catalog_pg.go`
- `internal/lobby/database/migrations/`

**任务**：

- 新建 `toolsets`、`toolset_tools`、`tool_revisions`（名称可按 Go 规范调整）及
  必要的 catalog/revision 状态表。
- Tool 记录 Hermes 原子名、schema hash、version、source、availability、grant
  policy 和 required capabilities。
- Toolset 只保存 Hermes 原名、描述、来源、状态和 revision 关系，不保存 handler。
- 用唯一约束防止同一 catalog version 下原子工具重复注册；toolset 关系支持
  多对多和版本化。
- 提供一次性旧 `CatalogTool`/旧 JSON 字段导入脚本或 migration；导入后新运行时
  不再读取旧表。

**验收**：迁移可在空库和含旧 catalog 的数据库执行；schema hash/version/source
  可审计；无重复原子工具；回滚或失败时不产生半套 revision。

**完成记录（2026-09-28）**：

- NetworkClaw 新增 `CapabilityCatalogVersion`、`ToolsetRevision`、`ToolRevision` 模型及 `CapabilityCatalogRepository` 查询接口；运行时模型只保存 Hermes 原子工具、toolset membership 和审计字段，不保存 handler/provider/transcript。
- 新增 `022_rebuild_capability_catalog.up.sql` / `.down.sql`，建立 catalog version、toolset、tool revision 和多对多 membership 表；唯一约束保证同一 catalog version 下 tool/toolset revision 不重复。
- migration 将旧 `catalog_tools` 与 `catalog_agents.tools_json` 一次性导入 `legacy-catalog-import-v1`，旧 schema 无 hash 时使用可审计的全零 `sha256:` 占位并标记 `retired`；旧表暂留，待后续运行时切换后移除。
- 临时 PostgreSQL 验证完整 001–022 迁移链、旧数据导入和 022 回滚：空库成功；含旧 catalog 时导入 9 条 tool revision、9 条 membership；回滚后新表全部移除。`go test ./internal/lobby/model ./internal/lobby/repository` 通过，`git diff --check` 通过。

**下一步**：进入 **T-03 Lobby Tool catalog 和 grant API**，基于本模型实现 toolset 展开、原子授权校验、retired/unavailable 拒绝和稳定 capability snapshot hash。

### T-03 [P0] 实现 Lobby Tool catalog 和 grant API

**依赖**：T-02。  
**主责**：NetworkClaw。  
**状态**：已完成（2026-09-28）。

**模块**：

- `internal/lobby/usecase/catalog.go`
- `internal/lobby/transport/http/catalog.go`
- `internal/lobby/model/catalog.go`
- `internal/lobby/repository/*catalog*`

**任务**：

- 提供 toolset 查询、原子工具查询、revision 查询、membership 展开和 snapshot
  hash 查询。
- Agent/Host 配置可以提交 `requested_toolsets`，但保存时展开并校验最终
  `allowed_tools`。
- 拒绝 unknown tool、retired revision、unavailable tool 和不匹配的 schema hash。
- 返回可供 Harness 使用的结构化 capability snapshot；不返回 Python handler 或
  完整敏感配置。
- 保留审计字段：actor、revision、catalog version、source 和更新时间。

**验收**：API 能把 `coding` 展开成 Hermes 原子集合；toolset 重复覆盖不会重复授权；
  直接提交未注册原子工具会 fail closed；snapshot hash 稳定且可复算。

**完成记录（2026-09-28）**：

- 新增 `CapabilityCatalogUseCase`、`CapabilityCatalogHandler` 和真实 PostgreSQL repository 查询：toolset、原子 tool revision、membership 和 catalog version 均从 T-02 新表读取。
- 新增 `GET /api/v1/catalog/{version}/toolsets`、`GET /api/v1/catalog/{version}/tools` 和 `POST /api/v1/catalog/grants`；grant 请求按 `requested_toolsets` 展开去重后的 `allowed_tools`，同时校验 catalog 必须 published、toolset/tool 必须 active/available、提交的 allowed_tools 和 schema hash 必须匹配。
- snapshot 使用排序后的 canonical JSON 计算稳定 `sha256:` hash；响应不包含 handler、provider client、transcript 或敏感配置。
- 新增 usecase 验收测试覆盖 toolset 展开、重复授权去重、hash 稳定性、unavailable tool 和 schema hash mismatch fail closed。
- `go test ./internal/lobby/usecase ./internal/lobby/transport/http ./internal/lobby/repository` 通过；integration `make test` 通过（72 项）。

**下一步**：进入 **T-04 Harness registry 到 Tool catalog 的投影**，将 T-01 inventory 转换为 published catalog payload，并加入 catalog drift 对账和同步入口。

### T-04 [P0] 接通 Harness registry 到 Tool catalog 的投影

**依赖**：T-01、T-03。  
**主责**：Harness；Integration 提供 drift fixture。  
**状态**：已完成（2026-09-28）。

**模块**：

- `vendor/hermes/tools/registry.py`
- `vendor/hermes/toolsets.py`
- `src/networkclaw_harness/tools/supply_chain.py`
- `src/networkclaw_harness/skills/catalog.py`（仅复用 snapshot 读取边界）

**任务**：

- 实现 registry/toolset inventory 到 Lobby catalog payload 的生成或同步入口。
- 保持 vendor handler 为唯一执行来源；Gateway 只引用 registry 中的 schema/name。
- 记录 check function 失败原因，区分 registered、available 和 executable。
- 对 MCP/plugin/runtime 工具采用 source/version 标记，不把动态工具硬编码进静态表。

**验收**：Harness inventory 与 Lobby catalog 自动对账；新增、删除、schema hash
  变化会产生 drift 失败；handler 仍只存在于 Harness vendor/registry。

**完成记录（2026-09-28）**：

- 新增 `tools/project-hermes-catalog.py` 和 `make hermes-catalog`，把 T-01 inventory 确定性投影为 `docs/evidence/hermes-capability-catalog-v1.json`：64 个 toolset、101 个去重原子工具、1499 条 membership。
- 生成 payload 使用 published Hermes catalog、revision=1、schema hash、source、availability、grant policy、required capabilities 和 status；静态、registry、plugin、MCP、runtime-injected 来源保留，不写入 handler/provider 实例。
- inventory 记录 check function 的 `check_returned_false` / `check_failed` 原因；不可用工具进入 retired 状态，动态来源仍保留在 catalog payload。
- `drift_errors` 对 catalog/toolset/membership/resolution errors 做 fail-closed 对账；测试覆盖确定性、去重、动态来源保留及 schema hash 变化失败。当前 catalog hash 为 `sha256:5cc8ccd8f21496920c1c5f6f50413f08c7a5cb2a2392fa260ca5a7277291a65b`。
- `.venv/bin/python -m unittest tests.test_capability_catalog_projection -v` 通过；后续 `make test` 需覆盖该测试。

**下一步**：进入 **T-05 Gateway 接入 requested toolsets 和原子授权**，让 Harness session 使用 catalog snapshot、requested toolsets 与每轮 allowed_tools 的交集。

### T-05 [P0] Gateway 接入 requested toolsets 和原子授权

**依赖**：T-03、T-04。  
**主责**：Harness；NetworkClaw 负责 Host binding 输入。  
**状态**：已完成（2026-09-28）。

**模块**：

- `src/networkclaw_harness/runtime/hermes_host_adapter.py`
- `src/networkclaw_harness/host/server.py`
- `src/networkclaw_harness/runtime/context.py`
- `vendor/hermes/model_tools.py`
- `vendor/hermes/agent/agent_init.py`

**任务**：

- 将固定的 `enabled_toolsets=["networkclaw", "todo", "delegation", "clarify"]`
  改为 session 配置中的 `requested_toolsets`。
- 先调用 Hermes 原生 toolset resolver 生成候选 schema，再应用 catalog snapshot、
  Host grant 和每轮 `allowed_tools` 的交集。
- 明确集合公式：`loaded ∩ host_grant ∩ turn_allowed`；toolset 名不能进入
  `allowed_tools`。
- 返回 `valid_tool_names`、loaded toolsets、catalog version/hash 和不可用原因。
- 在配置刷新或 grant 变化时只重建目标 session 的 Agent；不能影响同一 Gateway
  进程中的其他 session。

**验收**：

- `enabled_toolsets=["networkclaw", "coding"]` 可以看到 coding schema；
- 窄 toolset 可以只加载 `file/terminal/todo`；
- `allowed_tools` 不能扩出未加载 schema；unknown/denied/unavailable 分别报错；
- 两个 session 的 tool snapshot 和 Agent cache 完全隔离。

**完成记录（2026-09-28）**：

- Harness `host_grant` 现在接收并校验 `requested_toolsets`、`catalog_version`、`catalog_hash`，并将字段完整传入 session runtime。
- `HermesHostAdapter` 使用 Hermes 原生 `validate_toolset`/`resolve_toolset` 展开 requested toolsets；不再对新 grant 固定四个 toolset。授权集合按 `loaded ∩ host_grant ∩ turn_allowed` 收窄，toolset 名混入 `allowed_tools`、unknown、未加载和 unavailable 工具均 fail closed。
- `turn.started` 返回 requested/loaded toolsets、实际 `valid_tool_names`、catalog version/hash；Agent cache route 纳入 toolset 和 catalog 元数据，配置变化只驱逐目标 session 的 Agent。
- 保留旧 grant 未携带 `requested_toolsets` 的兼容路径，避免已有会话协议回归；新路径覆盖 `todo`、`file` 窄集合和双 session 隔离。
- Harness `.venv/bin/python -m pytest tests/test_hermes_host_adapter.py tests/test_host.py -q` 通过（70 项）；新增测试覆盖 requested toolset、unknown/unloaded fail closed 和 session cache 隔离。

**下一步**：进入 **T-06 Tool snapshot、Agent schema 和 cache route**，把 catalog snapshot 的完整签名、原子授权和 provider route 纳入 Agent cache 与 diagnostics，并补工具拒绝事件关联。

### T-06 [P0] 完成 Tool snapshot、Agent schema 和 cache route

**依赖**：T-05。  
**主责**：Harness。  
**状态**：已完成（2026-09-28）。

**模块**：

- `src/networkclaw_harness/runtime/hermes_host_adapter.py`
- `src/networkclaw_harness/runtime/context.py`
- `vendor/hermes/agent/agent_init.py`
- `vendor/hermes/agent/turn_tool_validation.py`

**任务**：

- 将 `requested_toolsets` 展开签名、原子 `allowed_tools`、catalog version/hash、
  provider route/profile 纳入 Agent cache route。
- Agent 创建后报告实际 `valid_tool_names`，供 Gateway diagnostics 使用。
- 让每轮 `allowed_tools` 只过滤已加载 schema，并保留 Hermes 原生选择、参数校验、
  registry dispatch、结果处理和继续 turn。
- 增加 tool call 与 canonical event 的 invocation/session/turn 关联，不能由前端
  从文本猜测工具调用。

**验收**：切换 coding 与窄 toolset 不会复用错误 Agent；工具被拒绝时有稳定错误
  事件；普通 tool、progress、todo、delegation 事件仍保持现有 canonical 名称和 lineage。

**完成记录（2026-09-28）**：

- `HermesHostAdapter` 的 Agent cache route 已包含 provider route、profile、requested toolsets 展开签名、原子 grant、catalog version/hash、turn budget；配置变化只驱逐当前 session Agent。
- session admission 及 Agent 创建后记录实际 `valid_tool_names`；每轮 `allowed_tools` 只能从已加载 schema 中筛选，越权仍返回稳定 `allowed_tools_exceed_grant` / `allowed_tool_not_loaded` 错误。
- `tool.started`、`tool.progress`、`tool.completed` 现在显式携带 `invocation_id` 与 session/turn/run/request identity，保留现有 canonical event 名称、todo plan 和 delegation lineage。
- 新增测试覆盖 snapshot route 隔离、每轮工具收窄、工具拒绝和 tool event identity；`.venv/bin/python -m pytest tests/test_hermes_host_adapter.py tests/test_host.py -q` 通过（72 项）。

**下一步**：进入 **T-07 Tool vertical slice 和跨仓验收**，联通 Lobby catalog grant、Gateway session snapshot、provider 工具调用及故障语义，形成可重复的组合测试证据。

### T-07 [P0] Tool vertical slice 和跨仓验收

**依赖**：T-06。  
**主责**：Integration；NetworkClaw/Harness 联合。  
**状态**：已完成（2026-09-28）。

**范围**：`networkclaw + coding`，至少覆盖 `read_file`、`search_files`、`write_file`、
`patch`、`terminal`、`todo_list`、`delegate_task`。

**任务与验收**：

- Lobby 选择 toolset，生成原子 grant 和 snapshot hash。
- Gateway 为 session 加载对应 Hermes schema，另一个 session 使用窄集合。
- Provider 触发普通工具、工具 progress、todo 更新和双 child delegation。
- 验证 unknown、not-loaded、denied、check_fn unavailable、catalog mismatch、
  cache rebuild 和 session 隔离。
- web2 只消费 canonical tool/plan/delegation/subagent 事件，能重建完整过程树。

Integration 必须留下可重复的组合测试、Harness/Go 测试命令和失败清理证据。

**完成记录（2026-09-28）**：

- 新增 `tests/test_capability_vertical_slice.py`，把 Lobby capability snapshot fixture 与 T-04 Harness catalog 对账，覆盖 `read_file`、`search_files`、`write_file`、`patch`、`terminal`、`todo_list`、`delegate_task`、`networkclaw_workspace_read` 八个 vertical-slice 工具及 schema hash/membership。
- 测试验证 snapshot 的最终 `allowed_tools` 只来自 catalog、`terminal` deny 不会泄漏，并重复执行 `project-hermes-catalog.py` 验证 101 tools、64 toolsets、1499 memberships 的稳定结果。
- 现有 Harness T-05/T-06 测试已覆盖 `coding`/窄 toolset session 隔离、unknown/not-loaded/unavailable/denied、cache rebuild 及 tool event identity；Go integration harnessinterop 入口继续作为真实 Gateway/provider-stub 验收入口。
- `make test` 通过 78 项；新增 vertical slice 3 项通过，`git diff --check` 通过。测试使用临时输出并由现有 integration cleanup 机制清理，不启动持久 provider 或写入原始源码仓库。

**下一步**：进入 **S-01 Skill release manifest 和 revision 投影**，为 Hermes Skill 生成可审计 release manifest、依赖和 trust/release 状态。

### S-01 [P0] 建立 Skill release manifest 和 revision 投影

**依赖**：T-07、C-00。  
**主责**：Harness；Integration 负责 manifest/schema fixture。  
**状态**：已完成（2026-09-28）。

**模块**：

- `src/networkclaw_harness/skills/catalog.py`
- `vendor/hermes/agent/skill_utils.py`
- `vendor/hermes/agent/skill_commands.py`
- Harness skill release/source 目录

**任务**：

- 为每个 Skill 生成只读 release manifest、version、content hash、manifest hash、
  release ref、platform/session_platform、trust/release status。
- 记录 `required_toolsets`、`required_tools`、fallback 和 config schema。
- 区分 `available`、`auto_load`、`disabled`；可用不等于自动注入 prompt。
- Skill 正文、reference/template/asset/script 不进入 Tool 表，也不注册 tool handler。

**验收**：同一 Skill release 可重复生成相同 hash；manifest 能表达工具依赖、平台
  条件和信任状态；未发布或 quarantine Skill 不能进入 session snapshot。

**完成记录（2026-09-28）**：

- Harness `SkillCatalog` 生成确定性 release manifest：包含版本、release ref、SKILL.md 与 metadata hash、manifest hash、platform/session_platform、toolset/tool 依赖、fallback、config schema 及包内 support file hash；信任与发布状态来自受控 root policy，未知来源默认为 `unknown`/`unavailable`，不接受 `skill.json` 自行声明 trusted/published。
- session load fail closed：仅 `available` 且 `trusted` 的 Skill 可加载；目录发现本身不代表自动加载，semantic asset 显式区分 `available`、`auto_load`、`disabled`。正文仍只作为 Skill 内容，不注册 tool handler；正文、metadata 或支持文件在 catalog 冻结后变化会拒绝 session load。
- Integration 新增 `schemas/skill-release-manifest-v1.schema.json`、`tools/generate-skill-manifest.py`、`make hermes-skill-manifest` 和 `docs/evidence/hermes-skill-release-manifest-v1.json`；公共 capability Skill schema 同步新增 release ref、平台/依赖/fallback/config/support files 和 metadata hash。
- Harness `tests/test_skill_release_manifest.py` 覆盖 manifest 确定性、条件字段、quarantine/unavailable/unknown 拒绝、root policy 信任边界、support file hash 与 session 冻结后的篡改拒绝；Integration contract test 对账生成输出、schema 和 manifest hash。
- 验证：Harness `scripts/run_tests.sh` 通过 279 项测试，vendor 完整性（773 个文件）和 runtime closure 校验通过；focused Skill tests 9 项通过。Integration `make hermes-skill-manifest`、`make validate-contracts`、`make test`（80 项 Python 测试及 Go race 测试）和 `git diff --check` 通过。未修改 `vendor/hermes`。

**下一步**：进入 **S-02 Skill 数据库和 Agent binding**，由 NetworkClaw 建立 Skill revision、依赖和 Agent binding 持久化及一次性旧模型导入；Harness release manifest 作为 revision 导入事实，不在 Lobby 保存 Skill 正文。

### S-02 [P0] 重建 Skill 数据库和 Agent binding

**依赖**：S-01。  
**主责**：NetworkClaw。  
**状态**：已完成（2026-09-28）。

**模块**：

- `internal/lobby/model/catalog.go`（或拆分 skill model）
- `internal/lobby/repository/catalog.go`
- `internal/lobby/repository/catalog_pg.go`
- `internal/lobby/database/migrations/`

**任务**：

- 新建 `skill_catalog`、`skill_revisions`、`skill_revision_dependencies`、
  `agent_skill_bindings`。
- Binding 保存 Agent 对 Skill revision 的引用、mode（auto/explicit/disabled）、
  config 和排序；不保存 Skill 正文的运行时副本。
- 将旧 Skill 数据一次性导入新 revision；新运行时不再读取 `skills_json`。
- 对 required toolset/tool 做 revision 级引用校验。

**验收**：Skill revision、依赖和 Agent binding 可独立审计；禁用/撤销/过期 Skill
  不会被新 session 选中；同一 Skill revision 可以被多个 Agent 引用而不共享可变状态。

**完成记录（2026-09-28）**：

- NetworkClaw 新增 `skill_catalog`、`skill_revisions`、`skill_revision_dependencies`、`agent_skill_bindings` 及 down migration；revision 保存 release/hash、config schema、support files、平台条件和过期时间，依赖通过 FK 引用 Tool/Toolset revision。
- 旧 `catalog_skills` 与 Agent `skills_json` 仅作为一次性导入输入；legacy revision 明确为 `unknown`/`unavailable`/`retired`，新运行时的 Agent 查找不再读取 `skills_json`。
- PGX repository 支持 revision/依赖事务写入、binding 写入/查询，以及按 catalog enabled、binding mode、release/trust/status、撤销、过期和平台条件过滤可选项。
- `skill_pg_test.go` 覆盖依赖 FK 失败回滚、同一 revision 的多 Agent 独立 config、disabled/revoked/expired/untrusted/platform 过滤；JSONB 断言按对象语义比较，避免 PostgreSQL 格式化差异。
- 隔离 PostgreSQL 验证 001–023 迁移、023 重复执行导入和 down migration；导入断言为 `3|2|3|1|1`，down 后三张 Skill 新表均已移除。
- 验证：`go test ./internal/lobby/model ./internal/lobby/repository ./internal/lobby/usecase ./internal/lobby/transport/http` 通过；S-02 PG 集成测试通过；`make validate-contracts`、`make test` 和 `git diff --check` 通过。Harness `vendor/hermes` 未修改。
- 遗留项：binding 当前引用 `catalog_agents` 身份；Agent revision 级引用待 A-01 建模后提升，不能在 S-02 中伪造 revision 事实源。

**下一步**：进入 **S-03 Skill 依赖解析和 SessionSkillSnapshot**，联通 Lobby binding、依赖解析与 Harness session 冻结；在 S-06、A-07 完成前继续保留旧 catalog 作为迁移输入，不切换生产事实源。

### S-03 [P0] Skill 依赖解析和 SessionSkillSnapshot

**依赖**：S-02、T-06。  
**主责**：NetworkClaw/Harness 联合。  
**状态**：已完成（2026-09-28）。

**模块**：

- NetworkClaw Lobby skill usecase/repository
- `src/networkclaw_harness/skills/catalog.py`
- `src/networkclaw_harness/runtime/context.py`
- `src/networkclaw_harness/runtime/hermes_host_adapter.py`

**任务**：

- 创建 session 时解析 Skill revision、依赖工具/工具集、platform 和 trust 条件。
- 生成不可变 `SessionSkillSnapshot`，保存 skill IDs、versions、hashes、mode 和
  resolved dependencies。
- 依赖不满足时区分 unavailable、tool denied、toolset not loaded、trust blocked。
- Skill catalog 发布新版本只影响新 session；运行中 session 不通过普通 toggle
  直接修改 system prompt。

**验收**：snapshot hash 可复算；缺少依赖时 session 创建 fail closed；同一 session
  的后续 catalog 发布不会改变已冻结 Skill 内容。

**完成记录（2026-09-28）**：

- Harness `SkillCatalog.resolve_session_snapshot()` 生成不可变 `SessionSkillSnapshot`，冻结 Skill ID、version、content hash、config hash、mode 和 resolved tool/toolset dependencies，并提供 `skill_set_hash`/`snapshot_hash` 的稳定 SHA-256。
- Harness 解析在 session 绑定后校验 release、trust、platform、toolset loaded、tool authorization 和 config；分别返回 `skill_not_published`、`skill_not_trusted`、`skill_unavailable`、`skill_toolset_not_loaded`、`skill_tool_not_authorized`、`skill_config_missing`。
- NetworkClaw 新增同构 `model.SessionSkillSnapshot`、`ResolveSkillSnapshot` 和 `CatalogSkillSnapshotResolver`；session 创建在 Manager/ChatService 分配前解析，依赖失败直接 fail closed。Skill revision 查找和 024 migration 输入已补齐，Skill 正文仍不进入 Lobby。
- 新增 Harness 与 Go focused tests，覆盖可复算 hash、toolset/tool/trust 失败分类；NetworkClaw `go test ./...`、Integration `python tools/validate-contracts.py` 和 Harness Python 编译校验通过。
- 新 catalog release 不会修改已有 snapshot；已有 session 使用已冻结的 revision/content hash，变更需创建新 session。

**下一步**：进入 **S-04 Harness SkillCatalog → Hermes prompt/auto-load**，把已冻结的 `auto_load`、`explicit`、`disabled` 模式接入 Hermes prompt/native skill tools，并保留依赖授权边界。

### S-04 [P0] Harness SkillCatalog 接入 Hermes prompt 和 native skill tools

**依赖**：S-03。  
**主责**：Harness。  
**状态**：已完成（2026-09-28）。

**模块**：

- `vendor/hermes/agent/prompt_builder.py`
- `vendor/hermes/agent/skill_utils.py`
- `vendor/hermes/tools/skills_tool.py`
- `src/networkclaw_harness/skills/catalog.py`
- `src/networkclaw_harness/runtime/hermes_host_adapter.py`

**任务**：

- 将 `auto_load` Skill 内容按 snapshot 注入 Hermes prompt 构建路径。
- `explicit` Skill 通过 Hermes 原生 `skill_view`/`skill_manage` 路径加载，不绕过
  tool grant 和 session snapshot。
- Skill 需要的 tools/toolsets 必须先经过 T-05/T-06 的授权交集。
- Skill 内容按 trust、长度、敏感字段和 release 状态过滤；不把 Skill 当作 tool
  handler 或独立 Agent loop。

**验收**：auto-load、explicit、disabled 三种模式行为可区分；Skill 依赖工具未获
  授权时有结构化失败；Hermes Agent 仍负责选择工具和继续 turn。

**完成记录（2026-09-28）**：

- Harness `SkillCatalog.project_session_snapshot()` 在已冻结 snapshot 上重新执行 release/trust/hash 校验；`auto_load` 生成带 content hash 的有界 prompt block，过滤空内容、超过 64 KiB、NUL 和敏感字段；`explicit` 仅返回 Skill ID 供原生 `skill_view` 路径使用，`available` 与 `disabled` 不注入 prompt 或显式面板。
- `HermesHostAdapter` 在 Agent 创建前投影 Skill snapshot，要求 resolved toolsets 已加载、required atomic tools 已授权；显式 Skill 没有 `skill_view` 授权时返回 `skill_tool_not_authorized`。prompt 通过 Hermes 原生 `ephemeral_system_prompt` 注入，Hermes 仍拥有完整 Agent/tool loop。
- Host Protocol 对 `host_grant.skill_snapshot` 做 session、mode、版本/hash 和依赖数组边界校验，snapshot 不接受 Skill 正文；Agent route 包含 `skill_set_hash`，避免跨 snapshot 复用缓存。
- 新增 Skill projection mode/filter 测试；Harness 聚焦测试 81 passed，全量测试 282 passed，vendor/runtime closure 校验通过。未修改 `networkclaw-harness/vendor/hermes`。

**下一步**：进入 **S-05 Skill API、前端 catalog 和绑定配置**，将 catalog、revision、依赖和 mode 绑定接入 NetworkClaw API/前端，并保持新绑定只影响新 session。

### S-05 [P0] Skill API、前端 catalog 和绑定配置

**依赖**：S-02、S-03。  
**主责**：NetworkClaw。  
**状态**：已完成（2026-09-29）。

**模块**：

- `internal/lobby/transport/http/` skill endpoints
- `web/src/pages/Skills.tsx`
- `web/src/api/skills.ts`
- Agent 配置页面中 Skill binding 区域

**任务**：

- 提供 Skill catalog、revision、依赖、trust/release 状态和影响范围查询。
- 前端按可用/自动加载/显式加载/禁用显示，不把 Skill 误显示为原子工具。
- 绑定时显示 required toolsets/tools 和缺失原因；保存的是 revision 引用和 mode。
- 修改影响新 session；运行中 session 显示当前 snapshot，不假装即时修改。

**验收**：前端能完成 catalog 浏览、revision 选择、依赖提示、Agent binding 保存；
  API 返回的 binding 与 Gateway snapshot 一致。

**完成记录（2026-09-29）**：

- 新增 Skill revision/catalog API：revision 列表、revision detail/dependencies、Agent binding 查询和完整集合替换保存；API 只返回 release/trust/status、平台范围及依赖 metadata，不返回 Skill 正文。
- Agent binding mode 固定为 `auto_load`、`explicit`、`disabled`（兼容旧 `auto` 并归一化）；保存时删除未提交的旧 binding，绑定只在新 session 创建时生效。
- `Skills.tsx` 已切换到 revision catalog，显示版本、release/trust、范围、来源和 tool/toolset 依赖；`Agents.tsx` 的 binding 编辑区显示 required/fallback 依赖及 unavailable、untrusted、inactive、过期和平台限制原因。
- session 创建时将 immutable、body-free `SessionSkillSnapshot` 及 `skill_snapshot_hash` 写入 `sessions`；Get/List/Create session response 返回 snapshot/hash，fork session 继承创建时 snapshot，运行中 session 不随 binding 修改。
- 新增/更新 repository、usecase、HTTP、前端测试；验证通过：NetworkClaw `go test ./internal/lobby/repository ./internal/lobby/model ./internal/lobby/usecase ./internal/lobby/transport/http`、`npm run typecheck`、`npm run build`、`git diff --check`。

**下一步**：进入 **S-06 Skill vertical slice 和跨仓验收**，验证 auto-load、explicit、disabled、缺失依赖和旧 session snapshot 的真实 Go ↔ Harness 行为。

### S-06 [P0] Skill vertical slice 和跨仓验收

**依赖**：S-04、S-05。  
**主责**：Integration；NetworkClaw/Harness 联合。  
**状态**：已完成（2026-09-29）。

**验收场景**：

- 创建一个带 `auto_load` Skill 的 Agent session，验证 prompt 注入和 content hash。
- 创建一个 explicit Skill session，验证 `skill_view` 经过工具授权和事件链路。
- 缺少 required tool、toolset 未加载、quarantine 和 disabled 各有稳定错误。
- 发布新 Skill revision 后，旧 session 仍使用旧 `SessionSkillSnapshot`。
- 前端能显示 Skill 与其依赖 Tool/Toolset 的关系，而不读取 Skill 正文作为工具事实。

**完成记录（2026-09-29）**：

- NetworkClaw 新增真实 Host Protocol vertical slice：通过 `host_grant.skill_snapshot` 启动 auto-load、explicit 和 disabled session；auto-load session 完成真实 provider turn，explicit session 在授权 `skill_view` 后产生 `tool.started`/`tool.completed` 事件并完成 turn。
- 跨仓验收覆盖 required tool 未授权、required toolset 未加载和 stale revision 的稳定错误码；Harness `session.open` 现在透传 runtime skill 错误码，不再统一包装成 `runtime_open_failed`。
- 旧 snapshot 继续按 session/revision/content hash 校验；发布或传入不匹配版本会 fail closed。Skill 正文仍只由 Harness catalog 提供，NetworkClaw 仅传递 body-free snapshot。
- 验证：NetworkClaw `go test -race ./tests/integration/harnessinterop -run TestSkillVerticalSliceHostProtocol|TestSingleSessionVerticalFlow -count=1` 通过；Harness Skill/Host focused tests 通过；三仓 `git diff --check` 通过。
- 未修改 `networkclaw-harness/vendor/hermes`。

**下一步**：进入 **A-01 Agent Profile/Revision 数据库**，把 Agent revision、Skill binding 和 capability snapshot 纳入同一可审计事实源。

## 6. Agent 阶段

### A-01 [P0] 重建 Agent Profile/Revision 数据库

**依赖**：T-07、S-06、C-00。  
**主责**：NetworkClaw。  
**状态**：已完成（2026-09-29）。

**模块**：

- `internal/lobby/model/catalog.go`
- `internal/lobby/model/session.go`
- `internal/lobby/repository/catalog*.go`
- `internal/lobby/database/migrations/`

**任务**：

- 新建 `agent_profiles`、`agent_revisions`、`agent_skill_bindings`、必要的
  `session_agent_snapshots`。
- Agent revision 保存 display metadata、system prompt、model/provider ref、
  `requested_toolsets`、`allowed_tools`、`denied_tools`、Skill binding、permission
  mode、turn/budget、delegation policy 和 revision hash。
- 不保存 Hermes Agent 实例、transcript、provider client、workspace、runtime
  `valid_tool_names`、lease/epoch/process ID 或 Skill 正文。
- Agent revision 的原子工具权限必须引用 T-03 的 catalog revision；Skill 必须引用
  S-02 的 Skill revision。

**验收**：Agent revision 可以独立发布、审计和回滚；同一 profile 的多个 revision
  不互相修改；不存在旧 `tools_json`/`skills_json` 作为新模型必填字段。

**完成记录（2026-09-29）**：

- 新增 migration 025：`agent_profiles`、`agent_revisions`、`agent_revision_tools`、`agent_revision_skills` 和 `session_agent_snapshots`；新模型不保存 Hermes Agent 实例、transcript、provider client、workspace 或 lease/epoch。
- Agent revision 保存 display metadata、system prompt、model/provider ref、requested toolsets、permission mode、turn budget、delegation policy 和稳定 `revision_hash`；工具授权通过 T-03 `capability_tool_revisions` 外键引用，Skill 通过 S-02 `skill_revisions` 外键引用。
- 新增 `AgentRepository` PostgreSQL 实现，revision 与工具/Skill 绑定使用单事务写入；读取支持完整 revision projection，profile 的多个 revision 互相独立。
- 新增 PG round-trip/FK 回滚测试，验证 profile/revision 持久化、稳定 hash、未知工具拒绝和失败事务无残留。旧 `catalog_agents.tools_json/skills_json` 仍只作为迁移输入，未进入 A-01 新模型。
- 验证：NetworkClaw `go test ./internal/lobby/model ./internal/lobby/repository ./internal/lobby/usecase ./internal/lobby/transport/http`、`go test ./...` 和 `git diff --check` 通过；未修改 Harness vendor。

**下一步**：进入 **A-02 Agent API 和 Lobby usecase**，实现 profile/revision 的发布、复制、停用、查询和完整 Gateway projection。

### A-02 [P0] Agent API 和 Lobby usecase

**依赖**：A-01。  
**主责**：NetworkClaw。  
**状态**：已完成（2026-09-29）。

**模块**：

- `internal/lobby/usecase/`
- `internal/lobby/transport/http/`
- `web/src/api/agents.ts`（协议类型先更新）

**任务**：

- 实现 profile/revision 的创建、发布、复制、停用、查询和 revision hash。
- 保存 Agent 时展开 toolset 为原子工具，解析 Skill binding 和依赖状态。
- 返回“候选 toolset”“最终 allowed_tools”“Skill mode”“effective snapshot”
  的分层结果，避免前端把 toolset 当授权原子。
- 发布新 revision 只影响新 session；现有 session 使用已冻结 snapshot。

**验收**：API 拒绝未注册工具、未发布 Skill、失配 revision 和不满足依赖；可以
  生成完整可传给 Gateway 的 Agent revision projection。

**完成记录（2026-09-29）**：

- 新增 Agent profile/revision usecase 和 PostgreSQL repository 操作，支持创建、查询、列表、发布、复制和停用；revision 写入及其工具/Skill 绑定保持原子性。
- 新增管理员写入保护的 HTTP API，并装配 Lobby router/usecase；前端 `agents.ts` 增加 profile/revision 类型和请求方法。
- 发布/投影时校验 catalog version、tool/toolset revision、Skill release/trust/status/expiry 与依赖；toolset 展开为原子 `allowed_tools`，处理 deny 和 Skill mode，并生成 effective snapshot hash。
- migration 026 为 revision 固定 catalog version；revision 内容 hash 不包含发布状态，避免发布改变内容身份。
- 验证：NetworkClaw `go test ./...`、定向 Lobby 包测试、`npm run typecheck` 和 integration `git diff --check` 通过；Harness 未修改，未编辑 `vendor/hermes`。

**下一步**：进入 **A-03 Session Agent/Capability snapshots**，在 session 创建和恢复边界统一冻结 Agent、Capability、Skill snapshots。

### A-03 [P0] Session Agent/Capability snapshots

**依赖**：A-02、S-03、T-06。  
**主责**：NetworkClaw/Harness 联合。  
**状态**：已完成（2026-09-29）。

**模块**：

- NetworkClaw `internal/lobby/model/session.go`、session usecase
- Harness `runtime/context.py`、`hermes_host_adapter.py`、`host/server.py`

**任务**：

- session 创建时同时冻结 `SessionCapabilitySnapshot`、`SessionSkillSnapshot`、
  `SessionAgentSnapshot`。
- 将 snapshot hash、agent revision、tool revisions、skill revisions、provider
  route、budget 和 policy 发送到 Gateway。
- session resume 只恢复同一 snapshot；显式 replacement 才能创建新 snapshot。
- 保持 `user_id -> Gateway process` 和 `session_id -> _HermesSession`；不把
  `agent_id` 提升为进程亲和键。

**验收**：profile/Skill/catalog 发布后旧 session 行为不变；Gateway 进程内多个
session 的 snapshot、workspace、runtime、Agent cache 和事件流互不串联。

**完成记录（2026-09-29）**：

- 新增 `SessionCapabilitySnapshot`、`SessionSkillSnapshot`、`SessionAgentSnapshot`，会话创建时从已发布 Agent revision 解析并冻结 toolset/tool revision、原子 allowed/denied tools、Skill revision/dependency、Agent revision projection、budget 和 policy。
- migration 027 新增 capability snapshot 持久化；Agent snapshot 使用既有 `session_agent_snapshots`，会话写入与三类 snapshot 在同一事务中完成，读取和列表恢复完整冻结事实。
- Harness host grant 和 chatrtmgr gRPC 协议透传三类 snapshot 及 hash；Host Adapter 校验三者身份、hash、catalog/allowed tools 一致性，并把 snapshot identity 纳入 session Agent cache route。
- session resume 保持同一 snapshot；snapshot 变化必须显式 replacement admission。保留 `user_id -> Gateway process` 和 `session_id -> _HermesSession` 的隔离模型。
- 新增 Go session/repository 测试、Harness host/adapter 回归和跨进程双 session 隔离测试；未修改 `vendor/hermes`。
- 验证：NetworkClaw `go test ./...`、Harness 定向 pytest、前端 `npm run typecheck`、Python `py_compile` 和三仓 `git diff --check` 通过。

**下一步**：进入 **A-04 Gateway Agent projection 和 Agent cache route**，把冻结 Agent projection 的 model/provider、tool/Skill snapshot、budget、permission 和 delegation policy 接入 Hermes 初始化与诊断。

### A-04 [P0] Gateway Agent projection 和 Agent cache route

**依赖**：A-03。  
**主责**：Harness。  
**状态**：已完成（2026-09-29）。

**模块**：

- `src/networkclaw_harness/runtime/hermes_host_adapter.py`
- `src/networkclaw_harness/host/server.py`
- `src/networkclaw_harness/runtime/context.py`
- `vendor/hermes/agent/agent_init.py`

**任务**：

- 将 Agent revision 的 model/provider/profile、toolset、atomic grant、Skill
  snapshot、budget、permission 和 delegation policy 映射到 Hermes Agent 初始化。
- cache route 包含 agent revision hash、capability hash、skill snapshot hash 和
  provider route；变化只驱逐目标 session 的 Agent。
- Hermes Agent 继续负责 schema 选择、工具调用、turn、取消、steer、delegation 和
  上下文生命周期；Gateway 不实现第二套 loop。
- 通过 `valid_tool_names` 和 snapshot hash 暴露诊断信息。

**验收**：同一 Agent revision 可用于多个独立 session；任一 session 的配置变化不
影响其他 session；模型、工具、Skill 和预算变更都可观察且不会复用旧 schema。

**完成记录（2026-09-29）**：

- Harness `HermesHostAdapter` 解析 A-03 的 Agent snapshot projection，将 system prompt、model/provider ref、permission mode、delegation policy、toolset/atomic grant、Skill snapshot 和 budget 映射到 Hermes Agent 初始化；没有引入第二套 Agent loop。
- Agent cache route 纳入 Agent revision hash、Agent snapshot hash、Capability snapshot hash、Skill snapshot hash、permission/delegation policy、provider route、catalog/tool grant 和 budget；任一 session 变化只驱逐该 session 的 Agent。
- `turn.started` 诊断暴露 `valid_tool_names`、catalog 与四类 snapshot hash、permission mode 和 delegation policy hash；provider selection 与冻结 model/provider projection 不匹配时拒绝。
- Host/Adapter 回归覆盖多 session 隔离、projection 驱动初始化、预算与 schema cache 重建；未修改 `vendor/hermes`。
- 验证：NetworkClaw Lobby/chatrtmgr/chatsvc 定向 Go 测试、Harness host/adapter pytest、Python `py_compile` 和三仓 `git diff --check` 通过。

**下一步**：进入 **A-05 Delegation、permission 和 policy 接入**，统一 parent/child delegation policy、child budget 及 tool/Skill grant 的跨 Gateway 约束。

### A-05 [P0] Delegation、permission 和 policy 接入

**依赖**：A-04。  
**主责**：Harness/NetworkClaw 联合。  
**状态**：已完成（2026-09-29）。

**模块**：

- Harness `vendor/hermes/tools/delegate_tool*`、Agent delegation/runtime 模块
- `hermes_host_adapter.py`、Host Protocol delegation fields
- NetworkClaw Agent revision/usecase policy 字段

**任务**：

- 将 Agent revision 的 delegation policy、child budget、tool/Skill grant 传给 child
  session 的配置选择。
- 保持 parent/child session、allocation、agent revision 和 capability snapshot
  lineage。
- 子 Agent 仍由 Hermes supervisor/runtime 派遣；NetworkClaw 只负责授权、亲和、lease
  和事件传输。

**验收**：双 child、child tool、child Skill、deny、timeout、failure 和 retry 过程
  均保留 canonical delegation/subagent/tool 事件；越权工具调用 fail closed。

**完成记录（2026-09-29）**：

- Harness `HostDelegationBroker` 现在接收 Agent projection 的 `delegation_policy`，在 child grant 解析前执行 `max_depth` 和 `child_budget` 上限校验；拒绝会唤醒等待线程并发出 canonical `delegation.resolved` deny 事件。
- Child grant 映射携带 parent/child session、turn、generation、allocation、lease、budget 和三类 snapshot。Harness 对 child toolset、原子工具和 Skill 执行 parent grant 子集校验，投影 Agent/Skill prompt，并通过 `upstream/patches/0004-host-child-capability-grant.patch` 与 vendor sync 让 Hermes child 使用授权的工具面；无独立 host broker 的嵌套 `delegate_task` fail closed。
- `HermesHostAdapter` 将 policy 绑定到每个 session broker，并继续通过 Hermes `delegate_task` 的 host allocation hook 创建独立 child runtime、tool session 和 workspace；child 资源在 batch 结束或失败时释放。
- NetworkClaw Gateway 从已准入 parent binding 派生独立 child session/workspace/lease，限制 child budget 与 capability/Skill snapshot 子集；外部 `delegation.resolve` 不能自行扩大授权，并保留 canonical child lineage。
- 验证：Harness `.venv/bin/python -m pytest -q` 全量通过；vendor sync/verify 通过；NetworkClaw `go test ./...`、`go test ./tests/integration/harnessinterop -count=1`（含双 child、child tool/Skill、deny、timeout、failure/retry、canonical event/replay）通过；Web `npm run typecheck`、三仓 `git diff --check` 通过。

### A-06 [P0] Agent 前端配置和有效权限视图

**依赖**：A-02、A-03、A-05。  
**主责**：NetworkClaw Web。  
**状态**：已完成（2026-09-29）。

**模块**：

- `web/src/pages/Agents.tsx`
- `web/src/api/agents.ts`
- `web/src/pages/Skills.tsx` 及共享 capability 组件

**任务**：

- 用 profile/revision 视图替换旧的扁平 Agent JSON 编辑。
- Toolset 用于批量勾选，原子工具显示最终展开、deny 和 unavailable 状态。
- Skill 显示 revision、auto/explicit/disabled、依赖 Tool/Toolset 和 trust 状态。
- 显示有效权限计算：`loaded tools ∩ Agent grant ∩ Host grant ∩ turn allowed`。
- 显示当前 session snapshot 与 profile 最新 revision 的差异，避免误导为即时变更。

**验收**：前端配置可保存为可审计 revision；用户能看出“未加载”“未授权”“本轮
禁用”和“运行环境不可用”的区别；启动对局后显示实际 snapshot/hash。

**完成记录（2026-09-29）**：

- Web Agents 页面新增 profile/revision workspace：支持 revision 选择、草稿保存、发布和复制前的审计快照展示；旧扁平 Agent CRUD 保持兼容。
- Toolset 支持批量勾选并展开 Hermes 原子工具；不可用工具禁用，effective permission 视图区分 `allowed`、`not_loaded`、`not_granted`、`turn_disabled` 和 `unavailable`。
- Revision 保存携带 Skill binding 的 revision、mode、依赖配置和 position；Skill binding 继续复用既有 catalog/trust 数据边界。
- Session 选择器读取真实 session snapshot/hash，并明确标识与所选 profile revision 一致或存在差异；发布只对新 session 生效。
- 验证：NetworkClaw Web `npm run typecheck`、`npm test -- --run src/lib/agentPermissions.test.ts`、`npm run build` 通过；`git diff --check` 通过。

### A-07 [P0] Agent 全链路验收

**依赖**：A-05、A-06。  
**主责**：Integration；三仓联合。  
**状态**：已完成（2026-09-29）。

**验收场景**：

- Lobby 创建 Agent revision：`coding` + `networkclaw`、若干 Skill、模型/provider、
  delegation policy 和预算。
- chatrtmgr 按 `user_id` 复用 Gateway；Gateway 为多个 `session_id` 创建独立
  Hermes runtime/Agent cache。
- 主 Agent 触发工具、Skill explicit load、两个子 Agent 和子 Agent 工具调用。
- 修改 profile/revision 后创建新 session；旧 session 继续使用原 snapshot。
- 验证 lease/fence、cancel/steer、provider retry、tool deny、Skill dependency
  failure、child failure/timeout 和事件 replay。
- web2 根据 canonical events 重建主任务、子任务、工具、Skill 相关过程和终态。

**完成记录（2026-09-29）**：

- 运行 `make integration-test` 完成三仓真实组合验收；`.integration-state/evidence/combination-matrix.json` 状态为 `passed`，13 个场景全部通过，清理状态为 `clean`。
- 验收覆盖 Agent revision/session snapshot 发布隔离、Skill auto/explicit/disabled 与依赖失败、tool deny、model/provider stream/retry/interruption、双 child delegation 的 grant/deny/timeout/failure 和 child tool 事件。
- 验收覆盖 user/session Gateway 复用与多 session 隔离、cancel/steer、lease/fence、request replay/hash conflict、parent/child interrupt scope、EOF/backpressure 和 exactly-once release。
- `frontend-process-ledger` 使用 canonical events 重建主任务、子任务、工具、Skill、计划和终态；`durable-child-replay-restart` 验证 replay 与重启后的 child authority。
- 详细证据见 [`docs/evidence/a07-agent-vertical-acceptance.md`](../evidence/a07-agent-vertical-acceptance.md)。

## 7. 收尾任务

### X-01 [P0] 删除旧运行时模型和兼容读取路径

**依赖**：T-07、S-06、A-07。  
**主责**：NetworkClaw；Harness 配合清理固定配置。  
**状态**：已完成（2026-09-29）。

**任务**：

- 删除或停用 `CatalogAgent`、`CatalogSkill`、`CatalogTool` 及其运行时读取路径。
- 删除 `skills_json`、`tools_json`、chatsvc `fullScopeJSON()` 等旧事实源；保留一次性
  导入工具和历史只读说明即可。
- 删除 Harness 中固定 toolset 默认值，所有生产 session 必须来自 snapshot/projection。
- 更新迁移、API、前端和文档，确保不存在双写双读。

**验收**：新部署从空库启动只使用新模型；旧数据导入后可生成新 revision，但运行时
不回读旧表；grep/静态检查无生产调用点。

**完成记录（2026-09-29）**：

- Lobby session/routing 已改为使用冻结 Agent/Capability snapshot；旧 `catalog_agents` persona/tool 读取不再注入生产 use case。
- 旧 `/catalog` CRUD 路由停用；新的 profile/revision、Skill revision 和 capability catalog API 保留为配置入口。
- chatsvc 将旧 `fullScopeJSON` 语义改为编译期 `runtimeToolManifestJSON` inventory，授权仍由 session snapshot 和每轮 `allowed_tools` 决定。
- NetworkClaw `go test ./...`、目标包测试和 `git diff --check` 通过。详细证据见 [`docs/evidence/x01-legacy-runtime-retirement.md`](../evidence/x01-legacy-runtime-retirement.md)。

### X-02 [P0] Bundle、schema drift 和交付验收

**依赖**：X-01。  
**主责**：Integration。  
**状态**：已完成（2026-09-29）。

**任务**：

- 将三类 revision/snapshot schema、Harness inventory、Go API 和 Web 类型加入
  bundle/provenance。
- 增加 capability catalog drift、snapshot hash、旧字段禁用和跨仓版本检查。
- 在 Mac 开发环境和 Ubuntu 22.04 amd64 CI 验证空库迁移、旧数据一次性导入、Gateway
  启动、真实 provider stub、事件过程树和清理。
- 更新 `doctor`、`test`、`integration-test`、`bundle`、`verify-bundle` 的入口说明。

**验收**：隔离 bundle 不依赖原始绝对路径；三仓树 hash、Harness vendor hash、
catalog/revision schema version 可追溯；组合测试和失败清理结果写入 evidence。

**完成记录（2026-09-29）**：

- 生成 X-02 bundle 并通过 manifest/checksum 验证；manifest 追踪三仓 tree/commit/dirty/diff、Harness vendor tree、Hermes patch、Host Protocol 版本和 Ubuntu 22.04/amd64 target。
- capability snapshot、Skill manifest、Hermes inventory/catalog、事件/Host Protocol schema、Go API 和 Web 类型均进入 bundle；catalog projection、schema/hash drift 和旧字段禁用 gate 通过。
- 隔离 bundle self-test 13/13 阶段通过，覆盖 archive safety、locked dependency、doctor、Harness tests、Integration tests、组合矩阵、manifest verify、bundle rebuild/verify；失败列表为空且 workspace 已清理。
- 详细证据见 [`docs/evidence/x02-delivery-acceptance.md`](../evidence/x02-delivery-acceptance.md)。

## 8. 可并行工作

以下并行只在共同依赖完成后进行，不能改变主发布顺序：

| 前置完成 | 可并行任务 | 说明 |
|---|---|---|
| C-00 | T-01 的 inventory fixture、C-00 的 schema review | 不修改运行时 |
| T-02 | T-03 API 草稿、T-04 registry projection 实现 | T-03 进入验收前必须依赖真实 schema |
| T-05 | T-06 的 cache 测试和 T-07 fixture 编写 | 运行时验收仍等 T-06 完成 |
| T-07 | S-01 manifest、Skill 前端信息架构 | Skill 运行时接入仍等 S-03 |
| S-02 | S-03 dependency resolver、S-05 API/UI | S-03 验收需要数据库 binding |
| S-06 | A-01 Agent schema review、A-02 API 草稿 | Agent runtime 不得提前进入共享验收 |
| A-03 | A-04 Gateway projection、A-06 UI | 两者都必须使用同一 Agent snapshot contract |
| A-05 | A-06 UI polish、A-07 fixture 编写 | A-07 仍需两者都完成 |

并行任务提交时必须注明使用的 contract/revision 版本；如果 contract 变更，相关
fixture 和 schema hash 必须重新生成。

## 9. 完成定义

本计划只有同时满足以下条件才算完成：

1. Lobby 持久化以 Tool/Toolset、Skill revision、Agent profile/revision 和三个
   session snapshot 为唯一运行时事实源。
2. Harness Gateway 能按 session 加载 Hermes toolset，按原子工具授权，并把 Skill 和
   Agent revision 投影给现有 Hermes Agent/runtime。
3. Hermes Agent 的 schema 选择、参数生成、工具执行、turn、取消、steer、delegation
   和上下文生命周期没有被 NetworkClaw 重写。
4. profile/catalog 发布不会修改已有 session；多 session 在一个 Gateway 进程内完全
   隔离。
5. 前端可以清楚区分 toolset 批量配置、原子工具授权、Skill 加载模式、Agent revision
   和当前 session snapshot。
6. canonical tool/plan/delegation/subagent 事件能够重建包含子 Agent 派遣、工具进度、
   Skill 加载和失败终态的真实过程。
7. 旧 catalog/JSON 字段只作为一次性迁移输入，不存在生产双读；三仓组合测试、bundle
   隔离验证和 drift 检查全部通过。

## 10. 下一步

下一项是 **发布准备与生产切换评审**。X-02 已完成；正式 release 仍需使用 clean 三仓 lock 和目标 Ubuntu 22.04/amd64 CI provenance。
