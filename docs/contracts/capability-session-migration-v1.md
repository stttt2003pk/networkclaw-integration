# Capability Session Migration v1

本 runbook 对应 R-09 的 M0 到 M3。迁移报告只保存脱敏的旧 catalog 映射、profile/revision 身份、活跃 session hash 和发布身份；不保存 transcript、prompt、provider 配置或用户身份。

## 前置条件

- `networkclaw-harness` 已完成 vendor gate，candidate manifest 通过 schema、canonical hash、依赖和 vendor provenance 校验。
- `CAPABILITY_MIGRATION_DSN` 仅通过环境变量提供，数据库连接使用受控迁移账号。
- 首次导入前，所有要迁移的 Agent 都有明确的 profile/revision、Tool/Toolset 和 Skill version；无法确认的项保持 `unknown` 或 `unavailable`，不得填造 revision。

## M0 只读盘点

```sh
CAPABILITY_MIGRATION_DSN="$DSN" \
  go run ./cmd/capability-migration \
  --candidate /path/to/capability-release.v1.json \
  --output /private/path/capability-migration-v1.json
```

检查 `read_only=true`、`phase=M0`、`legacy_write_protected` 和 `unresolved`。`ready_for_review=false` 时不得继续导入或发布。输出文件由 CLI 以 `0600` 创建，不能放入公开 artifact。

## M1 导入和发布

使用现有 capability release admin client，在显式 `--execute` 和 operator/job 标识下执行 import，再执行 publish。发布前确认 candidate 的 source tree、vendor tree 和 manifest hash 与 gate 报告一致。导入失败必须保持当前 published release 不变。

## M2 session 切换

安装 migration `029_legacy_capability_readonly` 后，新 session 必须带 Agent profile，解析当前 published release 并冻结 capability、Skill、Agent 三份 snapshot。创建时验证 snapshot hash 和发布版本；旧 session 继续读取创建时 snapshot，发布或 rollback 不改写它们。fork 只允许从同租户同用户的既有 snapshot 精确继承。

## M3 观察、回滚和收口

- 观察 snapshot hash、`unknown_*`、`stale_revision`、依赖拒绝和 session 创建结果。
- rollback 以旧 release 为单位重新发布，保留新 release 和审计记录；不删除 vendor，也不重写已创建 session。
- 确认旧 `tools_json`/`skills_json` 只读后再继续归档。029 的 down migration 只用于旧 binary 的受控回滚，不能作为常规清理步骤。

本地 `dev-up` 与 compose migration runner 使用同一个 `networkclaw_compose_migrations` 文件名/SHA ledger。旧工作区若已安装 029，runner 只有在 `capability_releases`、`session_capability_snapshots`、`agent_profiles` 均存在时才建立 baseline；不满足条件会停止并要求人工修复。
