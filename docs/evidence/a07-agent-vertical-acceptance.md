# A-07 Agent 全链路验收

状态：**通过（2026-09-29，Mac 当前三仓工作区）**。

统一入口：

```text
make integration-test
```

机器报告：`.integration-state/evidence/combination-matrix.json`；本次报告的
`status` 为 `passed`，13 个场景均为 `passed`，清理状态为 `clean`，没有残留
Gateway/provider 进程或测试 socket。

## 验收映射

| A-07 要求 | 当前证据 |
|---|---|
| Agent revision、model/provider、toolset、Skill、delegation policy 和预算投影 | `NetworkClaw/internal/lobby/usecase/agent_revision_test.go`、`tests/integration/harnessinterop/session_snapshots_test.go`、Harness delegation tests |
| user_id 复用 Gateway，多 session 独立 runtime/cache | `TestProviderBackedSessionsMultiplexWithoutCrossTalk` |
| 主 Agent 工具、Skill explicit load、两个 child 和 child 工具 | `TestRealGatewayCanonicalLedger/{todo,delegate}`、`TestSkillVerticalSliceHostProtocol` |
| 发布后旧 session 保持 snapshot，新 session 使用新 revision | `TestSessionSnapshotsSurviveCatalogPublishInSharedGateway` |
| lease/fence、cancel/steer、provider retry/interruption、tool deny | `TestLeaseTakeoverFencesOldOwnerAcrossProcess`、`TestSameSessionAdmissionAndActiveControl`、`TestReasonCodesEndToEndThroughClient/*`、`TestRealGatewayCanonicalLedger/delegate-deny` |
| Skill dependency failure、child failure/timeout | `TestSkillVerticalSliceHostProtocol`、`TestRealGatewayCanonicalLedger/{delegate-failure,delegate-timeout}` |
| canonical event replay 与 web2 过程树重建 | `durable-child-replay-restart`、`frontend-process-ledger`、`TestRealGatewayCanonicalLedger/*` |

组合矩阵还验证 EOF/backpressure、request replay/hash conflict、parent/child
interrupt scope、late frame fencing 和 exactly-once child release。报告只保存命令元数据、
测试状态和受限输出尾部，不保存 provider payload、token 或 transcript。

