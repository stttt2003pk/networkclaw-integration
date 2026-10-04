# Hermes Capability 前端实施计划

## 1. 计划定位

本文是 [Hermes Capability 前端重做设计](../architecture/hermes-capability-frontend-design.md)
的执行拆分，沿用 [Hermes Capability 重建计划](hermes-capability-rebuild-plan.md)
的依赖和验收风格。

本计划只覆盖 `NetworkClaw/web2` 和必要的前端契约验证，不在 Integration 中复制
Go/Harness 业务代码。`NetworkClaw/web` 是原作者工程，仅作为只读参考，不纳入本计划的
开发、构建、测试或交付范围。前端不实现 Agent loop、tool resolver、Skill dependency
resolver 或授权计算；这些结果由 Lobby、Gateway 和 Harness 提供。

**目录决策（2026-09-29）**：本计划涉及的前端源码、依赖、构建产物、测试和浏览器验收
全部在 `NetworkClaw/web2` 完成。`NetworkClaw/web` 不执行安装、修改、启动、构建或测试；
其中的引用仅用于读取原作者实现和行为对照。

**实施目录矩阵**：

| 目录 | 用途 | 本计划是否允许修改、构建或测试 |
|---|---|---|
| `../NetworkClaw/web2` | 唯一前端开发、构建和测试目录 | 是 |
| `../NetworkClaw/web` | 原作者工程，只读参考和行为对照 | 否 |
| `../networkclaw-integration` | 计划、契约记录和跨仓验证入口 | 仅文档与集成验证 |

**本次范围校正**：本计划的所有前端模块、代码修改、依赖操作、启动、构建、测试和浏览器验收，
统一归属于 `../NetworkClaw/web2`。`../NetworkClaw/web`
不属于任何任务的实施目录；后文若引用它，只表示读取原作者代码作行为对照。

**工程范围约束**：所有前端实现、修改、依赖安装、构建、测试和交付文件都必须位于
`../NetworkClaw/web2`。`../NetworkClaw/web`
只允许用于阅读原作者实现和行为参考；不得在其中新增、修改、安装依赖、启动服务、构建、测试或验证本计划任务。
计划中出现 `NetworkClaw/web` 的地方均表示只读参考，不表示并行开发目标。

前置后端能力来自主计划：

| 前置任务 | 前端使用的能力 |
|---|---|
| C-00 | capability/revision/snapshot schema、hash 和错误语义 |
| T-03/T-06 | toolset 展开、原子 grant、effective capability snapshot |
| S-03/S-05 | Skill revision、依赖解析、binding mode 和 skill snapshot |
| A-02 | Agent profile/revision API、发布和 projection |
| A-03 | Session Agent/Capability/Skill snapshot |
| A-05 | delegation policy、child grant 和 lineage |

如果这些前置 API 的字段发生变化，必须先更新本计划的 FE-01 契约审计，再继续后续
页面任务。

## 2. 目标和非目标

### 2.1 目标

完成四条前端闭环：

```text
Capability Catalog
    -> Agent draft/revision
    -> Published revision
    -> Session snapshot
    -> Runtime tool/skill activity
```

用户必须能够区分：

- Catalog 中存在但 Agent 未授权的工具。
- Agent 已授权但当前 runtime 未加载的工具。
- 环境不可用或 revision 已退役的工具。
- Skill 的 `auto_load`、`explicit`、`disabled` 三种模式。
- profile/revision 配置和当前 Session 的冻结 snapshot。

### 2.2 非目标

- 不在浏览器重新展开 toolset 或计算最终授权。
- 不把 Skill 正文复制进 Lobby Agent revision。
- 不在运行中 Session 直接修改能力权限。
- 不继续向新模型写入 `tools_json`、`skills_json` 或旧 `/catalog/agents`。
- 不修改 `networkclaw-harness/vendor/hermes`。

## 3. 总依赖图

```text
FE-01 前端契约审计
  -> FE-02 API client 与状态基础
      -> FE-03 Capability Catalog 只读页面
          -> FE-04 Agent revision workspace
              -> FE-05 Skill binding 与依赖校验 UI
                  -> FE-06 Review / Publish / Revision diff
                      -> FE-07 Session revision picker / snapshot view
                          -> FE-08 Runtime capability drawer / activity
                              -> FE-09 web2 旧写入口收口
                                  -> FE-10 浏览器验收与交付门禁

FE-02 -> FE-03、FE-04 的类型和查询基础
FE-03 -> FE-04 的目录选择器
FE-05 -> FE-06 的发布前依赖摘要
FE-06 -> FE-07 的 published revision 选择
FE-07 -> FE-08 的 snapshot identity
FE-08 -> FE-09 的事件和新模型事实源
```

任务按依赖顺序排列。只有标记为“可并行”的任务可以在共同前置完成后并行实施。

## 4. 任务清单

### FE-01 [P0] 前端契约审计和旧入口盘点

**依赖**：C-00、T-03、T-06、S-05、A-02、A-03、A-05。  
**主责**：`NetworkClaw/web2`；Go/Harness 维护者评审响应字段。  
**状态**：已完成（2026-09-29）。

**模块**：

- `NetworkClaw/web2/src/pages/agent-skill-tool/AgentsSection.tsx`
- `NetworkClaw/web2/src/api/catalog.ts`

**任务**：

- 对账 Agent profile/revision、Skill binding、catalog、三类 session snapshot 和
  runtime event 的实际 JSON 字段。
- 标记旧字段、兼容字段和新字段，建立前端禁止依赖字段清单。
- 记录每个接口的读写权限、错误码、分页/排序和 optimistic update 限制。
- 确认 snapshot hash 是服务端事实，前端只展示和比较，不重新计算授权。
- 将 `auto` 等旧 Skill mode 在读取端归一化为 `auto_load`，写入只允许新枚举。

**产物**：

- `docs/contracts/` 的前端消费字段表或本计划附录更新。
- 前端 API endpoint/type checklist。
- 旧写入口清单和迁移删除顺序。

**验收**：所有后续页面需要的字段都有唯一来源；不存在一个前端字段同时映射两个
  语义不同的后端字段；旧 `tools_json`/`skills_json` 被标记为禁止新写入。

**完成记录（2026-09-29）**：

- 新增 [hermes-capability-frontend-consumption-v1.md](../contracts/hermes-capability-frontend-consumption-v1.md)，记录 Catalog、Tool revision、Skill revision、Agent revision、三类 Session snapshot 和 canonical event 的前端消费字段、枚举及错误映射。
- 对照 `schemas/capability-snapshot-v1.schema.json`、`docs/contracts/capability-snapshot-v1.md` 和 Web2 当前实现完成字段审计；确认 C-00 是新模型唯一契约来源。
- 确认 Web2 当前仍使用旧 `CatalogAgent`、`skills_json`、`tools_json`、`/catalog/agents`、`agent_id` 和 `scope_json`；这些入口已列入 FE-09 收口，不得在新页面继续扩展。
- 确认新 Agent revision、Skill binding、Session snapshot API 尚未在 Web2 实现，后续必须先由 FE-02 建立类型、query key 和错误映射。
- 确认 `NetworkClaw/web` 仅作为原作者只读参考，不属于开发、构建、测试或交付范围。

**下一步**：进入 **FE-02 API client、类型和查询状态基础**；先按前端消费字段表建立新模型类型和状态边界，再接入 FE-03/FE-04 页面。

### FE-02 [P0] API client、类型和查询状态基础

**依赖**：FE-01。  
**主责**：`NetworkClaw/web2`。  
**状态**：已完成（2026-09-29）。

**模块**：

- `NetworkClaw/web2/src/api/capabilityCatalog.ts`（新增）
- `NetworkClaw/web2/src/api/agents.ts`
- `NetworkClaw/web2/src/api/skillCatalog.ts`
- `NetworkClaw/web2/src/api/sessions.ts`（新增或收敛现有 session API）
- `NetworkClaw/web2/src/api/snapshots.ts`（新增，若 snapshot 接口不适合放入 sessions）
- `NetworkClaw/web2/src/types/` 或现有类型目录

**任务**：

- 定义 `AgentProfile`、`AgentRevision`、`AgentToolGrant`、`AgentSkillBinding`、
  `CapabilityCatalogEntry`、`SessionAgentSnapshot`、`SessionCapabilitySnapshot`、
  `SessionSkillSnapshot`、`EffectivePermission`、`ToolInvocation`。
- 为 catalog、revision、session snapshot 和 runtime event 建立稳定 query key。
- 统一 `unknown`、`unavailable`、`not_loaded`、`denied`、`stale_revision` 错误展示
  所需的类型守卫和 reason code 映射。
- 统一 loading、empty、stale、forbidden、validation error 和 network error 状态。
- API client 不提供让页面自行修改 snapshot 或自行提交最终授权的便捷方法。

**验收**：

- `npm run typecheck` 通过。
- API 类型可以覆盖 C-00 fixture 和 A-02/A-03 响应。
- 旧 API 写入路径不会被新页面导入。

**完成记录（2026-09-29）**：

- 新增 `NetworkClaw/web2/src/types/capability.ts`，覆盖 Catalog、Tool/Skill revision、Agent profile/revision、Agent binding、三类 Session snapshot、effective permission、Tool invocation 和 C-00 reason code；保留服务端 `revision_hash`/`snapshot_hash` 原值。
- 新增 `NetworkClaw/web2/src/api/capabilityCatalog.ts`、`NetworkClaw/web2/src/api/agents.ts`、`NetworkClaw/web2/src/api/snapshots.ts`，分别建立 catalog、revision/draft/publish 和 session snapshot 的薄 client 及稳定 query key；未提供旧 `/catalog/agents` 或 snapshot 修改接口。
- 新增 `NetworkClaw/web2/src/lib/capabilityErrors.ts`，将 403、validation、stale revision、network 等状态与 C-00 reason code 分开映射。
- 新增 `NetworkClaw/web2/src/api/capability.test.ts`，验证 reason code 守卫和 forbidden/stale 错误分类；新模块没有导入旧 `catalog.ts` 写入 API。
- Web2 当前后端尚未提供新 capability 路由，因此 client URL 作为 Lobby 新契约占位，FE-03/FE-04 接入前必须以实际路由响应 fixture 对账，不从旧接口拼装新对象。
- 验证：`cd ../NetworkClaw/web2 && npm run typecheck`、`npm test -- --run src/api/capability.test.ts`、`npm run build` 均通过；构建仅有既有 chunk size warning。

**下一步**：进入 **FE-03 Capability Catalog 页面**；先实现 Web2 的 Skills、Toolsets、Atomic Tools 只读 master-detail 页面，消费 FE-02 类型和 catalog client。

### FE-03 [P0] Capability Catalog 页面

**依赖**：FE-02。  
**主责**：`NetworkClaw/web2`。  
**状态**：已完成（2026-09-29）。

**模块**：

- `NetworkClaw/web2/src/pages/CapabilitiesPage.tsx`
- `NetworkClaw/web2/src/components/capabilities/`
- `NetworkClaw/web2/src/api/capabilityCatalog.ts`
- 共享搜索、分页、master-detail 和状态组件

**任务**：

- 实现 Skills、Toolsets、Atomic Tools 三个 tab；Connectors 保留已有能力但不混入
  Agent grant 语义。
- 采用 Hermes 的 master-detail 布局：列表支持搜索、排序和状态过滤，详情显示
  revision、source、availability、schema/content hash 和依赖。
- Toolset 详情在 API 返回 membership 时展开原子工具；Atomic Tools 显示所属 toolset 和 grant policy 的来源。若当前 API 不返回 membership，由 FE-03 明示数据边界，不自行拼接或推断。
- Skill 详情显示 release/trust/platform/dependency 状态，不把正文当作 tool schema。
- 提供 profile/connection scope selector 时，明确当前读取的后端范围；scope 变化
  后丢弃旧详情和 pending write。
- 先实现只读页面；需要写操作时必须使用新 revision/binding API。

**验收**：

- 能浏览 catalog 和 Skill 依赖；Toolset membership 仅在 API 提供时展开。
- 能明确区分 catalog availability 与 Agent grant。
- scope 切换不会把旧 profile 的详情或 pending mutation 写入新 profile。
- 页面不请求旧 `/catalog/agents` 作为能力来源。

**完成记录（2026-09-29）**：

- 在 `NetworkClaw/web2` 新增 `/capabilities` 页面和侧栏入口，提供 Skills、Toolsets、Atomic Tools 三个只读 tab、目录版本选择、搜索、状态过滤、排序及 master-detail 详情。
- 展示 Skill release/trust/platform/dependency/hash、Toolset revision/source/status 和 Atomic Tool availability/status/schema hash；明确 Catalog availability 不等于 Agent grant。
- 对后端未返回的 Toolset membership/Atomic Tool 所属 Toolset 直接标示“响应未提供”，不从旧模型推导；grant policy 指向 Agent revision 事实来源。
- FE-03 页面无 profile/connection selector 和 pending mutation；仅在后续引入 scope selector 或 mutation 时应用 scope 隔离要求。
- 页面仅调用 `GET /catalog/skills/revisions`、`GET /catalog/{version}/toolsets` 和 `GET /catalog/{version}/tools`，不依赖旧 `/catalog/agents`。
- 新增 catalog client MSW 覆盖，验证 skills/toolsets/tools 响应解包、版本路径转义和平台查询参数。
- 验证：在 `../NetworkClaw/web2` 执行 `npm run typecheck`、`npm test`、`npm run build`、`git diff --check` 均通过；测试为 328 passed、1 skipped。构建有既有大 chunk 警告。

**下一步**：进入 **FE-04 Agent Profile 和 Draft Revision workspace**；先对账 A-02 实际 profile/revision API，再实现列表、草稿编辑和服务端保存，不把前端计算结果当作授权事实。

### FE-04 [P0] Agent Profile 和 Draft Revision workspace

**依赖**：FE-02、FE-03、A-02。  
**主责**：`NetworkClaw/web2`。  
**状态**：已完成（2026-09-29）。

**模块**：

- `NetworkClaw/web2/src/pages/Agents.tsx`
- `NetworkClaw/web2/src/api/agents.ts`
- `NetworkClaw/web2/src/api/capabilityCatalog.ts`
- `NetworkClaw/web2/src/types/capability.ts`

**任务**：

- 用 profile 列表、published revision、draft revision、revision hash 替代扁平 Agent
  JSON 编辑。
- 实现 `Identity & Runtime` 步骤：display metadata、system prompt、model/provider、
  permission、turn budget、delegation policy、child budget 和 max depth。
- 实现 `Tool Surface` 步骤：选择 requested toolsets，展示服务端展开的 atomic tools，
  允许草稿中的 deny 配置。
- toolset 是批量选择入口；保存时保留 tool revision 引用和显式 denied tools。
- 草稿编辑和页面切换不应触发 published revision 或现有 Session 变化。
- 支持取消、恢复 draft、刷新冲突提示和服务端 validation error。

**验收**：

- 可创建/读取 profile 和 draft revision。
- 可选择 toolset 并看到原子工具展开、revision、availability/status 和 unavailable 原因。
- 草稿可保存但不影响 published revision。
- 页面不会将浏览器端计算的 `allowed_tools` 当作服务端授权结果。

**完成记录（2026-09-29）**：

- 仅在 `NetworkClaw/web2` 新增 `/agents` workspace、Agents 侧栏入口和 Agent API/catalog grant client；`NetworkClaw/web` 保持只读参考，未参与开发、构建或测试。
- 实现 profile 列表和创建、revision 列表及 hash 展示、published/draft 状态查看；published revision 不直接编辑。
- 按实际 A-02 路由使用 `POST /agents/revisions/{profile_id}/{revision}/copy` 创建 draft，保存通过 `POST /agents/revisions/{profile_id}` 创建新的不可变 draft revision；没有引入不存在的 PUT draft 接口。
- workspace 覆盖 system prompt、display metadata、model/provider、catalog version、permission mode、turn budget、delegation policy，以及 requested toolsets 和显式 denied atomic tools。
- Tool Surface 通过 `POST /catalog/grants` 获取服务端 `allowed_tools` 与 `snapshot_hash` 后展示；浏览器不计算最终授权，也不把 grant snapshot 当作 revision 授权事实。显式 deny 仅作为 revision `tools[].decision` 提交。
- Tool Surface 同时读取 catalog tool 的 `availability`/`status`，对 unavailable 工具显示原因并禁止配置 deny；Tool revision 引用使用 catalog 返回值，不由浏览器猜测。
- 将 API 错误分类为 stale revision、validation、forbidden 和 network；stale revision 时提供刷新 revisions 操作，刷新只更新服务端 revision 列表，不自动覆盖当前 draft 内容。
- 已验证：`cd ../NetworkClaw/web2 && npm run typecheck`；`npm test`（331 passed、1 skipped）；`npm run build`；`git diff --check`；构建仅保留既有 chunk size warning。
- 已知边界：FE-04 尚未接入 Skill binding 编辑、publish/review 操作和 session snapshot；Tool revision 列表与 availability/status 由 catalog API 提供，Agent API 的 MSW 覆盖仍需在后续测试门禁补齐。

**下一步**：进入 **FE-05 Skill binding、mode 和依赖状态**，在现有 draft workspace 中接入 Skill revision、`auto_load`/`explicit`/`disabled` 模式和服务端依赖校验结果。

### FE-05 [P0] Skill binding、mode 和依赖状态

**依赖**：FE-03、FE-04、S-05。  
**主责**：`NetworkClaw/web2`。  
**状态**：已完成（2026-09-29）。

**模块**：

- `NetworkClaw/web2/src/components/agents/AgentSkillBindings.tsx`
- `NetworkClaw/web2/src/components/capabilities/DependencyResult.tsx`
- `NetworkClaw/web2/src/pages/Skills.tsx`
- `NetworkClaw/web2/src/api/skillCatalog.ts`

**任务**：

- 在 revision workspace 中选择 Skill revision，保存 `skill_id`、revision、mode 和
  config reference。
- mode 只允许 `auto_load`、`explicit`、`disabled`；读取兼容旧 `auto` 并立即归一化。
- 展示 required toolsets/tools、缺失 grant、not loaded、unavailable、untrusted、
  inactive、expired 和 platform restriction。
- `auto_load` 显示 prompt 注入预览元数据；`explicit` 显示 `skill_view` 是否授权；
  `disabled` 显示不会注入或建议调用。
- 保存完整 binding 集合，避免逐条 mutation 造成半套配置。

**验收**：

- 三种 mode 在编辑、读取和错误状态中可区分。
- Skill 依赖失败不会被显示为“工具不可用”这一单一错误。
- binding 保存只提交 revision 引用和配置，不提交 Skill 正文。
- 页面能显示新 Session 生效边界。

**完成记录（2026-09-29）**：

- 仅在 `NetworkClaw/web2` 的 Agent draft workspace 接入 Skill revision binding；保存完整
  binding 集合，字段包含 `skill_id`、`skill_version`、`mode`、`config` 和 `position`，不提交
  Skill 正文；增加配置 JSON 编辑和可见的 config reference。
- mode 仅写入 `auto_load`、`explicit`、`disabled`；读取旧值或非法值时归一化为
  `auto_load`。三种模式分别显示 prompt injection metadata、`skill_view` 授权状态和不会注入/建议调用。
- 依赖状态按服务端事实拆分为缺失依赖、未请求导致的 not loaded、missing grant、目录或工具
  unavailable、release/trust/status/expired，以及 Skill 声明的 platform/session platform 要求；
  未伪造浏览器运行态 loaded，明确由新 Session snapshot 决定。显式模式仅根据服务端
  `allowed_tools` 中的 `skill_view` 判断 granted/missing/unknown。
- `resolveCapabilityGrant` 返回的 `allowed_tools` 和 `snapshot_hash` 传入 Skill binding 组件；
  grant 请求未完成时清空旧状态，避免展示过期授权。
- 新增 `src/api/skillCatalog.test.ts`，覆盖 platform/session platform 查询、
  `include_unavailable`、Skill ID/version URL 编码及 revision/dependencies 解包。
- 验证命令（均在 `../NetworkClaw/web2`）：
  `npm run typecheck`；`npm test`（331 passed、1 skipped）；
  `npm test -- --run src/api/skillCatalog.test.ts src/api/capability.test.ts`（5 passed）；
  `npm run build`；`git diff --check`。构建仅有既有 chunk size warning。
- `NetworkClaw/web` 未修改、未安装依赖、未启动、未构建、未测试，仅作为只读参考。

**下一步**：进入 **FE-06 Revision diff、有效权限预览和发布**；基于 FE-05 的完整 Skill binding、
依赖状态和 grant snapshot，接入 draft/published diff、effective permission preview 与发布错误恢复。

### FE-06 [P0] Revision diff、有效权限预览和发布

**依赖**：FE-04、FE-05、A-02。  
**主责**：`NetworkClaw/web2`；Lobby API 维护者配合发布校验。  
**状态**：已完成（2026-09-29）。

**模块**：

- `NetworkClaw/web2/src/components/agents/AgentRevisionReview.tsx`
- `NetworkClaw/web2/src/components/agents/RevisionDiff.tsx`
- `NetworkClaw/web2/src/components/capabilities/EffectivePermissionTable.tsx`
- `NetworkClaw/web2/src/api/agents.ts`

**任务**：

- 显示 draft 与 published revision 的字段、tool grant、Skill binding 和 policy diff。
- 展示服务端返回的 effective projection：requested toolsets、allowed/denied tools、
  Skill dependency result、effective snapshot hash。
- 发布按钮在存在阻断性依赖错误时禁用，并展示服务端 reason code。
- 发布成功后刷新 profile/revision 列表，显示新 revision hash 和“仅影响新 Session”。
- 复制 revision 生成新 draft，不直接修改原 revision。
- 处理并发发布、stale draft、权限不足和发布失败后的恢复。

**验收**：

- 发布前能看到完整审计摘要。
- 未发布的 draft 不会出现在 Session revision picker。
- 发布成功后服务端返回的 hash 被原样保存和展示。
- 发布失败不会在前端显示为成功，也不会丢失 draft。

**完成记录（2026-09-29）**：

- 仅在 `../NetworkClaw/web2` 完成实现；`NetworkClaw/web` 未修改、未安装依赖、未启动、未构建、未测试，仅作为只读参考。
- 新增 `RevisionDiff`，对 draft 与 published revision 的 identity、tool grant、Skill binding 和 policy 字段进行稳定 diff；没有 published revision 时显示首个发布提示。
- 新增 `EffectivePermissionTable`，只展示服务端返回的 requested/candidate toolsets、allowed/denied tools、Skill modes、effective snapshot hash，并保留 raw effective snapshot 供依赖审计；浏览器不重新计算最终授权。
- 新增 `AgentRevisionReview` 和 Agents 页面发布流程：只有已保存且 projection 新鲜、没有阻断性 Skill 依赖错误时才允许发布；发布成功后刷新 revision 列表并原样展示服务端 `revision_hash`，明确“仅影响新 Session”。
- 发布失败保留 draft，透传 `ApiError.code`（包含 stale revision、权限不足和服务端校验 reason code），允许刷新后修复或重试；复制仍通过服务端 copy 路由生成新 draft，不修改原 revision。
- 增加 API、reason code、revision diff 和 effective projection 测试。验证结果（均在 `../NetworkClaw/web2`）：`npm run typecheck` 通过；定向测试 13 passed；全量 `npm test` 为 337 passed、1 skipped；`npm run build` 通过，仅有既有 chunk size warning；`git diff --check` 通过。
- draft 仅由 revision API 返回 `status=draft`，Session revision picker 后续必须只筛选 `status=published`；该 picker 属于 FE-07。

**下一步**：进入 **FE-07 Session revision picker 和 snapshot 展示**；只允许选择 published revision，并展示新 Session 冻结的 Agent、Capability、Skill snapshot 及 hash。

### FE-07 [P0] Session revision picker 和 snapshot 展示

**依赖**：FE-06、A-03。  
**主责**：`NetworkClaw/web2`；Session API 维护者配合响应字段。  
**状态**：已完成（2026-09-29）。

**模块**：

- `NetworkClaw/web2/src/components/sessions/AgentRevisionPicker.tsx`
- `NetworkClaw/web2/src/components/sessions/SessionSnapshotSummary.tsx`
- `NetworkClaw/web2/src/api/chat.ts`
- `NetworkClaw/web2/src/api/snapshots.ts`
- `NetworkClaw/web2/src/pages/HomePage.tsx`（创建与重开详情）
- `NetworkClaw/web2/src/pages/HistoryPage.tsx`（会话列表）

**任务**：

- 新建 Session 时先选择 profile，再选择 published revision。
- 创建请求发送 `agent_profile_id` 和 `agent_revision_id`，不以旧 `agent_id` 单独决定
  新模型运行配置。
- 创建前显示 model/provider、tool 数量、Skill mode 统计、delegation budget 和依赖
  warning。
- Session response 显示 Agent/Capability/Skill 三类 snapshot 和 hash。
- resume、fork 和 session 列表读取服务端冻结 snapshot；不使用当前 Catalog 重新推导。
- profile 发布新 revision 后，旧 Session 显示“snapshot differs”而不是自动更新。

**验收**：

- 只能选择 published revision 创建新 Session。
- 创建结果和列表结果都能显示 snapshot hash。
- resume 后 snapshot hash 不变。
- 新 revision 不改变旧 Session 的模型、工具和 Skill 状态。

**完成记录（2026-09-29）**：

- 前端仅在 `NetworkClaw/web2` 实施；原作者 `NetworkClaw/web` 只读参考，未在本任务中修改、安装、启动、构建或测试。
- 新建会话使用 `AgentRevisionPicker` 按 Profile 加载并只列出 `status=published` 的 revision；创建前展示 revision hash、model/provider、allowed tool 数、Skill mode 统计、delegation policy 和服务端依赖 warning 字段（若返回）。未选择 published revision 时不创建新 Session。
- `web2/src/pages/HomePage.tsx` 创建请求发送 `agent_profile_id` 与 `agent_revision_id=rev-N`，不再通过旧 `agent_id`/`scope_json` 创建新模型 Session；已创建会话不再提供新模型工具/Skill 临时改写。`SessionSnapshotSummary` 在创建结果、重开详情和历史列表展示服务端 Agent/Capability/Skill snapshot hash、冻结配置及与当前 published revision 的差异提示。
- 增加 fork 入口，使用 Lobby 现有幂等 fork API；跳转后通过 `getSession` 读取分支的服务端冻结 snapshot。`src/api/snapshots.ts` 改为复用真实 Session 详情接口，移除不存在的独立 `/snapshots` 请求。
- `NetworkClaw` Go 权威仓库补齐 `agent_revision_id` 请求字段与 published revision 精确选择；draft/retired 或失效 revision 被拒绝。fork 从父会话冻结内容生成分支独立的三类 snapshot，保留父 revision 内容；同步和流式消息从 Session Agent snapshot 取 model，旧 Session 不因 Profile 发布新 revision 而改变模型。Session 详情和列表继续从持久化 snapshot 读取，不用当前 Catalog 重新推导。
- 验证：`NetworkClaw/web2` 的 `npm run typecheck`、全量 `npm test -- --run`（343 passed、1 skipped）、`npm run build`、`git diff --check` 通过；构建仅有既有 chunk size warning。`NetworkClaw` 的 `go test ./internal/lobby/model ./internal/lobby/usecase ./internal/lobby/transport/http ./internal/lobby/repository` 与 `git diff --check` 通过。测试覆盖 published picker、创建请求与 hash 透传、fork API、snapshot differs、精确 revision 选择、fork 冻结内容和 model 固定。

**下一步**：进入 **FE-08 Runtime capability drawer 和 Tool/Skill activity**；以 FE-07 的 Session snapshot identity 为锚点展示 canonical event 中的工具调用和 Skill 活动，只读呈现 denied/not_loaded/unavailable 等 reason code。

### FE-08 [P0] Runtime capability drawer 和 Tool/Skill activity

**依赖**：FE-07、A-03、A-04、A-05；事件统一计划的可用 canonical event schema。  
**主责**：`NetworkClaw/web2`；Harness/Integration 提供事件样本和 replay fixture。  
**状态**：已完成。

**模块**：

- `NetworkClaw/web2/src/components/sessions/RuntimeCapabilityDrawer.tsx`
- `NetworkClaw/web2/src/components/sessions/RuntimeCapabilityDrawer.tsx` 内的
  `ToolInvocationRow`
- `NetworkClaw/web2` 会话消息流和 canonical event reducer
- `NetworkClaw/web2` 过程树/事件投影组件

**任务**：

- 顶部状态显示 Agent/revision/model/provider、granted tools 数量、Skill mode 数量和
  snapshot hash。
- Tools 面板显示 loaded、granted、unavailable、current-turn disabled 和 deny reason。
- Skills 面板显示 auto-loaded、explicit available、disabled、dependency failure 和
  stale revision。
- Snapshot 面板显示三类 hash、创建时间、replacement 状态和 parent/child lineage。
- 处理 `tool.started`、`tool.completed`、`tool.failed`、`tool.denied`、Skill
  loaded/rejected、delegation child created/resolved。
- Tool invocation 行显示 atomic tool、toolset、invocation ID、turn、状态、reason、
  snapshot hash 和耗时。
- drawer 只读；权限变更导航到新 draft 或 Session replacement。

**完成记录**：

- `web2` 新增 `RuntimeCapabilityDrawer`，从现有 `ProcessTreeState.events` 消费
  canonical event；页面实时帧和历史消息复用同一过程树投影，不新增权限计算或写接口。
- `HomePage` 接入 runtime process state；会话切换时从历史消息恢复最近过程树，流式事件更新时同步抽屉。
- 工具/Skill 活动按 `session_id` 过滤，避免 parent/child Session 串线；工具行保留 invocation ID、toolset、turn、status、reason、snapshot hash 和 duration。
- 只读抽屉展示 Agent/revision/model/provider、三类 snapshot hash、创建时间、replacement/lineage、工具状态分类和 Skill 活动。
- 回归测试：`RuntimeCapabilityDrawer.test.tsx` 覆盖 tool started/failed/denied、稳定 reason code、Skill rejected 和 child Session 隔离。

**验证**：`NetworkClaw/web2` 的 `npm run typecheck`、`npm test -- --run`（343 passed、1 skipped）、抽屉专项测试（1 passed）、`npm run build` 和 `git diff --check` 通过；构建仅有既有 chunk size warning。`NetworkClaw/web` 未修改、未安装依赖、未启动、未构建、未测试。

**验收**：

- 能区分 `not_loaded`、`not_granted`、`unavailable`、`turn_disabled`。
- Tool deny 和 Skill dependency failure 显示稳定 reason code。
- parent/child Session 的工具和 Skill 活动不会串线。
- replay 后过程树与实时事件一致。

**下一步**：进入 **FE-09 web2 旧模型写入口收口**。

### FE-09 [P0] web2 旧模型写入口收口

**依赖**：FE-08、A-07、X-01。  
**主责**：`NetworkClaw/web2`；原作者 `web` 仅提供只读参考，不参与实现、构建或测试。  
**状态**：已完成。

**模块**：

- `NetworkClaw/web2/src/pages/agent-skill-tool/AgentsSection.tsx`
- `NetworkClaw/web2/src/api/catalog.ts`
- `NetworkClaw/web2/src/pages/HomePage.tsx`
- `NetworkClaw/web2` 旧 Agent/Skill/Tool 路由和状态存储

**任务**：

- 停止新流程对 `skills_json`、`tools_json` 和旧 `/catalog/agents` 写接口的调用。
- 旧页面改为只读历史视图、迁移提示或跳转到新 `/agents`、`/capabilities` 页面。
- 清理旧页面的 optimistic update，避免产生不受服务端 revision 管理的本地权限状态。
- 对历史 Agent 显示迁移来源和当前 published revision，不把旧 JSON 伪装成新 revision。
- 保留一次性迁移工具的入口说明，但不让普通配置操作再次写旧表。

**完成记录**：

- 删除 `web2` 旧 `AgentsSection`、`ModelsSection` CRUD 组件及其 optimistic update。
- `/agent-skill-tool` 收敛为只读迁移提示页，仅链接到新的 `/agents` 和 `/capabilities`。
- `web2/src/api/catalog.ts` 移除旧 models/agents 的 create/update/delete API，仅保留历史目录读取和只读 seed 查询。
- `catalog.test.ts` 改为验证 legacy catalog 只读兼容；新 revision 写入继续统一走 `src/api/agents.ts` 的 draft/publish 流程。
- `skills_json`、`tools_json` 仅保留历史响应类型/读取兼容，不再从生产页面提交；canonical event 与 runtime capability drawer 不依赖旧权限 JSON。

**验收**：

- 静态搜索确认生产前端没有旧模型写调用。
- `NetworkClaw/web2` 仍能读取 canonical event 并展示过程，不依赖旧权限 JSON。
- 新旧页面不会对同一 profile 产生双写竞争。

**验证**：`NetworkClaw/web2` 的 `npm run typecheck`、`npm test -- --run`（45 个测试文件，332 passed、1 skipped）、`npm run build` 和 `git diff --check` 通过；构建仅有既有 chunk size warning。静态搜索未发现旧 catalog 的 POST/PATCH/DELETE 写调用；`NetworkClaw/web` 未修改、未安装依赖、未启动、未构建、未测试。

**下一步**：进入 **FE-10 浏览器验收、类型构建和交付门禁**。

### FE-10 [P0] 浏览器验收、类型构建和交付门禁

**依赖**：FE-09。  
**主责**：`NetworkClaw/web2`；Integration 仅维护跨仓验证入口和交付证据，后台与 Harness 提供联合验收依赖。  
**状态**：已完成（2026-09-30）。

**执行范围**：浏览器验收、类型检查、构建和前端测试只在
`../NetworkClaw/web2` 执行；`NetworkClaw/web` 仍为只读参考，
不启动、不安装依赖、不构建、不测试。

**任务**：

- 使用 provider stub 验收 Agent draft -> publish -> new session -> runtime activity。
- 覆盖 Skill `auto_load`、`explicit`、`disabled`、缺失依赖、未授权 `skill_view`。
- 覆盖 Toolset 展开、原子 deny、unavailable、not loaded 和 turn disabled。
- 覆盖新 revision 发布后旧 Session snapshot 不变。
- 覆盖 child delegation 的工具活动和 parent/child lineage。
- 验证 web2 旧入口不会产生新模型写入。
- 生成前端测试和跨仓 evidence，纳入 bundle/provenance。

**门禁命令**：

```bash
cd ../NetworkClaw/web2
npm run typecheck
npm run build
npm test

cd ../networkclaw-integration
make validate-contracts
make test
make integration-test
```

**验收**：

- 浏览器验收覆盖管理、Session 和运行态三条主路径。
- Web2 TypeScript、Web2 build、相关单测、Integration contract 和组合验收通过。
- 失败 reason code、snapshot hash 和旧入口静态检查均有证据。
- 测试结束清理临时 Session、provider stub、workspace 和 artifact。

**完成记录**：

- `web2` 已完成管理页、Session snapshot 和 runtime activity 的前端验收证据；运行态真实 Hermes/Gateway/Lobby browser ledger 位于 `.integration-state/evidence/event-e06-runtime-browser.json`，前端专项证据位于 [`docs/evidence/fe10-frontend-acceptance.md`](../evidence/fe10-frontend-acceptance.md)。
- `AgentRevisionPicker`、`SessionSnapshotSummary`、`RuntimeCapabilityDrawer` 和旧入口迁移页均有测试或组合验收覆盖；Skill mode/dependency/trust/release、tool grant/deny/unavailable/not-loaded/turn-disabled、revision snapshot 隔离和 parent/child lineage 均有证据。
- 门禁通过：`web2 npm run typecheck`、`npm run build`、`npm test -- --run`（45 个测试文件，332 passed、1 skipped）、`make validate-contracts`、`make test`（80 项）和 `make integration-test`（13 个组合场景全部通过）。
- 组合验收清理状态为 clean；测试拥有的残留 socket 已检查并清理，无 `ncg-*` 临时目录；`NetworkClaw/web` 未操作。
- 旧 catalog runtime authority 不再参与验收；browser report 中 `full_catalog_verified=false` 是预期结果，新的 revision/snapshot contract 和 A-07 vertical acceptance 取代旧 catalog fixture。

**交付证据**：`docs/evidence/fe10-frontend-acceptance.md`、
`.integration-state/evidence/combination-matrix.json`、
`.integration-state/evidence/event-e06-runtime-browser.json`。

**下一步**：前端计划完成；进入发布前的 **X-01/X-02 三仓退役、bundle/provenance 和最终交付复核**。对应重建计划中的 A-06/A-07 已有完成记录，后续以 X-01/X-02 的交付证据为准。

## 5. 可并行工作

只有共同依赖完成后允许并行：

| 前置完成 | 可并行任务 | 限制 |
|---|---|---|
| FE-01 | API response fixture、页面路由草图 | 不提交新写入口 |
| FE-02 | FE-03 Catalog、FE-04 workspace 壳 | 只能使用统一类型和 query key |
| FE-03 | Catalog 视觉整理、Agent tool selector | selector 必须消费 Catalog API |
| FE-05 | Skill detail 文案、dependency 状态组件 | 不改变 mode 枚举 |
| FE-06 | 发布 diff 测试、Session picker 壳 | picker 只能显示 published revision |
| FE-07 | snapshot summary、runtime event fixture | 不自行计算权限 |
| FE-08 | web2 只读适配、浏览器脚本 | 旧写入口仍需等 FE-09 统一收口 |

并行提交必须注明所依据的 C-00 schema、API 版本和 snapshot hash 规则。

## 6. 完成定义

本前端计划同时满足以下条件才算完成：

1. Catalog、Agent revision、Session snapshot 和 runtime activity 有清晰的页面边界。
2. Toolset 选择和 atomic tool 授权在 UI 上分层显示。
3. Skill revision、mode、依赖和 trust/release 状态可配置且可审计。
4. Session 只绑定 published revision，并展示冻结 snapshot/hash。
5. 运行态能区分 loaded/granted/turn disabled/unavailable/not granted。
6. Tool/Skill/delegation canonical event 能在 Web2 中重建过程。
7. 旧 `tools_json`、`skills_json` 和旧 Agent 写入口不再参与生产配置。
8. Web2 构建、单测、浏览器验收、Integration contract 和组合测试全部通过。

## 7. 计划完成后的下一步

FE-10 完成后，更新 [Hermes Capability 重建计划](hermes-capability-rebuild-plan.md)
中的 A-06/A-07 状态和完成证据；再由 X-01/X-02 统一验证旧模型退役、bundle 内容和
三仓 provenance。任何新的 UI 字段必须先回到 C-00 或对应后端 contract，避免前端
自行扩展运行时事实。
