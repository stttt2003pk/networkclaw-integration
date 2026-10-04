# Capability Release Admin Contract v1

状态：R-07 已冻结。Provider 为 NetworkClaw Lobby；consumer 为 Integration 的显式管理 client。

## 权威契约与边界

- HTTP 请求、响应、枚举和 nullability：NetworkClaw 的 `api/lobby/v1/capability-release-admin-v1.schema.json`。Integration 的 `schemas/` 同名文件是逐字节镜像。
- 完整 manifest：Integration 的 `schemas/capability-release-v1.schema.json`；NetworkClaw 的同名文件逐字节镜像，由 Go 嵌入并校验。
- Go message：`api/lobby/v1/capability_release.proto`，由 `make proto-capability-release` 生成。

R-07 冻结管理输入及写入前拒绝语义。当前验收使用 Go 测试内存 store，不操作生产 catalog/session。生产 repository 装配、事务和 durable audit 留给 R-08。

## 管理 API

`POST /api/v1/admin/capability-releases/actions`，JSON，最大 4 MiB。

复用 Lobby access JWT 和 `admin` role。operator 从已验 JWT subject 推导，不能由请求自报。缺失、非法、过期或 refresh JWT 返回 `unauthorized`；非 admin 返回 `forbidden`，均在读取 manifest 和调用 store 前拒绝。

| operation | 必填输入 | 语义 |
|---|---|---|
| `import` | operation、job_id、manifest | 接收完整 `capability-release.v1`；仅接受 draft，不发布 |
| `publish` | operation、job_id、release_id、release_hash、expected_published_hash | 发布 draft；重复当前发布幂等 |
| `rollback` | 同 publish | 重新发布曾 published 的已有 release；保留较新版本，不改写 session |

`expected_published_hash` 必填，可为 null。null 表示预期没有当前 published release；字符串表示预期当前 release hash。额外字段、重复 JSON key、深度超过 64 或缺字段返回 `request_invalid`。

## 固定响应与审计

所有响应为 `{code,message,data}`。成功 message 为 `ok`；失败 message 只使用稳定 reason code，不返回异常、manifest 正文、token、数据库或文件路径。

`data` 固定包含：`schema_version`、`operation`、`release_id`、`manifest_hash`、`catalog_version`、`release_status`、`result`、`reason_code`、`idempotent`、`previous_published_hash` 和 `audit`。audit 固定 `operator`、`job_id`、`source_tree_hashes`。

成功结果为 `draft_created`、`existing`、`published` 或 `rolled_back`；拒绝为 `rejected`；基础设施/事务失败为 `failed`。不能安全确认的 identity 为 null，source tree hashes 为空对象。R-08 必须将成功、幂等、拒绝和失败审计持久化；R-07 的 fixture receipt 不代表已落库。

## 校验、幂等与 CAS

`import` 先校验 admin request schema，再校验完整 manifest schema 和 R-00 canonical release hash。随后校验 duplicate/stale revision、Toolset membership、Skill dependency、availability/trust、Agent grant、catalog 和 release state。缺失引用返回 `stale_revision`，不可用依赖返回 `dependency_unavailable`；已发布 revision 不覆盖。

Toolset 是候选成员集；Agent `allowed_tool_revisions` 可显式收窄，只能来自 requested Toolset 的相同 revision，且不能被 `denied_tools` 排除。导入不自动扩大 Agent 权限。

相同 `release_hash` 返回 `existing` 和 `idempotent=true`。同一 identity 对应不同内容返回 `release_hash_conflict`。publish/rollback 在 store 事务内重新校验 identity、状态和 `expected_published_hash`；当前已是目标时幂等，否则 CAS 不匹配返回 `published_release_conflict`。事务失败不得产生 published 成功结果。

## Reason code

`unauthorized`、`forbidden`、`request_invalid`、`release_schema_invalid`、`release_hash_invalid`、`duplicate_revision`、`stale_revision`、`dependency_unavailable`、`agent_reference_invalid`、`catalog_conflict`、`invalid_release_state`、`release_not_found`、`release_hash_conflict`、`published_release_conflict`、`release_store_unavailable`、`import_transaction_failed`、`publish_transaction_failed`、`rollback_transaction_failed`。

HTTP 映射：401/403 为权限；400 为请求/依赖验证；404 为 release 不存在；409 为 identity/revision/state/CAS 冲突；503 为 store 不可用；500 为事务失败。

## Integration client 与验收

`tools/capability-release-admin.py` 提供三个 operation。网络操作要求显式 `--execute`；token 从 `NETWORKCLAW_ADMIN_TOKEN` 或 `--token-env` 读取。生产 endpoint 使用 HTTPS；HTTP 仅限 loopback；禁止重定向。普通 `ci-test` 不调用管理 client。

完整 Lobby 路由还校验 CSRF 来源。管理 client 的 `--origin`（或 `NETWORKCLAW_ADMIN_ORIGIN`）必须匹配部署的 `ONGRID_WEB2_ORIGINS`；例如本地 `--origin http://127.0.0.1:5174`。`dev-up` 使用配置的第一个允许来源。缺少/不匹配来源会在 handler 前返回 403，不得关闭 CSRF 来绕过。

`make capability-release-admin-contract-test` 使用测试内 httptest server，覆盖真实 JWT、Go handler、Python client 和 schema 往返；详细响应及 write delta 见 `tests/fixtures/capability-release/admin-contract-v1.json`。R-08 前不装配生产 store；移除 `CapabilityReleaseUC` 注入即可撤销管理路由。
