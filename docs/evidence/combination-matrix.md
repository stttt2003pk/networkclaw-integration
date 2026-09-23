# I-05 组合验收矩阵

I-05 的统一入口是：

```bash
make integration-test
```

它运行 Integration 离线夹具、真实 NetworkClaw Go client ↔ Python Harness 进程验收、Go transport/lifecycle 支撑测试，以及 Harness recovery/delegation 验收。机器可读报告写入 `.integration-state/evidence/combination-matrix.json`，同目录的 Markdown 文件由同一命令生成。

## Mac 验收结果

2026-09-23 在当前 Mac sibling 工作区执行，矩阵状态为 `passed`。组合场景与稳定 reason code 如下：

| 场景 | 证据类型 | 真实测试 | reason code |
|---|---|---|---|
| 单 Session vertical flow：negotiate → open → input/event → terminal → close | 跨仓 | `TestSingleSessionVerticalFlow` | `completed`, `provider_succeeded` |
| 多 Session multiplexing | 跨仓 | `TestProviderBackedSessionsMultiplexWithoutCrossTalk` | `completed` |
| 同 Session admission、active steer/cancel | 跨仓 | `TestSameSessionAdmissionAndActiveControl` | `turn_already_active`, `user_cancel` |
| lease takeover 与旧 epoch control 拒绝 | 跨仓 | `TestLeaseTakeoverFencesOldOwnerAcrossProcess` | `stale_epoch`, `epoch_takeover` |
| provider stream / transport interruption | 跨仓 | `TestProviderStreamingDropIsNotCompleted`, `TestProviderStreamAndTransportFaultCombination`, `TestReasonCodesEndToEndThroughClient` | `provider_interrupted`, `provider_stream_interrupted`, `provider_transport_reset` |
| request replay 与 hash conflict | 跨仓 | `TestRequestReplayAndHashConflictAcrossProcess` | `request_id_conflict` |
| SIGKILL、replacement、同 workspace 恢复 | 跨仓 | `TestPythonHarness_SigkillThenReplacementEpoch`, `TestPythonHarness_KillDuringProviderThenReplacementResumesSameWorkspace` | `harness_unavailable`, `epoch_takeover` |
| EOF fan-out 与 pending backpressure | 跨进程支撑 | `TestClient_ChildEOFFailsAllPendingCalls`, `TestClientPending_BoundsBufferedFrames` | `harness_unavailable`, `backpressure` |
| lease revoke、旧 binding 拒绝、late frame/terminal 过滤 | Go lifecycle 支撑 | `TestHarnessHandler_LeaseVersionAdvancesButOldEpochCannotRevoke`, `TestHarnessHandler_RevokeRejectsLateControl`, `TestHarnessHandler_TakeoverFencesLateEpochFrames`, `TestHarnessHandler_ReducesToFirstTerminalAndDropsLateEvents` | 不适用：断言生命周期拒绝和 late-frame 过滤，不断言稳定 reason code |
| parent/child session-local interrupt scope | 跨仓 | `TestParentChildInterruptScopeIsSessionLocal` | `user_cancel` |
| unknown side effect 不自动 replay、child grant exactly-once release | Harness recovery/delegation 支撑 | `tests/test_recovery*.py`, `tests/test_delegation.py` | `unknown_side_effect`, `delegation_broker_closed` |

矩阵中的 reason code 是相应测试断言的预期值；脚本检查这些指定测试确实执行并通过，不会从运行时事件自动抽取 reason code。旧 epoch revoke 不是 Harness wire protocol 中带 epoch 的操作，因此旧 binding 的 revoke 拒绝由 Go chatsvc lifecycle 单测验证，不冒充跨仓场景。矩阵脚本会在任一命令失败、任一指定 Go 测试未执行或任一场景状态不是 `passed` 时返回非零退出码。报告只保存命令元数据、测试状态和有限输出尾部，不保存 provider payload、Authorization、API key 或 transcript。

## 平台边界

这份证据是 Mac 本地 smoke/full matrix，证明三个源码工作树可以联动调试。Ubuntu 22.04 Linux/amd64 上执行同一完整矩阵属于 I-08；I-05 不把 Mac 结果当成目标镜像构建证据。
