# E-03 Relay / Replay Evidence

日期：2026-09-27

## 交付

chatrtmgr 已增加 canonical event relay ledger。Gateway 收到 Harness JSONL 事件后：

- 保留原始 `event_id`、`sequence`、`type`、session/run identity 和 payload；不按连接重新编号，也不改事件名。
- 按 `(session_id, run_id)` 隔离事件流；`event_id` 重复且事实相同的帧幂等丢弃，重复 ID 携带不同事实或同 sequence 冲突时显式失败。
- 以 Harness upstream `sequence` 作为 reconnect cursor。乱序到达的事件在 replay 时按 sequence 排序。
- 使用有界 retention；cursor 早于 retained tail 返回 `canonical relay cursor is outside retention`，调用方必须重新建立快照/会话，不能静默补齐。
- epoch 小于当前流的事件或 replay 请求返回 stale epoch；更高 epoch 会关闭旧订阅并建立新 owner 的流，防止旧 owner late event/terminal 泄漏。
- subscriber 使用有界 channel；消费者持续落后时关闭订阅并形成 backpressure，而不是无限缓存。

replay 请求通过 `resume_sequence` 和 `replay_only` 从 Lobby 的 gRPC request 传入 Gateway。`replay_only=true` 只重放 ledger，不重新提交 `user.input`，因此断线恢复不会重复执行模型或工具。

## 代码与测试证据

NetworkClaw：

- `internal/chatrtmgr/forwarder/canonical_relay.go`
- `internal/chatrtmgr/forwarder/canonical_relay_test.go`
- `internal/chatrtmgr/forwarder/gateway.go`
- `internal/chatrtmgr/forwarder/gateway_test.go`
- `internal/shared/harness/client.go`
- `internal/chatrtmgr/transport/grpc/server.go`
- `internal/chatrtmgr/transport/grpc/canonical_event_test.go`
- `internal/lobby/usecase/grpc_forwarder.go`
- `internal/lobby/usecase/routing.go`
- `api/chatrtmgr/v1/chatrtmgr.proto`

验证命令：

```text
cd <networkclaw-checkout>
go test ./internal/shared/harness ./internal/chatrtmgr/forwarder ./internal/chatrtmgr/transport/grpc ./internal/lobby/usecase ./cmd/chatrtmgr
go test -race ./internal/shared/harness ./internal/chatrtmgr/forwarder ./internal/chatrtmgr/transport/grpc ./internal/lobby/usecase
```

覆盖场景：乱序 replay、重复事件幂等、event identity 冲突、retention 外 cursor、旧 epoch、epoch takeover、replay-only 不启动新 turn、Gateway 并发 session、慢 subscriber/backpressure、未知事件和 `event_id` 传输保真。

## 边界

relay ledger 当前是 chatrtmgr 进程本地的有界内存日志；它保证单个 chatrtmgr 实例内的断线重连和 epoch fencing。跨 chatrtmgr 节点迁移时，Lobby 必须在旧 cursor 超出本地 retention 或 manager 失效后走新的 Harness session resume/快照路径；跨节点共享 durable event store 不属于 E-03 的最小交付，列入后续组合验收风险。
