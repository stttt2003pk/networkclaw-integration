# 本地联合开发

本地联合开发使用三个 sibling Git 仓库，不要求把源码复制进 integration：

```text
workspace/
├── networkclaw/
├── networkclaw-harness/
└── networkclaw-integration/
```

`workspace.local.yaml` 只保存本机路径，不提交到 Git。路径可使用相对 integration 仓库的路径或绝对路径。integration 工具通过它启动两个真实工作树，因此 Go 或 Harness 的未提交修改可以立即参与联调。

本地开发入口：

```bash
make doctor
make dev-up
make integration-test
make dev-down
```

完整组合矩阵也可以单独执行：

```bash
make combination-matrix
```

报告写入 `.integration-state/evidence/combination-matrix.json`，用于查看每个场景的测试名、退出码和稳定 reason code。

故障场景调试可以先单独运行离线夹具：

```bash
make fault-fixtures
```

需要包裹真实 Harness 时，使用 JSONL relay 注入传输故障或旧 epoch terminal：

```bash
python3 tools/fault-proxy.py --mode drop --after-frames 2 -- \
  python3 -m networkclaw_harness.host
```

夹具只用于 Integration 测试和组合验收，不进入客户生产运行时。`drop`、`reset`、`stale-terminal` 的断言应使用稳定 `reason_code`，不要依赖日志文本；所有测试必须回收 provider、proxy、Harness、socket 和临时 ledger。

源码路径配置由 `tools/resolve-sources.py` 统一解析，支持 `workspace.local.yaml` 中相对 integration 根目录的路径、绝对路径和 `NETWORKCLAW_PATH` / `HARNESS_PATH` 显式覆盖。也允许无 Git 元数据的源码包；dirty tree 用于本地开发，不会被拒绝。

`make dev-up` 构建并启动 NetworkClaw 的 `cmd/chatsvc`，Harness 由 chatsvc 启动，使用 JSONL stdin/stdout 协议，不单独开放 TCP 端口。`make dev-down` 只停止 Integration 创建的 chatsvc 并移除 Integration 管理的 socket。`make restart-go` 和 `make restart-harness` 都会重启 chatsvc，因为 Harness 子进程和 JSONL 管道由 chatsvc 拥有；后者的名字表达调试意图，不代表 Harness 是独立服务。

provider 环境默认读取 NetworkClaw 根目录的 `.env`（若存在），也可由 `provider_env_file` 或 `NETWORKCLAW_PROVIDER_ENV_FILE` 指定。已导出的 shell 环境优先于文件值；文件内容和变量值不会写入诊断或日志。

默认状态目录是 `.integration-state/`，包含 chatsvc/Harness PID、binary、socket、logs 和诊断 JSON。Harness PID 和命令从 chatsvc 子进程树解析，用于 IDE attach 与诊断；停止时由 owning chatsvc 回收子进程。`harness-frames.jsonl` 只记录方向、协议版本、帧类型、字节数和进程内随机密钥生成的 request/session ID 短摘要，不记录 payload、transcript 或原始 ID；文件权限为 owner-only。该文件是协议帧元数据 artifact，不是可重放的完整 frame dump。

`make logs` 跟踪 chatsvc 日志，`make collect-diagnostics` 生成环境/源码/PID/路径摘要。Integration 不创建/清理持久 session workspace，也不删除源码。

Mac 本地负责快速反馈和调试；最终 Linux/amd64 镜像仍由 Ubuntu 22.04 CI 构建。
