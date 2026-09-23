# 故障夹具

Integration 的故障夹具只负责组合边界，不实现 Go 或 Harness 的业务逻辑。夹具全部离线运行，provider 只绑定 `127.0.0.1`，模型 key 使用假的测试值或不发送 key。

## Provider stub

```text
make provider-stub
```

`tests/fixtures/provider_stub/server.py` 提供 OpenAI-compatible `POST /v1/chat/completions` 和 `GET /healthz`。可用模式：

| 模式 | 行为 | reason code |
|---|---|---|
| `stream` | 正常 SSE 响应 | `provider_succeeded` |
| `slow` / `delay` | 分块慢响应或延迟响应 | 由调用方 bounded timeout/cancel 决定 |
| `drop` | 输出 partial chunk 后断流 | `provider_stream_interrupted` |
| `reset` | TCP RST | `provider_transport_reset` |
| `http-error` | HTTP 503 | `provider_http_error` |
| `malformed` | 非法 SSE JSON | `provider_response_invalid` |

默认端口为 0，由 stdout 输出 `READY <port>`；`NETWORKCLAW_PROVIDER_STUB_EVENTS` 可指定脱敏 JSONL 账本路径。账本只允许有限 metadata，不写请求 body、Authorization、API key 或 transcript。

## JSONL transport proxy

`tools/fault-proxy.py` 在真实 Harness 子进程前作为 JSONL relay：

```text
python3 tools/fault-proxy.py --mode drop --after-frames 2 -- \\
  python3 -m networkclaw_harness.host
```

支持 `pass`、`drop`、`reset`、`sigkill`、`disconnect` 和 `stale-terminal`。`stale-terminal` 会把 terminal frame 复制一份并将 `execution_epoch` 减一，验证旧 owner frame 被拒绝；`drop`、`reset` 和 `sigkill` 在有界帧数后分别注入 transport drop、transport reset 和 Harness SIGKILL；`disconnect` 在有界输入帧后关闭 Harness stdin，模拟 Go client disconnect。代理只解析必要的协议 envelope，不记录 payload。

## 进程与清理

`tests/support/process.py` 的 `ManagedProcess` 负责 readiness、stdin disconnect、SIGKILL 和 TERM→KILL 有界回收。所有测试都用临时目录和 teardown，结束后不得遗留 provider、proxy、Harness、socket 或 ledger。

事件账本使用稳定 `reason_code`，测试断言 reason code 和最终协议状态，不断言易变日志文本。
