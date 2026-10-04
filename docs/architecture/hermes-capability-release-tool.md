# Hermes Capability Release 工具设计

状态：设计稿

## 1. 目标与边界

当前工程已经能够分别发现 Hermes Tool/Toolset、生成 Tool catalog 和生成 Skill
release manifest，但没有一个工具把 Agent、Skill、Toolset、原子 Tool 组合成一个
可审计的完整能力版本，也没有一个事务入口把这个版本写入 NetworkClaw 数据库。

本设计增加一个轻量的 **Capability Release** 工具，解决以下问题：

1. 把代码注册的 Agent、Tool、Toolset 与 Hermes vendor 中的 Skill 统一编译为一个
   不可变 release manifest。
2. 为 Agent、Skill、Toolset、Tool 建立明确的版本和 hash 引用关系。
3. 将 manifest 以单次事务导入 NetworkClaw，失败时不留下部分数据。
4. 在应用迁移期间保留旧 catalog 的可追溯性，并支持回滚到上一个已发布版本。

本工具不实现新的 Agent loop、模型调用、Tool handler、Skill 加载器、权限计算或
session runtime。三仓职责保持如下：

| 仓库 | 责任 | 本设计中的变化 |
| --- | --- | --- |
| `networkclaw-harness` | Hermes runtime、vendor、Tool/Skill 真实注册和执行 | 仅保证 Skill/Tool 同步到 vendor，并提供现有 inventory/manifest 输出；不改 Agent 核心逻辑 |
| `NetworkClaw` | catalog、Agent revision、Skill binding、数据库事务和发布状态 | 增加最小的 release import 适配，不改变运行时执行逻辑 |
| `networkclaw-integration` | 跨仓编排、manifest 编译、diff、校验、迁移和 CI 入口 | 新增 Capability Release 工具 |

## 2. 总体流程

```text
Hermes source / Harness code registration
                |
                v
      Harness vendor sync
   Tool + Toolset + Skill assets
                |
                v
     vendor integrity verification
                |
                v
      Hermes inventory discovery
                |
                v
 Agent + Tool + Toolset + Skill resolver
                |
                v
 capability-release.v1 manifest
 (versions, hashes, dependencies, provenance)
                |
        check / diff / migration plan
                |
                v
 NetworkClaw release importer
   one transaction, draft -> published
                |
                v
 New session uses new snapshot
 Existing session keeps old snapshot
```

### 2.1 阶段 0：源码和版本输入冻结

工具首先读取 `workspace.local.yaml` 或 `sources.lock.yaml`，记录：

- NetworkClaw、Harness、Integration 的 commit、tree hash 和 dirty 状态；
- Hermes source ref 和 vendor manifest hash；
- Host Protocol、capability schema 和 manifest schema 版本；
- 目标平台、session platform 和构建时间之外的确定性输入。

时间戳不能参与内容 hash。这样同一组源码和配置可以重复生成相同 release。

### 2.2 阶段 1：Skill 和 Tool 全量进入 Harness vendor

所有要进入 NetworkClaw 能力 catalog 的官方 builtin Skill、Tool、Toolset 定义以及
其运行所需的 metadata、support file 和 handler source，必须先进入
`networkclaw-harness/vendor` 的受控 vendor 树。Capability Release 不直接修改该树，
而是调用或检查 Harness 已有同步流程：

```text
Hermes source/ref
  -> networkclaw-harness/scripts/sync-hermes-runtime.py
  -> vendor/hermes
  -> scripts/verify-hermes-vendor.py
  -> vendor manifest + tree hash
```

要求：

1. Skill 不能只通过数据库名称登记；`SKILL.md`、metadata 和 support files 必须有
   vendor 路径和 content hash。
2. Tool 不能只通过前端或数据库注册；registry 中的 schema、handler source、
   toolset membership 和 source ref 必须可从 vendor/runtime 重新发现。
3. vendor sync 使用 allowlist 和 pinned source；不允许在 Integration 复制一份
   Hermes 业务源码，也不允许直接编辑 `vendor/hermes`。
4. vendor 校验失败时，release 编译立即失败，不能生成可发布 manifest。
5. 当前明确排除的 legacy Tool 不进入本 release：
   `host_netns_inspect`、`probe_dns`、`probe_http`、`probe_tcp`、`read_journal`、
   `restart_service`、`tail_file`、`web_search`。

如果现有 Harness allowlist 尚未包含某个 builtin Skill 或 Tool，只调整 Harness 的
同步输入、allowlist 或 provenance 配置；不改 Hermes runtime 的执行实现。

### 2.3 阶段 2：能力发现

复用现有工具，不重复实现解析逻辑：

1. `generate-hermes-inventory.py` 发现 Tool、Toolset、schema、来源和可用性。
2. `project-hermes-catalog.py` 生成原子 Tool 和 Toolset catalog。
3. `generate-skill-manifest.py` 生成 Skill release manifest、内容 hash、依赖、信任
   状态和 support file hash。
4. Agent 配置来源读取 NetworkClaw 现有 Agent/profile 配置；不能把 transcript 或
   session runtime 当作配置事实源。

发现结果必须经过以下边界：

- Toolset 只用于组织和批量选择；最终授权必须展开为原子 Tool 名称。
- Skill 正文不写入 Tool 表，也不注册为 Tool handler。
- Skill 的 `required_toolsets`、`required_tools` 必须引用本 release 中存在的版本。
- Agent revision 必须引用确定的 catalog、Toolset revision、Tool revision 和 Skill
  revision，不能只保存名称。

### 2.4 阶段 3：统一 manifest 编译

工具将三类输出合并为 `capability-release.v1`。推荐的顶层结构如下：

```json
{
  "schema_version": "capability-release.v1",
  "release_id": "cap-2026.09.30-001",
  "release_hash": "sha256:...",
  "catalog": {"version": "2026.09.30", "status": "draft"},
  "sources": {},
  "toolsets": [],
  "tools": [],
  "skills": [],
  "agents": [],
  "migration": {}
}
```

每个对象都必须有稳定身份和版本：

| 对象 | 关键字段 | 版本关联 |
| --- | --- | --- |
| Catalog release | `version`、`release_hash`、`source`、`status` | 一个完整能力发布单元 |
| Tool revision | `name`、`revision`、`version`、`schema_hash`、`source`、`status` | 引用 vendor/runtime 中的原子 Tool |
| Toolset revision | `name`、`revision`、`version`、`member_tool_revisions` | 引用同一 catalog 的 Tool revision |
| Skill revision | `skill_id`、`version`、`content_hash`、`manifest_hash`、`release_ref` | 引用 required Toolset/Tool revision |
| Agent revision | `agent_id`、`revision`、`revision_hash`、`catalog_version`、`skill_revisions`、`allowed_tools` | 把 Agent、Skill、Toolset、Tool 串成一个版本 |

`release_hash` 对 canonical JSON 计算，数组按语义顺序固定，对象键排序，不能包含
时间戳、绝对本机路径、secret、provider client、transcript 或 Hermes Agent 实例。

### 2.5 阶段 4：校验、diff 和迁移计划

在写数据库之前执行三类检查：

**结构检查**

- manifest schema、版本和 hash 格式正确；
- Toolset 成员存在，Skill 依赖存在，Agent 引用的 revision 全部存在；
- Tool/Skill 的 source、vendor hash、trust/release 状态完整。

**语义检查**

- Toolset 展开结果与 `allowed_tools` 一致；
- Agent 不能引用 `unavailable`、`retired`、未信任或未发布 Skill；
- required Tool/Toolset 缺失时 fail closed；
- 新 release 不会覆盖已发布 revision。

**变更检查**

- 与当前已发布 release 比较新增、删除、内容变化、依赖变化和 Agent 绑定变化；
- 删除只表示新 release 不再引用，不物理删除旧 revision；
- 生成迁移计划，列出旧 Agent/Tool/Skill 到新 revision 的映射和无法自动映射的项目。

`check` 只验证，`diff` 只比较，`export` 只生成 artifact。三者都不写生产数据库。

### 2.6 阶段 5：NetworkClaw 事务导入和发布

导入由 NetworkClaw 的管理入口完成，Capability Release 工具通过本地文件或管理 API
提交 manifest。必须使用单个数据库事务：

```text
begin
  校验 release_id/release_hash 幂等性
  创建 catalog version = draft
  写入 Tool revisions
  写入 Toolset revisions 和 membership
  写入 Skill revisions 和 dependency edges
  写入 Agent revisions 和 Skill bindings
  校验外键、状态、依赖和数量/hash
  将 draft 标记为 published
  将上一版本标记为 retired/previous
commit
```

任一步骤失败都回滚全部记录。已发布 catalog version 不原地修改；相同
`release_hash` 重复导入应返回已存在版本，而不是重复插入。

这里需要的 NetworkClaw 适配只包括：

- 一个 admin-only 的批量 release import command 或 API；
- 一个 repository transaction 方法，接收完整 manifest 并批量写入；
- import、publish、rollback 的审计结果和 reason code。

不需要修改 Agent loop、provider route、Hermes Tool executor、Skill prompt 注入或
Host Protocol 的运行时语义。若已有 repository/API 足够承载导入，可以只增加管理命令
和事务编排，不新增运行时接口。

## 3. Agent、Skill、Tool 版本打通规则

版本关系必须是有向、可追溯的：

```text
Capability Release
  -> Catalog version
      -> Agent revision
          -> Toolset revisions
              -> Tool revisions
          -> Skill revisions
              -> required Toolset/Tool revisions
```

运行时 session 创建时只消费已发布 revision，并生成不可变
`SessionCapabilitySnapshot`：

- 新 session 使用新 release；
- 已有 session 保留旧 catalog、Agent、Skill 和 Tool snapshot；
- release 发布不修改运行中的 session；
- snapshot hash 可以从 release 中的 revision 引用重新计算；
- 任何 revision/hash 不一致都 fail closed。

这样 Agent 版本不再保存无法审计的 `tools_json`/`skills_json` 事实，而是保存明确的
revision 引用和最终原子 `allowed_tools`。

## 4. 应用迁移方案

迁移目标是从旧 catalog 字段平稳切换到新 release 模型，不在运行时长期维护两套事实源。

### 4.1 迁移输入

以下旧数据只作为一次性迁移输入：

- 旧 `catalog_agents.tools_json`；
- 旧 `catalog_agents.skills_json`；
- 旧 `catalog_tools`、`catalog_skills` 或 seed catalog；
- 现有 Agent/profile 的名称、描述和启用状态。

迁移工具将它们转换为 draft manifest，并为无法确认来源或版本的对象标记
`unknown`、`unavailable` 或 `retired`，不得伪造 vendor 版本。

### 4.2 分阶段切换

**M0：只读盘点**

- 导出旧 catalog、Agent 绑定和正在运行的 session 数量；
- 生成旧名称到新 revision 的候选映射；
- 标记无法映射和 legacy 项目；
- 不改变应用读写路径。

**M1：导入首个 release**

- 从 vendor、registry 和旧 catalog 生成首个 `capability-release.v1`；
- 以 `draft` 导入 NetworkClaw；
- 完成依赖、hash 和数量校验后发布；
- 旧表和旧 JSON 保留，作为回滚和审计输入。

**M2：切换新 session**

- 新 session 创建改用 published Agent revision 和 capability snapshot；
- 运行中的 session 继续使用创建时的旧 snapshot；
- 前端和管理 API 只写新 revision/binding，不再写新的 `tools_json`/`skills_json`。

**M3：观察和收口**

- 对比新旧 session 创建成功率、依赖拒绝、unknown/stale revision 和 snapshot hash；
- 确认所有活跃 Agent 都有新 revision 映射；
- 将旧字段改为只读迁移输入，最后再通过单独迁移清理任务归档，不在本工具中删除历史。

### 4.3 回滚

回滚以 catalog release 为单位：

1. 选择上一个 `published` release；
2. 将其重新标记为当前发布版本，生成新的发布审计记录；
3. 新 session 使用回滚后的 revision；
4. 已创建 session 不被改写，继续使用原 snapshot。

回滚不删除新 release，也不回滚 vendor 文件。若问题来自 vendor，应先修复并生成新的
release，而不是修改已有 revision。

## 5. 工具形态和目录

建议在 Integration 中增加一个编排入口：

```text
tools/capability-release.py
```

并增加 Make 入口：

```text
make capability-release-check
make capability-release-diff
make capability-release-export
```

建议子命令：

| 子命令 | 作用 | 是否写数据库 |
| --- | --- | ---: |
| `vendor-check` | 检查 Skill/Tool 是否已同步到 Harness vendor | 否 |
| `compile` | 运行 inventory、catalog、Skill manifest 并生成统一 manifest | 否 |
| `check` | schema、依赖、hash、版本和 vendor provenance 校验 | 否 |
| `diff` | 与当前 published release 比较并生成迁移计划 | 否 |
| `export` | 输出可审计的 release artifact | 否 |
| `import` | 调用 NetworkClaw admin import 适配 | 是，且只允许显式发布流程 |

`import` 不应成为普通 `ci-test` 的默认步骤。CI 调用 `vendor-check`、`compile`、
`check` 和必要的 `diff`；生产或受控迁移作业才调用 `import`。

## 6. 与现有工具的融合

Capability Release 不替代现有工具，而是编排它们：

| 现有工具 | 在本设计中的位置 |
| --- | --- |
| `generate-hermes-inventory.py` | Tool/Toolset discovery |
| `project-hermes-catalog.py` | Tool catalog projection |
| `generate-skill-manifest.py` | Skill release projection |
| `validate-contracts.py` | manifest/schema/hash 校验 |
| Harness `sync-hermes-runtime.py` | vendor 同步前置步骤 |
| Harness `verify-hermes-vendor.py` | vendor 完整性 gate |
| `build-bundle.py` | 将已生成的 release artifact 放入 bundle |
| `ci-test.sh` | 调用 release check，不执行生产 import |

不新建第二套 CI、第二套 vendor、第二套 Agent 配置或第二套数据库事实源。

## 7. 失败语义和审计

工具至少输出以下稳定 reason code：

- `vendor_missing`：Skill/Tool 未进入受控 vendor；
- `vendor_hash_mismatch`：vendor 内容与 manifest 不一致；
- `unknown_tool` / `unknown_toolset` / `unknown_skill`：依赖无法解析；
- `dependency_unavailable`：平台、trust 或 required dependency 不满足；
- `stale_revision`：引用的 revision/hash 不是当前 catalog 版本；
- `release_hash_conflict`：同一 release identity 对应不同内容；
- `import_transaction_failed`：数据库事务已回滚。

每次 compile、diff、import、publish、rollback 都应记录：release id、manifest hash、
source identities、操作者/作业身份、结果和 reason code。日志不得包含 Skill 正文、
secret、provider credential 或绝对本机路径。

## 8. 验收标准

1. 从同一 Harness vendor、NetworkClaw 和 Integration source 重复运行 compile，得到
   相同 `release_hash`。
2. 任一 Skill、Tool、Toolset 或 Agent 依赖缺失时，compile/check 失败且不产生可发布
   manifest。
3. 全量 Skill/Tool 都能追溯到 Harness vendor 文件、source ref 和 content/schema hash。
4. 一个完整 manifest 可以在 NetworkClaw 单事务中导入；任一错误都不会留下半套 catalog。
5. 同一 manifest 重复 import 幂等，旧 published release 不被覆盖。
6. 新 release 发布后，新 session 使用新 snapshot，已有 session 行为不变。
7. 旧 `tools_json`/`skills_json` 只作为迁移输入，不再作为新运行时事实源。
8. CI 能执行 vendor-check、compile、check、diff 和 bundle 验证；CI 不直接发布生产数据库。
9. 不修改 Hermes Agent loop、Tool executor、Skill loader 或 NetworkClaw 运行时能力解析逻辑。

## 9. 实施顺序

1. 在 Harness 确认 Skill/Tool vendor allowlist、vendor manifest 和完整性校验覆盖范围。
2. 在 Integration 实现统一 manifest schema、canonical hash 和 `compile/check/diff/export`。
3. 用现有 inventory、catalog、Skill manifest 生成首个 release fixture，并加入 contract test。
4. 在 NetworkClaw 增加最小 admin import adapter 和 repository 事务导入方法。
5. 完成旧 catalog 到新 Agent/Skill/Tool revision 的迁移计划和一次性导入。
6. 在 CI 加入 release check，在受控环境执行 import/publish。
7. 切换新 session 到 published revision，观察后再收口旧写入口。

