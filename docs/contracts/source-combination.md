# 三仓组合契约

本文件和 `schemas/*.schema.json` 共同定义 Integration 的组合边界。Schema 是机器校验的权威；本文解释运行语义，不复制 Go 或 Python 的业务模型。

## 仓库职责

| 仓库 | 权威内容 | Integration 的使用方式 |
| --- | --- | --- |
| `networkclaw` | Go 后台、chatrtmgr Gateway 路由、Go 测试 | 作为真实源码工作树构建 `lobby`、`chatrtmgr` |
| `networkclaw-harness` | Python Host、Hermes runtime、`vendor/hermes`、Python 测试 | 通过 `python -m networkclaw_harness.host` 提供 JSONL 子进程 |
| `networkclaw-integration` | 编排、组合验收、CI、bundle、部署输入 | 解析前两者并生成交付制品 |

Integration 不要求前两个仓库 clean，也不复制源码。源码路径可以是 sibling、相对路径、绝对路径或 CI 临时 checkout；软链接只是便利入口，不是协议依赖。

## 两种组合模式

`workspace.local.yaml` 是开发模式配置。它允许 dirty tree、IDE attach 和本地未提交修改，路径相对于 Integration 根目录解析。

`sources.lock.yaml` 是 CI/release 模式配置。它记录 repository、ref、commit 和树 hash，构建机在临时目录 checkout 后再验证 hash。没有 Git 的客户源码包使用 tree hash，不能把 Git 历史当成构建前置条件。

## Host Protocol

- 版本：`1.0`。
- transport：chatrtmgr 直接启动 Harness Gateway，通过 UDS 交换 JSONL envelope；Harness 的 stdout 只能包含协议帧，诊断走 stderr。
- 进程边界：Harness Gateway 由 chatrtmgr 按 `user_id` 亲和拥有；不要把 Harness 误建成独立 TCP 服务。旧 chatsvc 仅保留在隔离回退验收和历史读取兼容代码中，不进入生产事件路径。
- 生命周期：`protocol.negotiate` 成功后才视为 Harness ready；`session.open`、`user.input`、`turn.cancel`、`turn.steer`、`session.lease.update` 等命令遵循 Harness 仓库的 catalog。
- 终态：`turn.completed`、`turn.failed`、`turn.cancelled` 是终态事件；`execution_epoch` 用于 takeover fencing，旧 epoch 的控制帧必须被拒绝。
- 终态 envelope/payload 由 `schemas/host-protocol-v1-terminal.schema.json` 约束：payload 必须包含 `outcome`、`end=true`、`reason_code`、`generation`；存在会话时携带 `execution_epoch`。`turn.failed` 可携带 `code`/`retryable`，runtime 元数据保持可选。事件类型和 outcome 必须一一对应。schema 来源对应 Harness `host/server.py::_frame` 的正规化行为及 Go `HarnessHandler` 的消费字段。

## 本地运行约定

Integration 管理 `.integration-state/`（可用 `state_dir` 覆盖）中的 binary、PID、socket、日志和诊断 artifact。停止时只清理它创建的进程和 socket，不删除三个源码仓库或持久 session workspace。可选 `NETWORKCLAW_HARNESS_FRAME_LOG` 只记录不含 payload 的 frame 元数据；request/session 标识使用进程随机密钥 HMAC 摘要。

当前 Go 组合入口是 `cmd/chatrtmgr`，其 Gateway UDS socket 是本地 readiness 信号；Harness 协议协商由 Gateway 启动阶段完成。旧 chatsvc 不属于交付镜像或默认启动路径；Gateway 是唯一实时执行入口。

实时事件合同：Harness execution path 只允许 canonical event envelope 以及
`done`/`error` 控制帧。固定 chunk oneof 和 `harness.Project` 不得被生产消费者
依赖，历史回放适配器必须显式标为 compatibility-only。

## 目标平台

Mac 用于开发、IDE 调试和快速 smoke；正式 Linux/amd64 证据必须在 Ubuntu 22.04 CI 产生。Mac arm64 的构建结果不能替代正式镜像证据。

## 兼容性规则

兼容扩展只能新增可选字段或事件；不能复用已有字段改变语义。协议版本发生破坏性变化时递增 major，并同时更新 Go client、Harness catalog、schema 和组合验收。Manifest 记录一次组合构建的 provenance，而不是要求客户保留我们的提交历史。
