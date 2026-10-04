# Capability Release Contract v1

状态：**R-00 已冻结**。

`capability-release.v1` 是把 Catalog、Toolset、原子 Tool、Skill 和 Agent revision
组合成一个不可变发布单元的离线契约。Integration 负责编译和校验；NetworkClaw
负责受控事务导入；Harness 负责 vendor、inventory 和 Skill manifest 的来源事实。

## 顶层字段

| 字段 | 规则 |
|---|---|
| `schema_version` | 固定为 `capability-release.v1` |
| `release_id` | `cap-` 开头的稳定标识；不能包含时间戳以外的运行时随机值 |
| `release_hash` | 删除自身后对整个 manifest 做 canonical JSON SHA-256 |
| `sources` | `networkclaw`、`harness`、`integration` 三个源码身份 |
| `hermes` | source ref、vendor manifest hash、vendor tree hash |
| `protocol` | Host Protocol 版本和 `capability.v1` schema 版本 |
| `target` | OS、版本、架构和 session platform |
| `catalog/toolsets/tools/skills/agents` | 本 release 的完整 revision 图 |
| `migration` | legacy 输入和无法自动映射的项目 |

每个源码身份记录 `repository`、`ref`、可选 `commit`、`tree_hash`、`dirty` 和可选
`diff_hash`。源码没有 Git 时 commit 可为 null，但 tree hash 仍然必需。

## 确定性和禁止内容

canonical JSON 使用 UTF-8、对象键按 Unicode code point 排序、数组保持语义顺序、无
空白，等价于：

```python
json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
```

`release_hash` 不得受生成时间、绝对本机路径、secret、provider client、transcript
或 Hermes Agent 实例影响。`tree_hash`、vendor hash、schema/content/manifest hash
均使用 `sha256:` 加 64 位小写十六进制。

## 状态和失败语义

- `active` / `retired`：Tool 或 Toolset revision 状态。
- `available` / `unavailable` / `revoked`：Skill 发布状态；`trusted`、`quarantined`、`unknown` 是信任状态。
- `unknown`：标识不在 catalog/registry 中。
- `unavailable`：已注册但平台、依赖或 check capability 不满足。
- `retired`：历史 revision 不再被新 release 引用。
- `vendor_missing`、`vendor_hash_mismatch`、`unknown_tool`、`unknown_toolset`、`unknown_skill`、`dependency_unavailable`、`stale_revision`、`release_hash_conflict`、`import_transaction_failed`：跨阶段稳定 reason code。

缺失或不可信依赖必须 fail closed，不能伪造版本或静默省略。legacy Tool 排除清单
固定为：`host_netns_inspect`、`probe_dns`、`probe_http`、`probe_tcp`、`read_journal`、
`restart_service`、`tail_file`、`web_search`。

## 边界

Release 是编排 artifact，不是第四个源码仓库。`import` 是 NetworkClaw 的 admin-only
受控操作；普通 CI 只执行 vendor-check、compile、check、diff 和 export，不写生产数据库。
