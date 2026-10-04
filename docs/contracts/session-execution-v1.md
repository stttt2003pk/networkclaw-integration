# Session execution v1

本契约补充 `capability-snapshot-v1`，冻结 Session 的执行策略和资产身份。`session-execution.v1` 的 schema 是 Integration 的 `schemas/session-execution-v1.schema.json`；Go 与 Harness 保存逐字一致的部署副本。它不取代 Host Protocol v1 的 frame、租约与模型配置契约。

`execution_snapshot` 必须包含 session_id、release 身份、policy、requested_toolsets、tools、skills、snapshot_hash。Profile 来源与默认模型引用可选。Profile 不存在时不能省略 policy 或资产集合；`[]` 是合法空授权，缺失或 null 是不完整输入。工具全集、最新 release、默认 Profile 都不能用作失败后的替代授权。

release 使用 release_id、release_hash、catalog_version。Tool 使用 name、revision、version、schema_hash、source；Skill 使用 skill_id、revision、version、content/metadata/manifest_hash、release_ref、mode、config_hash、resolved_dependencies。引用必须指向已发布、已部署的不可变资产。optional Skill 允许资产不可用时有明确的拒绝/省略记录，不允许替换版本。仍被 Session 引用的 release 必须保留，节点缺少它时拒绝执行。

policy 包含 system_prompt、permission_mode、四项 turn_budget 与 delegation_policy。delegation 启用必须同时授予 delegate_task、非零深度与并发上限。子授权从父授权收窄并重新绑定独立 child Session；租约、workspace、父子 lineage、generation/epoch 沿用 Host 字段，不放入本内容 hash。`allowlist` 与 `explicit` 保留旧授权词汇，禁止在转换时改变其含义。

hash 为 `sha256:` 加小写十六进制。仅排除顶层 snapshot_hash，然后使用 JSON `ensure_ascii=True, sort_keys=True, separators=(',', ':'), allow_nan=False` 的 UTF-8 字节计算 SHA-256。数组保留顺序，生产者冻结前按稳定资产身份排序；重排数组也属于内容变化。

此规则适用于新的 `execution_snapshot`，不重新解释已持久化的旧 Go capability/Skill 投影摘要。旧 capability 摘要保留空字符串 `snapshot_hash` 字段并使用 Go 的排序对象序列化；旧 Skill 摘要使用 `session_id,skills` 与已部署 `SessionSkill` 的字段顺序序列化。manager 通过 `LegacyCapabilityHash` / `LegacySkillHash` 校验与派生这些兼容投影，完整内容仍须逐项等价于已经校验的新 execution authority；不能从摘要兼容推导额外授权。版本化父/子 fixture 与实际 Lobby 生产摘要对账覆盖此差异。后续投影协议改版须显式迁移，不能使旧持久会话突然失效。

model_config_id、最低执行/凭证版本与参数属于 turn 请求。chatrtmgr 在 run 首次准入固定私有 model_execution，同 run 重试使用原值。Session 的 default_model_ref 仅为可选默认值，不能阻止后续合法模型切换。私有 model_execution、凭证、run/turn、lease/epoch 不允许进入本 snapshot；密钥原值或摘要不允许进入 Agent cache 身份。

| 原因 | 拒绝语义 |
| --- | --- |
| execution_contract_unsupported | 提供的契约版本不受支持 |
| execution_snapshot_invalid | 字段缺失/null、额外字段、格式或预算不合法 |
| execution_snapshot_identity_invalid | 平台/子 Session 身份不匹配 |
| execution_snapshot_hash_invalid | 内容 digest 不符 |
| execution_asset_duplicate | 同一资产身份出现多个引用 |
| execution_dependency_denied | Skill 依赖未获授权 |
| execution_delegation_denied | 派遣能力或策略不满足 |
| execution_snapshot_unavailable | 缺少可信冻结配置，拒绝执行 |
| execution_tool_denied | 创建请求超出部署授权上限 |
| execution_release_unavailable | 受信部署声明没有保留该 release |
| execution_asset_unavailable | 清单中的资产或本地包不可用 |
| execution_asset_version_mismatch | 引用与部署清单版本/身份不符 |
| execution_asset_hash_mismatch | 部署清单或实际 registry schema/source 不符 |
| dependency_unavailable / stale_revision | 发布资产不可用或身份/版本不符 |

滚动升级先部署能识别新字段的 Harness，再部署 chatrtmgr，再启用 Lobby 新创建路径。旧消费者不能执行新 Session；不得删除 execution_snapshot 降级。旧会话只允许从已验证的完整三份冻结 snapshot 与对应保留 release 等价转换；prompt、权限、预算、派遣与来源均保留，转换持久化且幂等。旧字段不完整时拒绝转换和执行。回退必须保留新表与冻结内容，不能恢复宽松默认授权。

脱敏父/子/空授权样例在 `tests/fixtures/session-execution/`，三仓针对相同样例验证结构、Unicode hash、身份、篡改、空授权、依赖与私有字段拒绝。

执行节点使用受信环境变量 `NETWORKCLAW_CAPABILITY_RELEASES` 声明离线部署，值为 JSON 数组，每项包含 `manifest`（capability-release.v1 文件）和 `asset_root`（对应 Harness 源码/交付快照根）。会话打开时校验 release digest、catalog、每项 revision/version/hash/source 与实际 Hermes registry；Skill 正文来自此快照的 `vendor/hermes/skills` 或 `src/networkclaw_harness/skills/builtin`。保留多个声明可同时支持旧、新 release，即使 Skill 同名也各自使用独立 catalog。不得用新快照覆盖仍被会话引用的旧目录。部署文件只包含资产事实；凭证不属于声明。缺少声明时显式空授权同样拒绝，防止将未知 release 解释成默认授权。
