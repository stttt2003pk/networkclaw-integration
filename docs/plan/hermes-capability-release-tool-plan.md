# Hermes Capability Release 工具执行计划

## 1. 计划定位

本计划把 [Hermes Capability Release 工具设计](../architecture/hermes-capability-release-tool.md)
拆成可执行模块和任务。目标是得到一个可重复、可审计、可回滚的
`capability-release.v1` 发布闭环：

```text
源码/版本冻结
  -> Harness vendor gate
  -> Tool/Toolset/Skill/Agent discovery
  -> capability-release.v1 compile
  -> check / diff / export
  -> NetworkClaw 单事务 import/publish
  -> 新 session 使用新 snapshot
  -> 迁移、回滚和 bundle/CI 验收
```

本计划不新增 Agent loop、模型调用、Tool handler、Skill loader、权限计算或
session runtime。Integration 只负责编排、编译、校验、diff、artifact 和跨仓验收；
权威业务修改必须回到 `NetworkClaw` 或 `networkclaw-harness`。

## 2. 仓库边界

| 仓库 | 本计划责任 |
|---|---|
| `networkclaw-harness` | Hermes source/vendor 同步、Skill/Tool allowlist、vendor manifest/tree hash、inventory/Skill manifest 输出 |
| `NetworkClaw` | release import admin 入口、repository 事务、publish/rollback 审计、session snapshot 消费 |
| `networkclaw-integration` | release schema、source/provenance 冻结、统一编译、check/diff/export、迁移计划、CI/bundle 和跨仓验收 |

禁止在 Integration 复制 Go 或 Harness 业务源码，也禁止直接编辑
`networkclaw-harness/vendor/hermes`。

## 3. 已有输入与缺口

以下产物可直接复用，但它们还不是完整 release：

- `tools/generate-hermes-inventory.py`：Tool/Toolset inventory；
- `tools/project-hermes-catalog.py`：原子 Tool 和 Toolset catalog；
- `tools/generate-skill-manifest.py`：Skill release manifest；
- `schemas/skill-release-manifest-v1.schema.json`、`schemas/capability-snapshot-v1.schema.json`；
- `tools/validate-contracts.py`、`tools/build-bundle.py`。

当前缺口是统一的 `capability-release.v1` schema、确定性 compiler、vendor gate、
跨对象语义校验、published release diff、NetworkClaw 单事务 importer，以及迁移和
受控发布入口。已有 Tool/Skill/Agent 重建任务的完成记录不能替代本计划的 release
artifact 和跨仓证据。

## 4. 总依赖图

外部前置完成后，按以下顺序执行。箭头左侧的任务必须先完成并通过验收，才可进入右侧任务：

```text
C-00 + T-01 + T-04 + S-01 + I-02
                |
                v
R-00 release contract/provenance
                |
                v
R-01 Harness vendor gate
                |
                v
R-02 Skill/Tool/Toolset/Agent discovery
                |
                v
R-03 unified manifest compiler
                |
                v
R-04 structural and semantic check
                |
                v
R-05 published release diff and migration plan
                |
                v
R-06 export and audit artifact
                |
                v
R-07 NetworkClaw import contract
                |
                v
R-08 transaction import/publish/rollback
                |
                v
R-09 session snapshot switch and legacy migration
                |
                v
R-10 CI, bundle and isolated verification
                |
                v
R-11 cross-repository release acceptance
```

`C-00/T-01/T-04/S-01` 分别对应 [Hermes Capability 重建实施计划](hermes-capability-rebuild-plan.md)
中的公共契约、Tool inventory/catalog 和 Skill manifest 前置；`I-02` 是 Integration
源码解析与诊断任务。它们必须先有可复用的输出，release 工具不重写这些能力。

## 5. 执行模块与任务

### 模块 M0：契约、版本输入和确定性

#### R-00 [P0] 冻结 capability-release.v1 契约和 provenance 输入

**依赖**：`C-00`、`I-02`。  
**主责**：Integration；NetworkClaw/Harness 评审。  
**状态**：已完成（2026-09-30）。

**任务**：

- 新增 `schemas/capability-release-v1.schema.json`，冻结 catalog、toolset、tool、skill、agent、migration 和 source 字段。
- 固定 `release_id`、`release_hash`、schema version、Host Protocol version、目标平台和 session platform 的格式。
- 记录三个源码的 commit/tree hash、dirty/diff hash、Hermes source ref、vendor manifest/tree hash；绝对路径、secret、transcript、时间戳不得进入 content hash。
- 规定 canonical JSON：UTF-8、键排序、语义数组顺序和 `sha256:` 格式，并复用现有 `tools/capability_contract.py` 的规则。
- 明确 legacy Tool 排除清单和 `unknown/unavailable/retired` 的含义，不伪造缺失版本。

**产物**：schema、`docs/contracts/capability-release-v1.md`、最小 valid/invalid fixtures。  
**验收**：同一输入重复 canonicalize 得到相同 hash；schema、fixture 和错误码可由 `make validate-contracts` 检查。

**完成记录（2026-09-30）**：

- 新增 [`schemas/capability-release-v1.schema.json`](../../schemas/capability-release-v1.schema.json)，冻结 release id/hash、三仓 provenance、Hermes vendor provenance、Host Protocol/目标平台、Catalog、Toolset、Tool、Skill、Agent 和 migration 字段。
- 新增 [`docs/contracts/capability-release-v1.md`](../contracts/capability-release-v1.md)，冻结 canonical JSON、`sha256:` hash、状态/失败语义、legacy Tool 排除清单和 admin-only import 边界。
- `tools/capability_contract.py` 新增 `release_hash()`；release hash 删除自身后按现有 canonical JSON 规则计算，不包含时间、绝对路径、secret、transcript 或 runtime 实例。
- 新增 `tests/fixtures/capability-release/valid-release-v1.json` 和 `invalid-release-hash.json`；正例固定 hash 为 `sha256:00237653ec8f7656fb3a675fe7526f6fdf8b2738636a9ba523188e8525e2e612`，负例固定 `release_hash_invalid` reason code。
- `tools/validate-contracts.py` 已接入 release schema、正例 hash 和负例 reason code 校验；验证器保持只读，不会自动改写 fixture。
- 验证：`make validate-contracts` 通过；`.venv/bin/python -m unittest tests.test_capability_contract -v` 通过 4 项；`git diff --check` 通过。

**下一步**：进入 **R-01 Harness vendor gate**。先在 `networkclaw-harness` 完成并验证 pinned source、allowlist、vendor manifest/tree hash 和 support-file 完整性，再在 Integration 接入 `vendor-check`；vendor gate 通过前不开始 R-02 discovery 或 R-03 compile。

### 模块 M1：Harness vendor 和能力输入

#### R-01 [P0] 建立 Skill/Tool vendor gate

**依赖**：`R-00`；Harness 的 vendor sync/verify 脚本。  
**主责**：`networkclaw-harness`；Integration 接入 gate。  
**状态**：已完成（2026-09-30）。

**任务**：

- 在 Harness 侧确认 builtin Skill、Tool、Toolset 的 pinned source、allowlist、metadata、support files 和 handler provenance。
- 通过 Harness 现有 `sync-hermes-runtime.py` 和 `verify-hermes-vendor.py` 完成同步和完整性校验，不直接改 vendor 树。
- 在 Integration 增加 `tools/capability-release.py vendor-check`，检查 vendor manifest、tree hash、Skill support file hash 和排除清单。
- vendor 缺失或 hash 不匹配时返回稳定的 `vendor_missing` / `vendor_hash_mismatch`，禁止继续 compile。

**产物**：vendor gate 适配、vendor fixture、Harness 侧变更说明。  
**验收**：正常 vendor 通过；删除、篡改或未 allowlist 的 Skill/Tool 均 fail closed，且不生成可发布 manifest。

**完成记录（2026-09-30）**：

- 复用 Harness 官方 `networkclaw-harness/scripts/verify-hermes-vendor.py`，验证 pinned Hermes source commit、allowlist hash、patch series、license/capability manifest 和逐文件 vendor hash；当前 vendor snapshot 为 1104 个文件，其中新增 331 个 Hermes Skill 相关文件，source commit 为 `6005aa1fd9aac8b1024ace50fec8cd1c85a04bae`。
- 新增 [`tools/capability-release.py`](../../tools/capability-release.py) 的 `vendor-check` 子命令：不复制 Harness 业务源码，调用官方 verifier，并计算 vendor manifest/tree hash、patch/allowlist provenance、Skill release metadata/content/manifest/support-file hash 和固定 legacy Tool 排除清单。
- `vendor-check` 同时编排现有 `generate-hermes-inventory.py`：当前对账 60 个静态 Toolset、34 个 registered Toolset、101 个 registry Tool/handler source 和 101 个 unique Tool；若 Skill 依赖 legacy 排除工具则以 `dependency_unavailable` fail closed。当前 inventory 中观察到的 `web_search` 只进入排除清单，不进入 release。
- 新增 `make capability-release-vendor-check`，默认将脱敏 gate 报告写入 `.integration-state/evidence/capability-release-vendor-gate.json`；可提交证据见 [`capability-release-vendor-gate-v1.json`](../evidence/capability-release-vendor-gate-v1.json)。报告不包含本机绝对路径、secret 或 Skill 正文。
- 新增 [`tests/test_capability_release_vendor.py`](../../tests/test_capability_release_vendor.py)，临时 Harness 副本分别注入 vendor 内容篡改、未 allowlist 文件和缺失文件；三种情况均被 verifier 拒绝，验证正常 gate 不会放行不完整或不一致 vendor。
- 当前 Harness Skill release 输入为 59 个 Skill（58 个 Hermes vendor Skill 加 1 个 builtin `workspace-inspection`）；每个 Skill 的 content/metadata/manifest hash、support files 和依赖均已进入 gate 报告。Hermes vendor Skill 共包含 58 个 `SKILL.md` 和 259 个 support files。
- 验证：`make capability-release-vendor-check` 通过；Harness `tests/test_vendor_supply_chain.py` 通过 3 项；Integration capability contract/vendor focused tests 通过 5 项；`make test` 通过 87 项 Python 测试及 `go test -race ./tools/web2-server`；`git diff --check` 通过。未直接编辑 `networkclaw-harness/vendor/hermes`。

**下一步**：进入 **R-02 Skill/Tool/Toolset/Agent discovery**。复用已通过 gate 的 inventory、catalog 和 Skill manifest，新增统一 discovery artifact；先对账 Toolset membership、Skill dependency 和 NetworkClaw Agent/profile revision 输入，再开始 R-03 unified compiler。

#### R-02 [P0] 编排 Skill、Tool、Toolset 和 Agent discovery

**依赖**：`R-01`、`T-01`、`T-04`、`S-01`。  
**主责**：Integration；Harness/NetworkClaw 提供受支持的读取入口。  
**状态**：已完成（2026-09-30；2026-10-01 补齐追溯字段并复验）。

**任务**：

- 调用现有 inventory、catalog 和 Skill manifest 生成器，不复制解析逻辑。
- 从 NetworkClaw Agent/profile 配置读取 Agent revision 输入；不得把 transcript 或 session runtime 当作配置事实源。
- 对 Skill 解析 `required_toolsets`、`required_tools`、platform/trust/release 状态、metadata/content/support file hash。
- 对 Toolset 展开原子 Tool membership；对 Agent 记录 requested toolsets、最终 allowed tools 候选和 Skill bindings。
- 统一 source identity、revision、schema/content/manifest hash 和 availability 字段，输出确定性 discovery artifact。

**产物**：`tools/capability-release.py discover`、discovery fixture、字段对账报告。  
**验收**：Tool、Toolset、Skill、Agent 每个对象都能追溯到来源和 hash；未知对象返回 `unknown_tool`、`unknown_toolset` 或 `unknown_skill`。

**完成记录（2026-09-30）**：

- `tools/capability-release.py discover` 复用既有 Hermes inventory、catalog 和合并后的 Skill manifest，并读取显式的 `networkclaw.agent-revision-export.v1` Agent/profile 输入；不从 transcript、session runtime 或旧 `tools_json`/`skills_json` 推断配置事实。
- Discovery artifact [`docs/evidence/capability-discovery-v1.json`](../evidence/capability-discovery-v1.json) 已固定 Toolset membership、Tool revision/schema hash/source/availability、Skill revision/content/metadata/manifest/support-file hash、Skill dependency、Agent requested toolsets/allowed tools/denied tools/Skill bindings，以及三仓 provenance。
- 当前 discovery 对账为 64 个 Toolset、101 个 Tool、59 个 Skill、1 个 Agent；`maps` 正确解析 `terminal` 依赖，`sdlc-review` 正确解析 `kanban` 依赖。未知依赖 fail closed，并稳定返回 `unknown_tool`、`unknown_toolset` 或 `unknown_skill`。
- 新增 [`tests/fixtures/capability-release/agent-discovery-v1.json`](../../tests/fixtures/capability-release/agent-discovery-v1.json) 和 [`tests/test_capability_release_discovery.py`](../../tests/test_capability_release_discovery.py)，覆盖确定性、对象数量、依赖展开和未知 Toolset 拒绝；`source_tree.py` 排除 discovery 自身生成 artifact，确保默认输出路径重复运行仍保持相同 tree hash 和 JSON。
- 证据与验证：`make capability-release-vendor-check` 通过；Harness vendor verifier 通过（1104 个文件）；Harness vendor supply-chain/Skill manifest 测试通过；Integration capability release vendor/discovery focused tests 通过 4 项；`git diff --check` 通过。

**补充完成记录（2026-10-01）**：

- 复用现有 discovery 编排，成功产物新增已通过 gate 的 Hermes source/vendor manifest/tree、allowlist 和 patch provenance；`inputs.agent_export_hash` 对实际读取的 Agent/profile 配置执行 canonical JSON SHA-256，补齐外部配置的追溯依据，不写入本机路径或配置正文。
- `make capability-release-discover` 支持 `CAPABILITY_RELEASE_AGENTS` 指定配置输入；CLI 支持 `--agents`。默认输入仍为 `tests/fixtures/capability-release/agent-discovery-v1.json`，本次 1 个 Agent 的证据来自测试 fixture，未读取或修改生产数据库，也不将 fixture 的 revision hash 宣称为真实数据库导出证据。
- 重新生成 [`capability-discovery-v1.json`](../evidence/capability-discovery-v1.json)：64 个 Toolset、101 个 Tool、59 个 Skill（58 个 vendor Skill 加 1 个 Harness builtin）和 1 个 fixture Agent。Toolset membership 引用已存在的原子 Tool revision；Tool schema/source、Skill platform/trust/release/content/metadata/manifest/support-file 和 Agent 配置输入均可追溯。
- 扩展 `tests/test_capability_release_discovery.py`：重复 discovery 一致、vendor/input hash、全量 membership 引用、Skill hash 及三个独立负例 `unknown_toolset`、`unknown_tool`、`unknown_skill` 均通过；失败报告保持 `status=failed`，现有 compiler 拒绝失败 discovery 并且不生成 release。
- 验证：`make validate-contracts capability-release-vendor-check` 通过；Integration `tests.test_capability_contract`、`tests.test_capability_release_vendor`、`tests.test_capability_release_discovery`、`tests.test_capability_release_compile` 共 10 项测试通过；Harness `tests/test_vendor_supply_chain.py`、`tests/test_hermes_vendor_skill_manifest.py`、`tests/test_skill_release_manifest.py` 共 16 项通过。`make capability-release-discover` 默认输出重复运行逐字节一致；`git diff --check` 通过。
- 本次复验（2026-10-01）：`make capability-release-vendor-check capability-release-discover` 通过；`tests.test_capability_release_discovery`、`tests.test_capability_release_vendor`、`tests.test_capability_contract` 共 8 项 focused tests 通过；生成报告保持 `status=passed`，对账数量仍为 64 个 Toolset、101 个 Tool、59 个 Skill 和 1 个 Agent；`git diff --check` 通过。
- 三仓状态：本次仅修改 Integration 的 discovery 工具、Make 入口、测试、计划和 discovery evidence；NetworkClaw/Harness 无本次源码或 vendor 修改，保留三个仓库原有未提交变更。NetworkClaw 全仓回归、真实数据库导出和 session 迁移不属于本次 R-02 验收。

**复验记录（2026-10-02）**：

- `make validate-contracts capability-release-vendor-check capability-release-discover` 通过；Harness vendor verifier 校验 1104 个 vendored files。
- `.venv/bin/python -m unittest tests.test_capability_release_discovery -v` 通过 2 项，覆盖重复 discovery 一致性、64 个 Toolset、101 个 Tool、59 个 Skill、1 个 Agent、Toolset membership、Skill dependency，以及 `unknown_toolset`、`unknown_tool`、`unknown_skill` 三类 fail-closed。
- 连续两次 `make capability-release-discover` 生成的 `.integration-state/evidence/capability-discovery-v1.json` 字节完全一致；当前 Agent 输入仍是显式 `tests/fixtures/capability-release/agent-discovery-v1.json`，因此本记录不把 fixture revision hash 宣称为生产数据库导出 provenance。
- `git diff --check` 通过。Integration、NetworkClaw、Harness 的既有未提交修改均保留；本次未直接编辑 `vendor/hermes`。

**本地联调补充记录（2026-10-02）**：

- 修复 `make dev-up` 首次空库只启动服务但没有可消费 published catalog 的问题：当 `capability_releases` 为空时，自动复用 vendor gate、discovery、compile、check，并通过本地 seed admin 完成 import/publish；重复启动发现已有 release 时保持幂等并跳过 bootstrap。
- Capabilities 页面改为先读取 `/api/v1/capabilities/catalog` 的实际 published version，再请求 Toolset/Tool；不再固定请求不存在的 `v1`。本地发布版本为 `hermes-tool-inventory-v1`，对账为 64 个 Toolset、101 个 Tool、59 个 Skill。
- 增加 admin client 的 `Origin`/CSRF 请求头，并修复 macOS 已退出子进程的回收判断；`make dev-up` 当前可保持前端 `http://127.0.0.1:5174/`、Lobby `http://127.0.0.1:8080` 和 chatrtmgr `127.0.0.1:50052` 运行。
- 验证：Integration `.venv/bin/python -m unittest tests.test_workspace_tools tests.test_capability_release_admin -q` 通过 22 项；NetworkClaw web2 `npm test -- src/api/capability.test.ts` 通过 4 项；登录后 catalog/Toolset/Tool/Skill 接口均返回 HTTP 200 且数量对账通过，浏览器刷新 `/capabilities` 后已展示目录。三个仓库 `git diff --check` 均通过；本记录仅确认本地目录消费，不替代 Linux 发布或 session grant 验收。

**下一步**：R-02 的直接后继是 **R-03 unified manifest compiler**，以 discovery artifact 编译 `capability-release.v1`。按当前计划状态，R-03 至 R-10 均已有完成记录，因此整份计划首个待实施任务为 **R-11 跨仓 release acceptance**。

### 模块 M2：统一编译与离线校验

#### R-03 [P0] 实现 capability-release.v1 compiler

**依赖**：`R-00`、`R-02`。  
**主责**：Integration。  
**状态**：已完成（2026-09-30）。

**任务**：

- 新增 `tools/capability-release.py compile`，合并 catalog、Toolset、Tool、Skill、Agent 和 migration 输入。
- 生成稳定的 release/catalog/toolset/tool/skill/agent revision 关系；Agent 通过 revision 引用，不保存不可审计的 `tools_json`/`skills_json` 事实。
- 计算 canonical `release_hash`，并把 source/provenance、vendor hash、schema version 和目标平台写入 manifest。
- 为同一输入提供幂等输出；时间、绝对路径和本机环境噪声不能改变 hash。

**产物**：`schemas/capability-release-v1.schema.json` 对应 compiler、`tests/fixtures/capability-release/`、manifest 示例。  
**验收**：同一三仓输入重复 compile 的 `release_hash` 和对象顺序一致；任一缺失依赖不产生可发布输出。

**完成记录（2026-09-30）**：

- 新增 `tools/capability-release.py compile` 和 `make capability-release-compile`，以 R-02 discovery artifact 为输入，重新执行已通过的 Harness vendor gate，生成 `capability-release.v1` draft manifest。
- 编译结果 [`docs/evidence/capability-release-v1.json`](../evidence/capability-release-v1.json) 包含三仓 provenance、Hermes source/vendor manifest/tree hash、Host Protocol/capability schema、目标平台、Catalog、64 个 Toolset、101 个 Tool、59 个 Skill、1 个 Agent 和空 migration 输入；Agent 只保存 revision 引用，不写入 `tools_json`/`skills_json` 或运行时 binding 细节。
- `release_hash` 使用 `tools/capability_contract.py` 的 canonical JSON 规则计算；固定 release id、同一 discovery 输入重复编译时，manifest、对象顺序和 hash 完全一致。release 输出通过 `capability-release-v1.schema.json` 校验。
- Discovery 失败、vendor gate 失败或 release id 不合法时返回稳定 reason code，且不会写出 release artifact；编译边界会裁剪 Skill binding 的运行时字段，只保留 schema 规定的 `{name, revision}` 引用。
- 新增 [`tests/test_capability_release_compile.py`](../../tests/test_capability_release_compile.py)，覆盖重复编译一致性、release hash、对象数量、draft 状态和失败输入不产出 artifact。
- 验证：`make validate-contracts` 通过；R-03/R-02/R-01 focused tests 通过 6 项；完整 `make test` 通过 92 项 Python 测试及 `go test -race ./tools/web2-server`；`git diff --check` 通过。

**下一步**：进入 **R-04 structural and semantic check**。对 R-03 manifest 增加只读 schema/hash/provenance、Toolset membership、Skill dependency、Agent reference 和 unavailable/retired 状态校验，再进入 R-05 diff/migration。

#### R-04 [P0] 实现结构、语义和 provenance check

**依赖**：`R-03`。  
**主责**：Integration。  
**状态**：已完成（2026-09-30）。

**任务**：

- 新增 `capability-release.py check`，执行 schema、hash、revision、vendor provenance、toolset membership、Skill dependency 和 Agent reference 校验。
- 校验 Toolset 展开结果与 `allowed_tools` 一致；拒绝 unavailable/retired/不可信或未发布 Skill。
- 对 required Tool/Toolset 缺失、stale revision、重复 revision 和 catalog 覆盖分别返回稳定 reason code。
- `check` 只读，不调用生产 import，不修改现有 catalog。

**产物**：check report、reason-code fixture、负面测试。  
**验收**：`vendor_missing`、`dependency_unavailable`、`stale_revision` 等错误可稳定复现；通过的 manifest 才标记为可导出。

**完成记录（2026-09-30）**：

- 新增 `tools/capability-release.py check` 和 `make capability-release-check`；check 只读读取 R-03 manifest，不调用 NetworkClaw import，也不修改 catalog。
- Check report [`docs/evidence/capability-release-check-v1.json`](../evidence/capability-release-check-v1.json) 已通过 schema、canonical `release_hash`、三仓 source identity、Hermes vendor manifest/tree hash、Toolset membership、Skill dependency 和 Agent reference 校验。
- 语义校验确认 Toolset 是 Agent 的候选集合，`allowed_tool_revisions` 必须来自请求 Toolset 的展开结果，并排除 denied、unavailable 和 retired Tool；Skill 依赖必须引用存在且可用的 Tool/Toolset revision，Skill 必须为 trusted/available；Agent catalog version、Skill/Tool/Toolset revision 必须一致。
- 新增 [`tests/test_capability_release_check.py`](../../tests/test_capability_release_check.py)，覆盖通过路径和稳定错误码 `release_hash_invalid`、`dependency_unavailable`、`stale_revision`、`duplicate_revision`；生成的 capability evidence 已加入 source tree 排除清单，check/export 顺序不会改变 provenance hash。
- 验证：`make capability-release-check` 通过；R-04 focused tests 的 2 个测试方法覆盖 5 个负面/通过场景；Harness vendor verifier 和 Skill/vendor tests 通过；`make validate-contracts`、`make test`（94 项 Python 测试及 Go race 测试）和 `git diff --check` 通过。

**下一步**：进入 **R-05 published release diff and migration plan**。以 R-04 通过的 manifest 为新 release，接入当前 published release 的只读快照，生成新增/删除/内容和依赖变化，以及无法自动映射的迁移项。

### 模块 M3：变更分析、迁移和 artifact

#### R-05 [P0] 实现 published release diff 和 migration plan

**依赖**：`R-04`；当前 published release 的只读导出或快照。  
**主责**：Integration；NetworkClaw 提供只读 release 查询。  
**状态**：已完成（2026-09-30）。

**任务**：

- 新增 `capability-release.py diff`，比较新增、删除、内容变化、依赖变化、Agent binding 变化和 revision 状态。
- 删除只表示新 release 不再引用，不物理删除旧 revision。
- 生成旧 Agent/Tool/Skill 到新 revision 的候选映射，无法确认的项目标记 `unknown`/`unavailable`/`retired`。
- 输出 M0 盘点、M1 首次导入、M2 新 session、M3 收口所需的迁移输入。

**产物**：机器可读 diff、`migration-plan.json`、人工审阅摘要。  
**验收**：相同 manifest diff 为空且幂等；缺失映射不会被自动伪造为可发布绑定。

**完成记录（2026-09-30）**：

- 新增 `tools/capability-release.py diff` 和 `make capability-release-diff`；候选 manifest 必须先通过 R-04 check，published 输入只读比较，不执行 import、publish、rollback 或数据库写入。
- 机器报告 [`capability-release-diff-v1.json`](../evidence/capability-release-diff-v1.json) 比较 `valid-release-v1.json` published 快照和 `cap-2026.09.30-001` 候选 release，记录 Toolset、Tool、Skill、Agent 的新增、删除和内容变化，并单独记录 Skill dependency、Agent binding 和 revision status 变化。
- 当前基线对账结果为新增 224 个 revision、删除 3 个 revision、内容变化 1 个 Tool revision；迁移候选包含 M0 inventory、M1 first import、M2 new session、M3 close old release 四个阶段，3 个无法映射项目均标记为 `retired`，没有自动伪造新 binding。
- 人工审阅摘要见 [`capability-release-diff-review.md`](../evidence/capability-release-diff-review.md)。迁移输出只提供候选和 unresolved 状态，旧 revision 不会被物理删除。
- 新增 [`tests/test_capability_release_diff.py`](../../tests/test_capability_release_diff.py)，覆盖同一 manifest 空 diff/幂等、对象变化、binding/dependency 变化和 unresolved migration；生成的 diff/摘要 evidence 已加入 source tree 排除清单，运行顺序不改变 provenance。
- 验证：`make capability-release-diff` 通过；R-05 focused tests 通过 2 个测试方法；候选 release 的 R-04 check、`make validate-contracts`、完整 `make test` 和 `git diff --check` 通过。

**下一步**：进入 **R-06 export and audit artifact**。把通过 check 的 manifest、diff、migration plan、source lock 和 vendor provenance 组装为可脱离原始工作区验证的 release artifact，并记录 release id、manifest hash、作业身份和结果。

#### R-06 [P0] 生成可审计 release artifact

**依赖**：`R-04`、`R-05`。  
**主责**：Integration。  
**状态**：已完成（2026-09-30）。

**任务**：

- 新增 `capability-release.py export`，输出 manifest、check/diff 报告、source lock、vendor provenance 和 migration plan。
- 支持脱离原始 Git/绝对路径读取；日志和 artifact 不包含 Skill 正文、provider credential 或 secret。
- 为 compile、diff、export 记录 release id、manifest hash、source identity、操作者/作业身份、结果和 reason code。

**产物**：release artifact 目录和 checksum；供 bundle 消费的固定布局。  
**验收**：artifact 在临时目录可独立校验，路径重定位不改变 hash；失败报告不会留下伪造的 published 标记。

**完成记录（2026-09-30）**：

- 新增 `capability-release.py export` / `verify-export` 和 `make capability-release-export` / `capability-release-verify-export`；export 重跑 R-04 check，并重新计算 R-05 diff，拒绝过期或不同 manifest 的报告与审计记录。
- 固定 artifact 布局见 [`capability-release-export-v1.md`](../contracts/capability-release-export-v1.md)：14 个受校验文件包括 manifest、check/diff、独立 `migration/migration-plan.json`、source lock、published 基线快照、vendor provenance、compile/diff/export 审计、release schema 和独立 verifier/公共 hash/scanner；根目录 `checksums.sha256` 包含逐文件 SHA-256。
- `provenance/source-lock.json` 冻结 manifest 对应的三仓 source identity、Host Protocol 和目标平台；不把工作区中指向较早 commit 的 build `sources.lock.yaml` 伪装为该 release 的实际 source identity。vendor provenance 包含 source ref、manifest/tree、allowlist、patch-series/逐 patch hash 和文件数。
- compile/diff/export 的 sidecar 和包内审计记录 release id/hash、三仓 source identity、`--operator`、`--job-id`、result/reason code；失败审计为 `failed`，不写 published 标记。导出在临时 staging 完整校验后才发布目录，拒绝覆盖已有产物，失败清理 staging。
- 复用 bundle 的敏感信息 scanner（抽取至 `tools/artifact_scan.py`，bundle 入口继续调用同一规则），并校验解码后的 JSON 字符串、Skill 正文/credential 字段、绝对路径和不安全路径。审计与 artifact checksum 不进入 release hash。
- 新增 `tests/test_capability_release_export.py` 的 6 个测试方法，覆盖两次 export 的一致性、重定位后从其他 cwd 独立验证、checksum 篡改/symlink 拒绝、过期/失败报告与审计拒绝、正文/credential/private key/绝对路径拒绝、staging 清理、已有 artifact 保留和 compile/diff 失败审计脱敏。
- 本轮变更位于 Integration；NetworkClaw 和 Harness 的现有未提交修改保留。默认 published 输入仍为测试夹具，导出不等于生产发布。
- 最终 artifact 位于 `.integration-state/artifacts/r06-release-final/`；验证摘要见 [`capability-release-export-v1.json`](../evidence/capability-release-export-v1.json)。同一输入两次 export 的 manifest 和 checksum 逐字节一致，目录重定位后使用包内 `verify.py` 在其他 cwd 验证通过，不读取原始 Git 或工作区文件。
- 验证：`make capability-release-export`、`make capability-release-verify-export` 通过；`make test` 通过 102 项 Python 测试（含 6 项 R-06 export 测试和原有 bundle/scanner 回归）及 `go test -race ./tools/web2-server`；`make validate-contracts` 和 `git diff --check` 通过；Harness `verify-hermes-vendor.py` 通过 1104 个文件。NetworkClaw 本轮无源码修改，不重跑其全仓测试。

**下一步**：进入 **R-07 NetworkClaw admin import contract**，冻结 admin-only 的完整 release 输入、draft/import/publish/rollback 响应、幂等 hash/冲突错误和写库前拒绝边界；数据库事务实现按依赖顺序留在 R-08。

### 模块 M4：NetworkClaw 事务发布和运行时切换

#### R-07 [P0] 冻结 NetworkClaw admin import contract

**依赖**：`R-04`、`R-06`、NetworkClaw 的 Agent/Skill/Tool revision 模型。  
**主责**：`NetworkClaw`；Integration 提供 client/fixture。  
**状态**：已完成（2026-09-30）。

**任务**：

- 定义 admin-only 的本地文件或管理 API 输入，接收完整 `capability-release.v1`。
- 冻结 import、publish、rollback 的响应字段、审计结果和 reason code。
- 相同 `release_hash` 必须幂等返回现有版本；同一 identity 对应不同内容返回 `release_hash_conflict`。
- 普通 `ci-test` 不得调用 import；生产发布必须是显式受控流程。

**产物**：Go API/command contract、fixture、Integration client。  
**验收**：合法 manifest 可进入 draft；非法 schema、stale revision、未授权调用均在写库前失败。

**完成记录（2026-09-30）**：

- NetworkClaw 新增 POST /api/v1/admin/capability-releases/actions，由 verified access JWT + admin role 保护；定义 import、publish、rollback 三个显式操作和统一 {code,message,data} 响应。
- 新增 capability-release-admin-v1.schema.json、protobuf message、嵌入的 release schema、fixture 和 Go contract handler。Integration 镜像 schema，新增 tools/capability-release-admin.py；client 使用显式 --execute 和环境变量 token，未接入普通 ci-test。
- 写入前校验覆盖 schema、canonical release hash、duplicate/stale revision、依赖可用性和 trust、Agent grant、catalog/state；相同 release hash 返回 existing/idempotent=true，identity 内容变化返回 release_hash_conflict，publish/rollback 使用 expected published hash CAS。
- 审计 receipt 固定 release identity、catalog/status、result、reason code、operator/job、source tree hashes；错误响应不泄露数据库或绝对路径。Go durable repository transaction 和 catalog/revision persistence 明确留到 R-08。
- 验收报告 capability-release-admin-contract-v1.json 及 27 场景明细 tests/fixtures/capability-release/admin-contract-v1.json 通过；拒绝场景写入增量为 0，Python client 往返通过。
- 验证：NetworkClaw go test -race ./internal/lobby/... 通过；Integration make test 通过 109 项 Python 测试及 go test -race ./tools/web2-server；make capability-release-admin-contract-test 通过；git diff --check 通过。Harness 本轮无修改。

**下一步**：进入 **R-08 单事务 import、publish 和 rollback**，实现 durable catalog/revision persistence、原子回滚、审计落库和故障注入验收。

#### R-08 [P0] 实现单事务 import、publish 和 rollback

**依赖**：`R-07`；`A-01`、`A-03` 的 revision/snapshot 持久化能力。  
**主责**：`NetworkClaw`。  
**状态**：已完成（2026-09-30）。

**任务**：

- 在一个数据库事务中写 catalog、Tool revision、Toolset membership、Skill revision/dependency、Agent revision/binding。
- 完成外键、状态、数量和 hash 校验后才将 draft 标为 published；上一版本标记为 retired/previous。
- 任一步骤失败全部回滚，不修改已发布 revision；重复 import 不重复插入。
- rollback 重新发布已有旧 release，生成新的审计记录，不删除新 release 或回滚 vendor。

**产物**：repository transaction、admin import/publish/rollback、审计记录和 Go 集成测试。  
**验收**：故意在每个写入阶段注入失败，数据库无部分记录；重复 import 幂等；旧 published release 可回滚。

**完成记录（2026-09-30）**：

- NetworkClaw 新增 migration `028_capability_release_transactions`，持久化 release identity/status 和 audit；为 `skill_revisions` 增加显式整数 revision，保留 Skill 正文在 Harness，不把 vendor 内容复制进 Lobby。
- 新增 `capabilityReleasePgRepo`，所有 catalog version、Tool revision、Toolset membership、Skill revision/dependency、Agent revision/binding、release status 和 audit 写入同一个 Serializable PostgreSQL transaction；数据库约束、写后 identity 对账和 transition 内的 mutable-state/hash/status 重检在 published 前生效，Agent revision 随 release 原子切换为 published/retired。
- import 使用 release id/hash 幂等；同一 identity 的不同 manifest 返回 `release_hash_conflict`。publish/rollback 在事务锁内执行 published hash CAS，旧 release 标记 `retired`，新 release 保留；rollback 不修改 vendor，并追加 durable audit。
- 增加可控 failure injection，覆盖 `catalog`、`tools`、`toolsets`、`skills`、`dependencies`、`agents`、`bindings`、`release`、`audit` 以及 transition 的 retire/release/catalog/audit 阶段。任一阶段失败后数据库记录数保持为 0 或原状态。
- 新增 PostgreSQL 集成测试 [`internal/lobby/repository/capability_release_pg_test.go`](../../NetworkClaw/internal/lobby/repository/capability_release_pg_test.go)，证实 9 个 import 阶段和 5 个 transition 阶段原子回滚、重复 import 幂等、旧 published release 可回滚且审计记录保留。
- 证据见 [`capability-release-transaction-v1.json`](../evidence/capability-release-transaction-v1.json)。验证：PostgreSQL 16 fixture 迁移至 028；`go test -race ./internal/lobby/repository -run TestCapabilityRelease -count=1 -v` 通过；NetworkClaw `go test -race ./...` 通过；Integration `make test` 通过 109 项；`make capability-release-admin-contract-test` 通过 7 项；`git diff --check` 通过。Harness 本轮未修改 vendor。

**下一步**：进入 **R-09 session snapshot 和旧 catalog 迁移**。把已发布 release 接入新 session 的 capability/Agent/Skill snapshot，验证发布和回滚不改写运行中 session，并收口旧 `tools_json`/`skills_json` 写入口。

#### R-09 [P0] 接通 session snapshot 和旧 catalog 迁移

**依赖**：`R-05`、`R-08`；`A-03`、`A-07` 的 session/vertical 验收能力。  
**主责**：NetworkClaw；Harness/Gateway 和 Integration 协作。  
**状态**：已完成（2026-10-01）。

**任务**：

- M0 导出旧 `tools_json`/`skills_json`、Agent/profile 和活跃 session，生成候选映射和无法映射清单。
- M1 导入首个 release 并保留旧字段为只读迁移输入；不伪造缺失 vendor 版本。
- M2 让新 session 只消费 published Agent/capability/Skill snapshot；已有 session 保留旧 snapshot。
- M3 观察 snapshot hash、依赖拒绝、unknown/stale revision 和 session 创建结果，再收口旧写入口。
- 发布和回滚不得改写运行中的 session，也不得在运行时长期维护双事实源。

**产物**：一次性 migration command/report、session switch fixture、回滚演练记录。  
**验收**：新旧 session 行为边界正确；旧字段不再被新写入；迁移失败不改变已发布版本。

**完成记录（2026-10-01）**：

- NetworkClaw 以 migration `029_legacy_capability_readonly` 收口 `catalog_agents.tools_json`/`skills_json` 写入口；M0 `MigrationInventory` 使用 Repeatable Read + Read Only 事务导出脱敏旧 Agent、profile/revision、活跃 session hash、published release 和保护状态。`cmd/capability-migration` 生成 `capability-migration.v1` 候选映射；unknown/unavailable/invalid 输入进入 `unresolved`，不伪造 vendor revision，报告默认为 `ready_for_review=false`。
- 新 session 仅解析 published release 的 Agent/profile、显式 allowed Tool/Toolset、Skill version/content/metadata/manifest hash 和依赖，冻结 capability/Skill/Agent snapshots；创建时 Serializable + published-row lock 重验 revision、grant、依赖和 snapshot hash。旧 session、发布和 rollback 保留原 snapshot；同租户同用户 fork 精确继承旧 snapshot。
- Integration 证据 [`capability-session-migration-v1.json`](../evidence/capability-session-migration-v1.json) 通过真实 PostgreSQL + Harness 验收：旧写入拒绝、legacy session 保留、候选池不扩权、stale/unknown/过期/拒绝依赖/tamper fail closed、发布锁竞争、rollback、retired fork、CLI 只读报告、029 down/up 和 Harness 三轮交互。
- 修复 `tools/dev.py` 本地迁移重放：复用 compose 的 `networkclaw_compose_migrations` 文件名/SHA ledger；已安装 029 的旧工作区必须通过 release/session/profile schema marker 才能 baseline，避免历史 seed 在只读 trigger 下重放。证据文件加入 source tree generated exclusion；操作步骤见 [`capability-session-migration-v1.md`](../contracts/capability-session-migration-v1.md)。
- 验证：NetworkClaw `go test -race ./internal/lobby/usecase ./internal/lobby/repository ./cmd/lobby ./cmd/capability-migration -count=1` 通过；真实组合验收 `make capability-release-session-migration-test` 通过；Integration `make validate-contracts`、`python3 -m py_compile tools/dev.py` 和 `git diff --check` 通过。当前组合证据使用隔离 fixture，不等同于生产迁移执行；Harness vendor 本轮未修改。

**下一步**：进入 **R-10 CI、bundle 和隔离验证**，把 R-09 的 migration runbook、schema/evidence、vendor provenance 和三仓 provenance 纳入 CI/bundle，并在脱离原始工作区的 Linux/amd64 环境验证。

### 模块 M5：CI、bundle 和跨仓验收

#### R-10 [P0] 接入 Make、CI 和 bundle

**依赖**：`R-06`、`R-08`、`R-09`。  
**主责**：Integration。  
**状态**：已完成（2026-10-01）。

**任务**：

- 增加 `tools/capability-release.py` 子命令：`vendor-check`、`compile`、`check`、`diff`、`export`、显式 `import`。
- 增加 `make capability-release-check`、`make capability-release-diff`、`make capability-release-export`；`ci-test` 只执行 vendor-check/compile/check/diff。
- 将 release schema、manifest、diff、vendor provenance、migration plan 放入 `build-bundle.py` 产物。
- 在 bundle 中保留三仓 tree/commit/dirty/diff、Harness vendor hash、Host Protocol 和目标平台信息。

**产物**：Make/CI 入口、bundle manifest 更新、drift 检查。  
**验收**：CI 不写生产数据库；bundle 脱离原始工作区仍可执行 check 和 verify；schema/hash drift 会使构建失败。

**完成记录（2026-10-01）**：

- `ci/ubuntu-22.04/ci-test.sh` 增加只读 `capability_release_gates` 阶段，依次运行 vendor-check、compile、check、diff；没有调用 `capability-release-admin.py` 或任何 import/publish/rollback。
- `make bundle` 默认嵌入 audited capability release payload；bundle manifest 新增 `capability_release` identity，包含 release manifest、check/diff、vendor gate、migration plan/runbook 和 release schema。构建前校验 capability release hash、check/diff 状态、三仓 tree/commit/dirty/diff、Harness vendor manifest/tree、Host Protocol/target，以及 Integration/NetworkClaw 两份 schema 一致性；drift 会 fail closed。
- `verify-bundle` 在没有原始工作区的临时解包目录中重新验证 payload、schema、release hash、source/vendor provenance 和 migration plan。证据 [`capability-bundle-isolated-v1.json`](../evidence/capability-bundle-isolated-v1.json) 记录 Mac 隔离目录中 `verify-bundle` 与 capability `check` 均通过且临时目录已清理。
- Bundle 安全扫描保留绝对路径、secret、symlink 和重复路径拒绝；Hermes 文档中的明确占位 token/示例 home 用户名被识别为非凭据示例，不放宽真实凭据检测。`test_capability_bundle.py` 覆盖 payload 自洽和 schema drift 拒绝。
- 验证：vendor/compile/check/diff 全部通过；`make test` 112 项 Python 测试及 `go test -race ./tools/web2-server` 通过；`make validate-contracts`、bundle build/verify、Mac 解包 check/verify 和 Linux/amd64 runtime container 输入检查通过。早期完整 Ubuntu bootstrap 曾因 Docker overlay 磁盘层已满中断，未删除用户 Docker 数据；后续使用临时内存挂载完成同一 bundle 的 Ubuntu 22.04/amd64 隔离 verify/check，正式 clean-source `ci-test.sh` 留给 R-11。

**补充验收记录（2026-10-01）**：

- `tests/bundle/self_test.py` 对含 capability payload 的 bundle 显式运行 `capability_check`，使用解包目录里的 release manifest 和 Harness vendor；普通无 capability payload 的历史 bundle 保持可验证。
- 当前定向验收：`make capability-release-vendor-check capability-release-compile capability-release-check capability-release-diff` 全部通过；`tests.test_capability_bundle` 在无本机预生成归档时也运行 3 项检查，覆盖 payload 自洽、schema drift、hash/source/vendor drift 拒绝，不再跳过 CI gate。
- 当前 bundle `networkclaw-bundle-r10-final.tar.gz` 的 SHA-256 为 `7141fdd0abdd73c85f0275b69ed3953f70993191e49495a6989302d3b623f1ca`，release hash 为 `sha256:51a38c4023afb8278a2d23335de29c0e1a7a26044d28245b6ecf00b0caec6f57`。Mac 隔离 self-test 14 阶段全部退出 0，包含 Harness 测试、Integration 测试、组合矩阵、manifest verify、capability check、重建和重建包 verify，临时目录已清理。
- 使用独立 Ubuntu 22.04.5/x86_64 容器（Python 3.12.14）和临时内存挂载绕过本机 Docker overlay 容量限制；同一最终 bundle 在脱离原始工作区后 `verify-bundle` 和 capability `check` 都退出 0，vendor/hash/Toolset/Skill/Agent 检查全部通过，临时解包目录已清理。脱敏机器证据见 [`capability-bundle-isolated-v1.json`](../evidence/capability-bundle-isolated-v1.json)。没有调用 admin import/publish/rollback。
- 同一 Ubuntu 容器尝试运行完整 `ci-test.sh`：Go race 通过；Harness 为 288 passed、2 failed（`test_offline_release.py`、`test_vendor_supply_chain.py` 依赖外部同步/归档输入）；随后 overlay 写层耗尽，后续 stage/report 无法落盘。该失败报告不被当作 R-10 通过证据，正式 clean-source 全量回归、修复外部输入和有空间 runner 验证转入 R-11。
- 本轮仅补充 Integration 的隔离验证入口、drift 测试和证据；NetworkClaw/Harness 无本轮源码或 vendor 修改，保留三仓已有 dirty 状态。此 bundle 为 customized 本地验收产物；正式 clean-source `ci-test.sh`、Ubuntu 全量跨仓回归和可发布 provenance 由 R-11 继续验收。
- 当前复验（2026-10-01）：重新执行 `make capability-release-vendor-check capability-release-compile capability-release-check capability-release-diff`、`tests.test_capability_bundle`（3 项）、`make validate-contracts` 和 `git diff --check` 均通过；按当前工作区重建并验证 bundle 通过，归档 SHA-256 为 `d291a5f61e883e7d95f4f1da1d8bafaeb6a6945ef5d797cad6d2649c3b4ff8fd`，release hash 为 `sha256:5ce0ffdb02ca8636592a485345d78b9eb46063416c99ab16cd56df8a71d5aaa4`。该归档仍为 customized 本地验收产物。

**下一步**：进入 **R-11 跨仓 release acceptance**，在干净三仓输入上重复 compile/hash/provenance，覆盖 vendor/依赖/Toolset/Agent/hash/事务失败和新旧 session 全链路，并在有可用磁盘的 Ubuntu 22.04 Linux/amd64 runner 上完成正式证据。

#### R-11 [P0] 完成跨仓 release acceptance

**依赖**：`R-10`。  
**主责**：Integration；NetworkClaw/Harness 联合验收。  
**状态**：已完成（2026-10-02）。

**任务**：

- 从固定三仓输入重复 compile，验证 `release_hash`、对象顺序和 provenance 一致。
- 覆盖 vendor 缺失、Skill 依赖缺失、Toolset 成员变化、Agent binding 变化、hash 冲突和事务中途失败。
- 覆盖首次 import、重复 import、publish、rollback、新旧 session snapshot 和旧写入口收口。
- 在 Mac 快速验证和 Ubuntu 22.04 Linux/amd64 目标环境运行同一高层入口；记录三仓分别的 commit/dirty/tree hash 和测试证据。

**产物**：`docs/evidence/capability-release-acceptance.md`、机器可读报告、失败清理记录。  
**验收**：满足架构稿九项验收标准；所有失败路径有稳定 reason code，临时 workspace、进程、socket 和 artifact 清理完成。

**完成记录（2026-10-02）**：

- 新增 [`docs/evidence/capability-release-acceptance.md`](../evidence/capability-release-acceptance.md) 和 [`capability-release-acceptance.json`](../evidence/capability-release-acceptance.json)，分别记录 Mac arm64 dirty 工作区验收和 Ubuntu 22.04 Linux/amd64 ephemeral clean snapshot 验收。两边统一入口五个阶段均通过；Ubuntu clean snapshot 的三仓临时 commit 仅用于验证，不代表真实分支历史。
- `tools/run-capability-release-acceptance.py` 强制使用显式 disposable PostgreSQL DSN，生成脱敏报告并检查临时 workspace 清理；报告覆盖 release gates、29 项 Integration release tests、Harness vendor/Skill tests、admin contract 和 database/session acceptance。
- NetworkClaw `TestCapabilityReleaseAcceptanceCompiledManifest` 直接导入当前完整 manifest，验证 64 个 Toolset、101 个 Tool、59 个 Skill、1 个 Agent 及其 membership/dependency/binding 数量；重复 import 幂等，publish 不改变 manifest hash。
- 真实 PostgreSQL 事务测试覆盖 `catalog`、`tools`、`toolsets`、`skills`、`dependencies`、`agents`、`bindings`、`release`、`audit` 九个失败注入点，全部回滚并返回 `import_transaction_failed`；同一 release identity 携带不同内容返回 `release_hash_conflict`。Session migration 覆盖新旧 snapshot、publish/rollback、legacy 写入口只读和真实 Harness resume。
- Harness vendor gate 在两平台均验证 1104 个文件；vendor source ref、manifest/tree hash、三仓 commit/tree provenance 和完整 release hash 均写入机器报告。未直接编辑 `vendor/hermes`。
- 清理证据确认临时 workspace、PostgreSQL schema、runner 进程和测试 socket 已移除。一次独立完整 `ci-test.sh` 尝试因 runner 缺少 Helm 及 root/path 环境假设失败，未被用作通过证据；R-11 专项入口在同一 Ubuntu 22.04/amd64 runner 上已通过。

**后续**：冻结真实三仓版本并更新 `sources.lock.yaml`，在工具齐全、有可写空间且使用普通用户的 Ubuntu runner 上补齐完整通用 CI；通过后验证签名 bundle/image 和发布 provenance，再由管理员显式执行受控 import/publish。本次 dirty 工作区及临时 clean snapshot 不等同于可发布版本，未写生产数据库。

## 6. 完成定义

只有以下条件全部满足，Capability Release 工具才可标记完成：

1. 同一三仓输入可重复生成相同 `release_hash`，且 manifest 可独立校验。
2. Skill、Tool、Toolset、Agent 都能追溯到 source、vendor/runtime 文件和对应 hash。
3. 缺失、不可信、过期或冲突依赖 fail closed，不产生可发布 manifest。
4. NetworkClaw import/publish/rollback 使用单事务，重复 import 幂等，旧 release 不被原地覆盖。
5. 新 session 使用新 snapshot，已有 session 不被发布或回滚改写。
6. 旧 `tools_json`/`skills_json` 只作一次性迁移输入，不再是运行时事实源。
7. CI 执行 vendor-check、compile、check、diff 和 bundle verify，但不直接发布生产数据库。
8. Mac 与 Ubuntu 22.04/amd64 的跨仓验收、故障清理和 provenance 证据齐全。

## 7. 实施注意事项

- `import` 是受控发布操作，不能成为普通测试或 bundle 构建的隐式副作用。
- vendor 变更必须先在 Harness 仓库完成同步、patch、vendor verify 和回归，再更新 Integration 的 lock/provenance。
- 若现有 `T-*`、`S-*`、`A-*` 任务的契约字段变化，先更新 `R-00` 和 fixture，再继续后续任务。
- 本计划只新增 release 编排和验收；不在 Integration 建立第二套 vendor、Agent 配置或数据库事实源。
