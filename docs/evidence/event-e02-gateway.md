# E-02 Gateway Producer Evidence

日期：2026-09-27

## 交付

Harness Gateway 现在直接把 HermesHostAdapter 的 native callback、delegation broker、工具审计和受控结果元数据写入 canonical event stream；不经过 chatsvc projection。Host JSONL 负责为每个输出事件生成独立 `event_id`、单调 `sequence` 和完整 session/run/turn/request envelope。

已接入的 canonical producer：

- `turn.queued`：Gateway admission
- `turn.started`、`turn.completed`、`turn.failed`、`turn.cancelled`、`assistant.delta`、`plan.updated`
- `tool.generating`、`tool.started`、`tool.progress`、`tool.completed`
- Hermes 原名 `subagent.start`、`subagent.complete`、`subagent.text`、`subagent.thinking`、`subagent_progress`
- `delegation.requested`、`delegation.resolved`
- `approval.requested`、`approval.resolved`
- `clarification.requested`、`clarification.resolved`
- `artifact.created`
- `context.started`、`context.continued`、`checkpoint.updated`
- `provider.attempt`、`provider.retry`、`usage.updated`
- `reasoning.delta`、`moa.reference`、`moa.progress`、`moa.phase`、`moa.aggregating`

Hermes 原始 thinking、reasoning、MoA 和 usage 受 capability gate 约束。未授权时保留事件事实但只发送 bounded summary 或 `warning`；不会把原始思维链、凭证或完整工具结果放入用户事件。

## 能力对账

`capabilities.report.events` 现在报告 baseline 36 个事件与 18 个 process extensions 的并集。`EVENTS` 保持 baseline 兼容集合，`PROCESS_EXTENSIONS` 和 `ALL_EVENTS` 是 Gateway 的 canonical vocabulary。

## 代码与测试证据

Harness：

- `src/networkclaw_harness/protocol/catalog.py`
- `src/networkclaw_harness/host/server.py`
- `src/networkclaw_harness/protocol/frames.py`
- `src/networkclaw_harness/runtime/hermes_host_adapter.py`
- `src/networkclaw_harness/runtime/delegation.py`
- `src/networkclaw_harness/runtime/hermes_tools.py`
- `tests/test_hermes_host_adapter.py`
- `tests/test_delegation.py`
- `tests/test_host.py`

验证命令：

```text
cd <networkclaw-harness-checkout>
./.venv/bin/pytest -q
git diff --check

cd <networkclaw-integration-checkout>
python3.12 -m unittest tests.test_event_contracts
```

结果：Harness 全量测试通过；integration 事件契约 6 项通过。
