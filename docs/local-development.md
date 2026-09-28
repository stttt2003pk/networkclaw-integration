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

`make dev-up` 启动宿主机进程全栈：本地构建 `lobby`、`chatrtmgr`，由 chatrtmgr 以 `target=gateway` 管理按用户亲和的 Harness Gateway，并运行 NetworkClaw `web2` 前端。Gateway 通过 UDS + JSONL 承接 session 和事件。启动前需已安装 `NetworkClaw/web2` 的 npm 依赖。它连接已经安装并运行的本机 PostgreSQL（默认 `127.0.0.1:5432`）和 Redis（默认 `127.0.0.1:6379`），通过共享本地 registry 文件发现 chatrtmgr，不依赖 etcd 或 Docker Compose。`make dev-up` 返回成功时，前端 `http://localhost:5174/` 与 lobby API `http://127.0.0.1:8080` 均已就绪。`make dev-down` 只停止 Integration 启动的进程，不停止本机 PostgreSQL/Redis，也不触碰 Compose 栈。

provider 环境默认读取 NetworkClaw 根目录的 `.env`（若存在），也可由 `provider_env_file` 或 `NETWORKCLAW_PROVIDER_ENV_FILE` 指定。已导出的 shell 环境优先于文件值；文件内容和变量值不会写入诊断或日志。

默认状态目录是 `.integration-state/`，包含 Gateway/chatrtmgr PID、binary、UDS socket、logs 和诊断 JSON。`gateway-frames.jsonl` 只记录方向、协议版本、帧类型、字节数和进程内随机密钥生成的 request/session ID 短摘要，不记录 payload、transcript 或原始 ID；文件权限为 owner-only。该文件是协议帧元数据 artifact，不是可重放的完整 frame dump。

`make logs` 跟踪 Gateway 日志，`make collect-diagnostics` 生成环境/源码/PID/UDS/分层状态摘要。Integration 不创建/清理持久 session workspace，也不删除源码。

Mac 本地负责快速反馈和调试；最终 Linux/amd64 镜像仍由 Ubuntu 22.04 CI 构建。
