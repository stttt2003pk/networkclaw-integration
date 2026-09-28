# E-01 Transport Evidence

日期：2026-09-27

## 交付

E-01 在 NetworkClaw 的 Gateway → chatrtmgr → lobby 载体上完成。`ForwardStreamResponse` 新增 `canonical_event = 10` opaque bytes 字段；旧 `oneof chunk` 保留，作为迁移期兼容 projection。canonical event 不在中间层重新命名或压缩为 `run_state`/`chunk`。

Gateway 对每个 Harness frame 生成原始 JSON envelope，并把它放入 `canonical_event`：

```text
Harness JSONL frame
  -> Gateway CompatChunk.canonical_event
  -> chatrtmgr ForwardStreamResponse.canonical_event
  -> lobby StreamChunk.canonical_event
```

未知事件使用 `type=canonical_event` 的迁移载体，chatrtmgr 返回只有 `canonical_event` 的 response，lobby 以 `StreamChunkCanonicalEvent` 保留事实。已知旧事件仍可同时产生 oneof projection，因此 E-01 不要求 E-02 之前改变用户面。

## 边界

- canonical event 最大 64 KiB；超限生成结构化错误并终止当前流。
- lobby 校验 `protocol_version=1.0`、非空 `type`、非零 `sequence`、JSON 合法性以及 session/run identity；不匹配直接拒绝。
- terminal oneof（done/error）和 canonical terminal envelope 同时保留；上游没有 terminal 不伪造成功。
- Go Harness client 的 pending frame 上限仍为 128；超过上限返回 `ErrProtocol`，形成慢消费者背压证据。
- canonical payload 以 opaque JSON 传输，未知字段和未来事件名不会在 Go oneof 解析时丢失。

## 代码与测试证据

- `NetworkClaw/api/chatrtmgr/v1/chatrtmgr.proto`
- `NetworkClaw/internal/shared/harness/projection.go`
- `NetworkClaw/internal/chatrtmgr/forwarder/gateway.go`
- `NetworkClaw/internal/chatrtmgr/transport/grpc/server.go`
- `NetworkClaw/internal/lobby/usecase/grpc_forwarder.go`
- `NetworkClaw/internal/lobby/model/response.go`
- `NetworkClaw/internal/chatrtmgr/transport/grpc/canonical_event_test.go`
- `NetworkClaw/internal/lobby/usecase/canonical_event_test.go`
- `NetworkClaw/internal/shared/harness/client_test.go::TestClientPending_BoundsBufferedFrames`

验证命令：

```text
cd <networkclaw-checkout>
go test ./internal/shared/harness ./internal/chatrtmgr/forwarder ./internal/chatrtmgr/transport/grpc ./internal/lobby/usecase
go test -race ./internal/shared/harness ./internal/chatrtmgr/transport/grpc ./internal/lobby/usecase
```
