# E-07 canonical-only realtime evidence

日期：2026-09-27

## 结论

Harness 实时执行路径现在只有一套事实源：

```text
Harness Gateway UDS/JSONL
  -> chatrtmgr Gateway forwarder
    -> gRPC canonical_event carrier
      -> lobby canonical validation/relay
        -> WebSocket canonical_event
          -> web2 canonical process projection
```

`done` 和 `error` 只表示传输控制，不承载替代事实。旧 `content`、
`reasoning`、`tool_start`、`tool_end`、`run_state` oneof 不再被 Harness
execution path 接受或发送。

## 实现边界

- `cmd/chatrtmgr` 启动时强制 `CHATRTMGR_PROCESS_TARGET=gateway`。
- `cmd/lobby` 启动时强制 Harness enabled 且 rollout 为 100%，不再把生产 run
  分配到 legacy execution path。
- Gateway replay 返回 canonical tail，最后追加 `done`，不会重新提交 `user.input`。
- lobby 的 recording emitter 从 canonical `assistant.delta`、`tool.started`/
  `tool.completed` 和受限 reasoning summary 读取落库摘要；child tool 通过
  `parent_item_id` 保留归属。
- web2 `HomePage` 与 semantic reducer 忽略实时旧 chunk；审批和澄清只由
  canonical interaction 事件驱动。旧 parser/projector 仍可用于历史读取和隔离
  legacy 对照测试。

## 代码证据

NetworkClaw：

- `cmd/chatrtmgr/main.go`
- `cmd/lobby/main.go`
- `internal/chatrtmgr/forwarder/gateway.go`
- `internal/chatrtmgr/transport/grpc/server.go`
- `internal/lobby/usecase/grpc_forwarder.go`
- `internal/lobby/usecase/routing.go`
- `web2/src/api/chat.ts`
- `web2/src/api/semanticProjection.ts`
- `web2/src/pages/HomePage.tsx`

## 验证证据

```text
go test -race ./internal/chatrtmgr/forwarder ./internal/chatrtmgr/transport/grpc \
  ./internal/lobby/usecase ./internal/shared/harness -count=1
go test -race ./tests/integration/harnessinterop -count=1
npm test -- --run
npm run build
```

结果：Go 相关包通过；完整 Harness interop 通过；web2 37 个测试文件、324
项测试中 323 项通过、1 项按条件跳过；TypeScript typecheck 和 Vite build
通过。真实 interop 覆盖 stream、todo、reset、usage、context、delegation、
child failure/deny/timeout、clarification、replay、epoch fencing 和工具副作用。

当前 E-07 bundle 交付验收也已闭环：

- bundle SHA-256：`a7d0cc5e7e18c53edb32753975be038b4a688fc6f2f248d37a7faf498a7ff500`
- `.venv/bin/python tools/verify-bundle.py /private/tmp/networkclaw-e07.tar.gz`：通过
- `tests/bundle/self_test.py`：13 个阶段全部通过，`failures=[]`、`missing_inputs=[]`，隔离 workspace 已清理
- 机器报告：[bundle-self-test-e07-final.json](../../.integration-state/evidence/bundle-self-test-e07-final.json)

## 兼容边界

`internal/shared/harness/projection.go`、chatsvc projection 和固定 oneof
类型仍作为历史读取/隔离回退代码存在，但没有生产实时消费者。任何重新启用
legacy execution path 的部署必须先恢复独立迁移开关和对应验收，不属于当前交付
拓扑。
