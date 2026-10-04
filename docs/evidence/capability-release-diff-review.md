# Capability Release Diff Review

日期：2026-09-30

本次只读比较使用 `tests/fixtures/capability-release/valid-release-v1.json` 作为
published release 快照，候选版本为 `cap-2026.09.30-001`。机器可读结果见
[`capability-release-diff-v1.json`](capability-release-diff-v1.json)。

- 新增：224 个 revision
- 删除：3 个 revision
- 内容变化：1 个 Tool revision
- 未确认迁移：3 项，均标记为 `retired`，没有自动生成新 binding
- M0 inventory、M1 first import、M2 new session 已准备；M3 close old release 需要人工审阅

该报告只描述变更和候选迁移，不执行 import、publish、rollback 或数据库写入。
