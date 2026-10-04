# Capability Contract v1

状态：**C-00 已冻结**。这是 Lobby、Harness Gateway 和 integration 之间的公共输入边界；运行时不得把旧 `tools_json`、`skills_json` 或 transcript 当作事实源。

## Hash 与序列化

所有 hash 使用 `sha256:` 加 64 位小写十六进制。JSON 使用 UTF-8、无 BOM、对象键按 Unicode code point 排序、数组保持语义顺序、无空白（等价于 Python `json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)`）。`snapshot_hash` 对 `snapshot` 对象去掉自身 `snapshot_hash` 后计算；其他 hash 对对应正文或 manifest 的 canonical JSON 计算。

## Revision 字段

| 对象 | 必填字段 | 规则 |
| --- | --- | --- |
| Catalog | `version`, `source`, `status` | `status`: `draft` / `published` / `retired` |
| Tool revision | `name`, `revision`, `version`, `schema_hash`, `source`, `availability`, `status` | `name` 是 Hermes 原子工具名；`availability` 区分 registered/available/unavailable |
| Skill revision | `skill_id`, `version`, `content_hash`, `manifest_hash`, `source`, `release_status`, `trust_state` | 正文和发布包不可变；依赖只引用 Hermes toolset/原子工具名 |
| Agent revision | `agent_id`, `revision`, `revision_hash`, `requested_toolsets`, `allowed_tools`, `denied_tools` | `allowed_tools` / `denied_tools` 只能是原子工具名 |

## Session 快照

`SessionCapabilitySnapshot` 在 session 创建时生成，包含 `session_id`、`catalog_version`、`agent_revision`、toolset revision 映射、最终 `allowed_tools` 和 Skill 快照。创建后不可变；配置发布只影响新 session。`SessionSkillSnapshot` 的 `mode` 区分 `available`、`auto_load`、`disabled`，不把 Skill 正文写入 Agent 或持久化 session。

`requested_toolsets` 是候选输入，`allowed_tools` 是最终原子授权。Gateway 必须在 Hermes registry 加载并做环境检查后取交集；空或未知 toolset fail closed。

## 错误语义

| 代码 | 含义 |
| --- | --- |
| `unknown` | 标识未在 catalog/registry 注册 |
| `unavailable` | 已注册但当前平台、依赖或 check capability 不满足 |
| `not_loaded` | 已授权但本 session 未加载对应 schema/toolset |
| `denied` | 被 Agent、Host grant 或本轮 allowed_tools 拒绝 |
| `stale_revision` | revision 或 schema hash 与 catalog 当前版本不一致 |

Skill 依赖错误使用 `skill_not_found`、`skill_not_published`、`skill_not_trusted`、`skill_toolset_not_loaded`、`skill_tool_not_authorized`、`skill_config_missing`。除非 binding 明确 optional，否则不得静默省略。

## 边界

快照不得包含 Hermes Agent 实例、provider client、transcript、workspace 绝对路径、handler、secret 明文、lease 或 execution epoch。Gateway debug/readiness 和 canonical event 关联字段应携带 `snapshot_hash`，但不携带上述运行时对象。
