# Hermes Capability 前端消费字段表 v1

状态：**FE-01 已完成（2026-09-29）**。

本表是 `NetworkClaw/web2` 消费 Hermes Capability 新模型的字段边界。字段事实以
`schemas/capability-snapshot-v1.schema.json` 和
`docs/contracts/capability-snapshot-v1.md` 为准；前端只展示服务端结果，不在浏览器
重新展开 toolset、计算授权或重建 session snapshot。

## 1. 前端消费对象

| 对象 | 必填/关键字段 | 前端用途 | 当前 Web2 状态 |
|---|---|---|---|
| Catalog | `version`, `source`, `status` | 目录范围、来源和生命周期 | 新 API 待接入；旧 `Catalog*` 仅兼容读取 |
| Tool revision | `name`, `revision`, `version`, `schema_hash`, `source`, `availability`, `status` | Atomic Tool 详情、状态和审计 | 新 API 待接入；旧 `CatalogTool` 缺 revision/hash |
| Skill revision | `skill_id`, `version`, `content_hash`, `metadata_hash`, `manifest_hash`, `source`, `release_ref`, `release_status`, `trust_state`, `platforms`, `session_platforms`, `required_toolsets`, `required_tools`, `config_schema` | Skill 详情、依赖和 binding 选择 | 新 API 待接入；旧 `CatalogSkill` 仅有名称/描述/启用状态 |
| Agent revision | `agent_id`, `revision`, `revision_hash`, `requested_toolsets`, `allowed_tools`, `denied_tools` | Draft/published revision、权限 diff 和发布摘要 | 新 API 待接入；旧 `CatalogAgent` 使用 `skills_json`/`tools_json` |
| Session capability snapshot | `session_id`, `catalog_version`, `agent_revision`, `toolset_revisions`, `allowed_tools`, `snapshot_hash` | Session 冻结能力和 hash 展示 | 当前 `Session` 没有 snapshot 字段 |
| Session skill snapshot | `skill_id`, `version`, `content_hash`, `mode`, `config_hash`, `resolved_dependencies`, `omitted_reason` | Skill 生效模式和依赖结果 | 当前 Web2 无对应类型 |
| Runtime event | canonical event envelope 的 `session_id`, `run_id`, `turn_id`, `event_id`, `invocation_id`, `payload`, `snapshot_hash`（如事件携带） | Tool/Skill/delegation activity 和 lineage | 已有 canonical event reducer；需补 capability 字段投影 |

## 2. 枚举和错误映射

### Tool 状态

- `registered`、`available`、`unavailable`、`active`、`retired`
- 运行态错误：`unknown`、`unavailable`、`not_loaded`、`denied`、`stale_revision`

### Skill 状态

- binding mode：`auto_load`、`explicit`、`disabled`
- session snapshot mode：`available`、`auto_load`、`disabled`
- 依赖错误：`skill_not_found`、`skill_not_published`、`skill_not_trusted`、
  `skill_toolset_not_loaded`、`skill_tool_not_authorized`、`skill_config_missing`

前端不得把上述错误合并为单一的“不可用”，也不得将 `auto` 写回新接口；如兼容读取
旧值 `auto`，只能归一化为 `auto_load`。

## 3. 新 API 消费边界

FE-02 需要实现以下领域 client。具体 URL 以 NetworkClaw Lobby 最终路由为准，不能
从多个旧接口拼装新对象：

| 领域 | 读取 | 写入 |
|---|---|---|
| Capability catalog | catalog、toolset、atomic tool、skill revision | 仅按新 catalog/revision API |
| Agent revision | profile、draft、published revision、effective projection | draft 保存、binding 集合保存、publish/duplicate |
| Session | published revision picker、三类 snapshot | 创建时提交 `agent_profile_id` + `agent_revision_id` |
| Runtime | canonical event stream、snapshot identity | 只读 |

服务端返回的 `revision_hash`、`snapshot_hash` 和 reason code 必须原样保留；前端不能
自行生成替代值。

## 4. 旧入口盘点和迁移顺序

以下入口属于旧模型，只允许作为兼容读取或一次性迁移输入，禁止新页面继续写入：

| 位置 | 旧行为 | 处理顺序 |
|---|---|---|
| `web2/src/api/catalog.ts` | `CatalogAgent.skills_json/tools_json`；`POST/PATCH/DELETE /catalog/agents` | FE-02 不向新 client 暴露；FE-09 收口 |
| `web2/src/pages/agent-skill-tool/AgentsSection.tsx` | 直接编辑并提交旧 JSON 数组 | FE-09 改为只读历史/迁移提示 |
| `web2/src/pages/HomePage.tsx` | 用 `agent_id` + `scope_json` 创建 Session | FE-07 改为 profile + published revision |
| `web2/src/pages/AgentSkillToolPage.tsx` | 以旧 seed catalog 解释 Skill/Tool | FE-03 替换为新 catalog master-detail |
| `web2/src/components/AgentPicker.tsx`、`SkillToggle.tsx`、`lib/scope.ts` | 本地组装旧工具选择和 scope | FE-07/FE-09 删除新流程依赖 |

本次审计确认 `NetworkClaw/web` 不在开发、构建、测试或交付范围内。

## 5. 审计结论

- C-00 schema、canonical JSON/hash 规则、snapshot 不可变边界和错误语义已具备唯一来源。
- Web2 当前尚未实现新 Agent revision、Skill binding、Session snapshot API；FE-02 必须
  先建立类型和 query key，再由后续页面接入。
- 旧写入口仍存在，已明确列入 FE-09；不得在 FE-02 至 FE-08 中增加对旧字段的写入。
