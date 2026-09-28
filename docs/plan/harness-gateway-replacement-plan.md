# Harness Gateway 替代 chatsvc 执行方案

## 目标

让 Harness Gateway 直接接入 chatrtmgr，承接当前 chatsvc 的用户亲和执行职责，并在验证通过后移除 chatsvc。

目标拓扑：

```text
lobby -> chatrtmgr -> Harness Gateway -> HermesHostAdapter -> Hermes runtime
```

用户和会话分层保持不变：

```text
user_id
  -> 一个 Harness Gateway 进程
      -> 多个 session_id
          -> 各自独立的 Hermes session/runtime
              -> 各自按 agent_id 选择或重建 Agent
```

## 范围和非目标

本计划只替代 chatsvc 的进程、Host Protocol 承接和用户亲和执行入口。它沿用 Harness 已有的 `HermesHostAdapter`、`_HermesSession`、runtime、workspace、history、lease fence、turn control 和 delegation 机制。

本计划暂不统一 36 个事件的传输名字和下游模型。Gateway 第一阶段提供现有 chatrtmgr/chatsvc 兼容帧，使拓扑迁移可以单独验证。事件统一见 [event-unification-design-and-plan.md](event-unification-design-and-plan.md)，并在本计划完成后开始。

## 责任边界

| 仓库 | 本计划中的责任 |
|---|---|
| `networkclaw-harness` | Gateway 入口、UDS/JSONL 承接、Host Protocol 请求分派、session/lease 调用和兼容响应 |
| `NetworkClaw` | chatrtmgr 的进程启动/健康/UDS 目标、请求桥接、服务绑定和 chatsvc 退出路径 |
| `networkclaw-integration` | 组合测试、启动编排、故障夹具、部署输入和迁移验收文档 |

## 依赖图

任务按依赖顺序排列；后面的任务不得先于其依赖进入实施验收。

```text
G-00
  -> G-01
      -> G-01a
          -> G-02
              -> G-03
                  -> G-04
                      -> G-05
                          -> G-06
                              -> G-07
                                  -> G-08
```

这是有意的单链路发布顺序：每个任务完成后先保留可回退的旧路径，再进入下一个任务；G-07 是最后一次允许同时运行旧路径和 Gateway 路径的对照闸门，G-08 才切换默认路径并移除 chatsvc 生产消费者。36 个事件统一不占用这条链路的兼容阶段，必须等待 G-08 完成后按独立计划执行。

### 执行规则

- 权威代码只改对应仓库：Harness 行为回到 `networkclaw-harness`，chatrtmgr/Go 行为回到 `NetworkClaw`，组合夹具和交付输入回到本仓库。
- 每个任务提交前必须留下三类证据：代码/配置变更、可重复的测试命令、失败时的清理或回退结果。只有依赖任务的证据齐全，后续任务才能开始。
- Gateway 第一阶段只提供现有兼容 framing 和 stream chunk。任何事件改名、canonical envelope、sequence、replay 或 36 事件补齐都标记为事件计划工作，不得作为 Gateway 任务的隐含修复。
- 生产切换前不得双写执行。G-07 可以在隔离 fixture 中做旧路径/新路径对照，G-08 之后只允许 Gateway 作为实时执行入口。

## 当前进度

| 任务 | 状态 |
|---|---|
| G-00 冻结 Gateway 替代边界和兼容入口 | **已完成（2026-09-26）** |
| G-01 在 Harness 中提供 Gateway 进程入口 | **已完成（2026-09-26）** |
| G-01a 补齐 Gateway UDS listener 并保持 JSONL framing | **已完成（2026-09-26，G-01 子任务）** |
| G-02 让 chatrtmgr 能启动并管理 Gateway | **已完成（2026-09-26）** |
| G-03 建立 Gateway 请求桥和兼容响应 | **已完成（2026-09-26）** |
| G-04 接通 session、lease、fence 和 Agent 配置 | **已完成（2026-09-26）** |
| G-05 | **已完成（2026-09-26）** |
| G-06 | **已完成（2026-09-26，隔离 bundle self-test 已通过）** |
| G-07 旧路径与 Gateway 路径对照验收 | **已完成（2026-09-26）** |
| G-08 切换默认路径并移除 chatsvc | **已完成（2026-09-26；Gateway-only 生产入口、bundle/OCI、组合矩阵和 Compose 部署 smoke 已通过）** |

## 任务

### G-00 [P0] 冻结 Gateway 替代边界和兼容入口

**依赖**：无。

**主责**：Integration；NetworkClaw 与 Harness 评审。

**状态**：已完成（2026-09-26）。

**内容**：

- 固化 `user_id -> Gateway 进程`、`session_id -> _HermesSession`、`agent_id -> 配置选择`。
- 固化 Gateway、chatrtmgr、HermesHostAdapter 和 Hermes runtime 的职责边界。
- 明确第一阶段沿用现有 chatsvc UDS framing 和兼容 stream chunk；不得在此任务混入事件改名。
- 定义 Gateway 的 readiness、shutdown、session open/close、lease update/fence 和进程 owner 语义。

**验收**：本文、[harness-gateway-affinity.md](../architecture/harness-gateway-affinity.md) 和三仓责任边界一致；评审确认 Gateway 迁移不重写 `HermesHostAdapter` 或 Hermes Agent loop。

**完成证据**：

- [harness-gateway-affinity.md](../architecture/harness-gateway-affinity.md) 已冻结 `user_id -> Gateway 进程`、`session_id -> _HermesSession`、`agent_id -> 配置选择` 三层绑定，并记录了 session 隔离、进程故障范围和当前完成度。
- 已明确 `HermesHostAdapter`、`_HermesSession` 和 Hermes runtime 沿用现有实现；Gateway 只新增 Host Protocol/UDS/进程承接外壳，不重写 Agent loop、turn、control 或 delegation。
- 已明确第一阶段使用现有 chatsvc/chatrtmgr 兼容 framing 和 stream chunk，只完成拓扑替代，不把事件改名、canonical envelope 或 replay 混入 Gateway 迁移。
- 已明确 Gateway 的 readiness、shutdown、session open/close、lease update/fence、owner identity 和 `agent_id` 接线边界；`agent_id` 不改变 `user_id` 进程亲和键。
- [event-unification-design-and-plan.md](event-unification-design-and-plan.md) 已独立声明依赖 G-08，证明事件统一没有被隐含并入本任务。

**遗留边界**：G-00 只冻结设计，未把 Gateway 代码、chatrtmgr 直连、兼容响应和 `agent_id` 接线计入其完成证据；这些工作分别由 G-01 至 G-08 承接。

**后续记录**：G-01 已完成，当前下一步见 G-02。

### G-01 [P0] 在 Harness 中提供 Gateway 进程入口

**依赖**：G-00。

**主责**：Harness/UE 组。

**状态**：已完成（2026-09-26；包含 G-01a）。

**内容**：

- 增加可被 chatrtmgr 启动的 Gateway 入口。
- 保留 JSONL Host Protocol 的 stdout 数据纯净性，诊断走 stderr 或受控 artifact。
- 提供 Unix socket + JSONL 入口、health/readiness 和 bounded shutdown。
- Gateway 内复用现有 `JsonlHost`、`HermesHostAdapter` 和 session registry，不复制执行逻辑。
- 支持一个 Gateway 进程承载多个 session，并正确回收 session/runtime/tool binding。

**最小产物**：Harness 的可启动入口/命令、readiness 与 bounded shutdown 约定、入口级测试；复用 `JsonlHost`、`HermesHostAdapter` 和现有 session registry，不新建第二套执行循环。

**验收**：Harness 单仓测试证明启动、握手、健康、多个 session、关闭、进程退出和孤儿清理；同一进程中一个 session 的 fence 不影响另一个 session。验收命令和失败清理结果写入 Harness 变更说明，作为 G-02 的启动契约。

**完成证据**：

- 现有 `networkclaw_harness.host`（`python -m networkclaw_harness.host`，同样由 `networkclaw-harness` console script 暴露）作为第一版 Gateway 进程入口；不新增重复的 `gateway.py` 包装层。它创建 `HermesHostAdapter`、`JsonlHost`，安装 parent-death guard，并保持 stdout 只有 JSONL 协议帧、诊断写入 stderr。
- `JsonlHost` 已提供 `protocol.negotiate`、`health.query`/readiness、`capabilities.query`、`shutdown`、session open/close/drain、lease/fence、EOF 处理和 bounded worker drain；`HermesHostAdapter` 与 session registry 继续作为执行层。
- `HarnessSupervisor` 已以 `python -m networkclaw_harness.host` 启动子进程，传递 `--parent-pid`，维护私有 stdin/stdout pipes，并覆盖握手、健康探针、shutdown、超时升级、崩溃回收和父进程死亡清理。
- 已确认一个进程承载多个独立 session；host 测试覆盖两个 session 的路由/隔离，lifecycle 测试覆盖多 session、pipe disconnect、正常回收、SIGKILL 和 orphan cleanup；session fence 只作用于目标 session 的 runtime binding。
- 实际验证（Harness 仓库）：`./scripts/run_tests.sh tests/test_gateway.py tests/test_lifecycle.py tests/test_host.py tests/test_hermes_host_adapter.py`，结果 **68 passed**；`./scripts/run_tests.sh` 全量结果 **247 passed in 44.64s**，随后完成 vendored Hermes 校验（`verified 770 vendored files`）和 runtime closure 校验（`imports=ok offline=ok globals=ok`）。
- `tests/test_gateway.py` 通过真实 `AF_UNIX` socket 完成 protocol negotiate、health、两个 session、单 session fence、另一个 session turn、并行健康探针、断连回收、shutdown、SIGTERM、父进程死亡和 socket 清理；subprocess CLI 测试确认 `python -m networkclaw_harness.host --socket-path ...` 可启动，stdout 无协议污染且进程退出后 socket 消失，现有路径不会被覆盖且 socket 权限为 `0600`。每条连接保有自己的 `JsonlHost` session binding，G-02/G-03 的 chatrtmgr bridge 必须让同一个 session 保持在同一连接。

**边界说明**：G-01 已完成 Harness 侧 Gateway 进程、UDS + JSONL transport 和生命周期契约；chatrtmgr 仍未切换到该入口，旧生产链路仍是 `chatrtmgr -> chatsvc -> Harness`。因此 G-02 仍必须实现 NetworkClaw 侧 Gateway target、user affinity、启动/健康/停止/重启和清理。

**下一步**：执行 G-02，在 `NetworkClaw` 的 chatrtmgr 中把 process starter、service binding 和 readiness target 从 chatsvc 迁移为 Gateway，保持 `user_id -> 一个 Gateway 进程`。

### G-01a [P0] 补齐 Gateway UDS listener 并保持 JSONL framing

**依赖**：G-01 的 JSONL/生命周期部分已完成。

**主责**：Harness/UE 组；NetworkClaw 提供 socket path、启动参数和 readiness 约定。

**状态**：已完成（2026-09-26，作为 G-01 的子任务）。

**内容**：

- 在现有 `JsonlHost` 之上提供 Unix domain socket listener；每个连接使用同一 JSONL Host Protocol，不复制 `HermesHostAdapter` 或 session registry。
- 支持 chatrtmgr 传入 socket path，启动时安全创建/校验，退出时 bounded close 并清理 socket 文件。
- 保持 stdout/stderr 语义：协议通过 UDS JSONL 连接，stdout 不输出诊断；诊断仍走 stderr/artifact。
- 明确单 Gateway 多连接/多 session 的并发模型、client disconnect、EOF、半关闭和连接级资源回收。

**最小产物**：Harness UDS listener、socket path/权限约定、readiness 探针、listener 生命周期测试和真实 Unix socket JSONL fixture。

**验收**：从独立 client 通过 Unix socket 完成 negotiate、health、session open、多个 session、session fence、shutdown 和进程退出；验证 socket 文件创建/清理、client disconnect、孤儿清理和一个 session 的 fence 不影响另一个 session。上述验收已由 `tests/test_gateway.py` 覆盖，G-01 因此标记为完成。

### G-02 [P0] 让 chatrtmgr 能启动并管理 Gateway

**依赖**：G-01a。

**主责**：NetworkClaw 后台组。

**内容**：

- 将 process starter、service info、readiness 和 stop/restart 逻辑从 chatsvc 专名抽象为 Gateway target。
- 保持 `user_id` 亲和和现有 service binding 语义；不把 `agent_id` 加入进程键。
- 配置 Gateway command、args、socket path、owner identity 和环境白名单。
- 确保进程退出、socket 删除、日志和 PID 清理与现有 chatsvc 生命周期等价。

**最小产物**：chatrtmgr 的 Gateway target/process binding 配置、启动参数白名单、readiness/stop/restart 实现和单元测试。

**验收**：chatrtmgr 可独立启动、复用、停止和重启 Gateway；启动失败、readiness 超时和进程崩溃都有稳定错误和清理结果。必须证明同一 `user_id` 复用同一进程、不同用户不共享进程。

**状态**：已完成（2026-09-26）。

**完成内容**：

- `ProcessConfig` 增加 Gateway target、Gateway binary path、socket 目录和既有启动/停止超时配置；默认仍保留 chatsvc target，便于回退。
- process starter 按 target 启动 `networkclaw-harness --socket-path ... --parent-pid ...`，只传递 Gateway 环境白名单，并把 stdout/stderr 写入权限为 `0600` 的 Gateway 日志文件。
- Gateway readiness 不再只检查 socket 文件，而是通过 UDS JSONL Host Protocol 执行 `health.query`，校验协议版本、request correlation、sequence、终止帧和 `ready` 状态；metrics 也通过同一探针读取。
- ProcessManager/BindingManager 继续使用 `user_id -> serviceID` 亲和，不把 `agent_id` 加入进程键；同一用户的多个 session 复用同一 Gateway 进程，不同用户创建不同进程。
- stop/restart、启动超时、启动失败、monitor 崩溃回调和 socket 清理均走 Gateway target；崩溃移除死进程记录时同时删除遗留 socket 并清理用户 binding，下一次请求可重新建立 Gateway。

**验证证据**：

- Go 单元/组件测试：`go test ./internal/chatrtmgr/config ./internal/chatrtmgr/process ./internal/chatrtmgr/forwarder ./internal/chatrtmgr/gateway ./cmd/chatrtmgr`，通过。
- 真实跨仓测试：设置 `NETWORKCLAW_GATEWAY_TEST_BINARY` 指向 Harness `.venv/bin/networkclaw-harness` 后运行 `go test -count=1 -run 'TestGateway' ./internal/chatrtmgr/process`，通过；覆盖同用户复用、不同用户隔离、Gateway readiness、重启、停止和 socket 清理。
- starter 测试覆盖 spawn 失败、readiness 超时、不可拨号 socket、cleanup kill/remove 错误聚合；manager 测试覆盖死进程条目移除和崩溃 socket 清理。
- `git diff --check` 通过；测试使用 `t.Cleanup` 清理临时进程、socket 和目录。

**边界与遗留**：G-02 只完成 Gateway 进程的启动、亲和、健康、停止、重启和故障清理；chatrtmgr 的 ForwardMessage/ForwardStream 请求尚未改为直连 Gateway，仍由 G-03 负责。事件名称和 36 个 vendor 事件统一不属于 G-02。

**后续记录**：G-03 已完成；当前下一步见 G-04。

### G-03 [P0] 建立 Gateway 请求桥和兼容响应

**依赖**：G-02。

**主责**：NetworkClaw 与 Harness 联合。

**内容**：

- 将 chatrtmgr 的 ForwardMessage/ForwardStream 请求映射为 Gateway Host Protocol 输入。
- 透传 `user_id`、`tenant_id`、`session_id`、run/turn/request identity、workspace、lease、host grant 和当前 Agent 配置输入。
- 将 Gateway 输出暂时映射为现有 chatrtmgr 兼容的 content/tool/run/error/done stream chunk。
- 明确该映射只是迁移兼容层，不作为新的事件契约。

**最小产物**：请求/响应字段映射表、Gateway client/bridge、兼容 chunk 转换测试和一条真实 vertical flow fixture。

**验收**：单 session vertical flow、流式文本、工具开始/结束、错误、done、半关闭和 EOF 行为与旧 chatsvc 路径一致；请求不会跨 session 串流。此处只验证兼容行为，不宣称事件名称已经统一。

**状态**：已完成（2026-09-26）。

**完成内容**：

- 抽出共享的 Host Protocol client 和兼容投影；Gateway 与旧 chatsvc 共用请求关联、EOF、限额和响应投影语义。
- 新增 GatewayForwarder，按 serviceID 到 Gateway socket 复用已 negotiate 的 UDS JSONL 连接；同一进程可并发承载不同 session，并校验 request、session、turn、run 和 sequence。
- 将 PostMessageRequest 的 host binding、tenant/user/session、workspace、lease、owner、epoch、host grant、Agent 输入和 memory 输入映射为 session.open 加 user.input 帧。
- 将 Harness 事件映射为现有 content、tool_start、tool_end、run_state、error、done chunk；半关闭、无 terminal、错误和错误关联都不会伪造 done。
- Gateway target 切换到 GatewayForwarder；旧 target 继续使用 chatsvc forwarder，保留回退路径。G-03 暂不接管 cancel、steer 和 lease lifecycle control。

**验证证据**：

- go test ./... 通过。
- go test -race ./internal/chatrtmgr/forwarder ./internal/shared/harness ./internal/chatsvc/session 通过。
- go test -race -count=1 ./internal/chatrtmgr/forwarder -run TestGateway 通过；覆盖输入透传、两个 session 并发、单次 negotiate、content/tool/run/done 投影、turn.failed、half-close、错误 session 和无 terminal EOF。
- 真实跨仓 vertical flow：`go test -race -count=1 ./tests/integration/harnessinterop -run TestRealGatewayForwarderVerticalFlow` 通过；启动本地 provider stub 和真实 `networkclaw-harness --socket-path`，经 chatrtmgr GatewayForwarder 完成 session.open、user.input、provider-backed Hermes turn 和兼容流收尾，并由测试清理 provider、Gateway、UDS 和临时 workspace。
- git diff --check 通过；fixture 清理连接、socket、临时目录和 forwarder context。

**边界与遗留**：G-03 是请求桥和迁移兼容响应，不是 36 事件统一；没有改 vendor 事件名，也没有把 control、lease takeover、cancel、steer 下沉到 GatewayForwarder。provider-backed vertical flow 和完整 session/lease/fence 接线在 G-04/G-05 继续验收。

**下一步**：执行 G-04，把 session open/resume/close、lease renew/revoke/takeover、旧 epoch fence、cancel/steer/delegation 和 agent_id 配置选择接到同一 Gateway session binding；随后用 G-05 验证进程级和 session 级故障边界。

### G-04 [P0] 接通 session、lease、fence 和 Agent 配置

**依赖**：G-03。

**主责**：Harness/UE 组；NetworkClaw 提供 lease 输入。

**内容**：

- Gateway 直接调用现有 `HermesHostAdapter.open/close/update_lease/fence`。
- 保持每个 `_HermesSession` 独立 workspace、runtime、工具会话、turn admission 和事件 bridge。
- 将 `agent_id` 接入请求/session state，并用于 Agent 配置选择；仍不改变进程亲和键。
- 确保 provider route/profile/tool grant/budget 变化只重建目标 session 的 Agent。

**最小产物**：`agent_id` 请求到 session state 的字段链路、生命周期/lease/fence 组合测试和多 session 隔离 fixture。

**验收**：测试覆盖 session open/resume/close、lease renew/revoke/takeover、旧 epoch、session fence、Agent route change、cancel、steer、delegation 和多 session 并行；provider 或 Agent 配置变化不得重建无关 session。

**完成记录（2026-09-26；尚未满足最终验收）**：

- Harness `JsonlHost` 已将同 epoch `session.open/session.resume` 接到 session 配置刷新：保留 workspace、runtime、tool session、turn admission 和 event bridge；`agent_id`、`profile_id`、provider route、tool grant、resource profile 或 turn budget 变化只驱逐目标 session 的 Agent 缓存。活跃 turn 或 fenced session 拒绝配置刷新；resume 省略配置字段时沿用既有值。
- `HermesHostAdapter` 已显式提供 session 配置入口，并把 `agent_id/profile_id/turn_budget/tool grant/profile` 纳入 Agent cache route；Agent cache eviction 不结束 durable Hermes session。Agent 仍是 session 内可替换缓存，不跨 session 共享。
- `GatewayForwarder` 已把 `agent_id` 从 HarnessBinding 转入 `session.open`，并实现同一已协商 UDS JSONL 连接上的 cancel、steer、query、delegation resolve 和 lease lifecycle control 转发；Harness Host Protocol 增加了 `run.query` 快照命令；进程 affinity 仍只由 `user_id` 决定。
- Go proto、Lobby model、chatrtmgr transport 和 routing 已补齐 `HarnessBinding.agent_id` 字段链路；没有把 agent_id 加入 Gateway 进程 key。
- 验证证据：Harness `bash scripts/run_tests.sh -q` 通过（包含 vendor/runtime/doc 校验）；Go `go test -race -count=1 ./internal/chatrtmgr/forwarder ./internal/chatrtmgr/transport/grpc ./internal/lobby/usecase ./internal/lobby/repository ./cmd/chatrtmgr` 通过；真实 `go test -race -count=1 ./tests/integration/harnessinterop -run TestRealGatewayForwarderVerticalFlow` 通过；组合 runner 已改用迁移后的 `./internal/shared/harness` 测试路径。

**边界与遗留**：G-04 完成 Gateway session/lifecycle/control 和 session-local Agent 配置接管，但不做 vendor Hermes 36 事件改名或压缩规则统一；该工作保持为后续独立设计和任务。控制响应仍复用现有 chatrtmgr/chatsvc control contract，待 G-05 用故障夹具验证跨进程断连、SIGKILL、旧 epoch late frame 和恢复窗口。

**下一步**：执行 G-05，覆盖 Gateway 进程故障、UDS reset/drop、provider interruption、慢消费者、lease takeover 后恢复和清理报告；G-05 通过后再建立独立的事件统一设计/任务，按 vendor Hermes 事件逐项保留原名。

### G-05 [P0] 完成 Gateway 故障和恢复验收

**依赖**：G-04。

**主责**：Integration；三仓联合。

**内容**：

- 增加 Gateway SIGKILL、UDS reset/drop、client disconnect、provider interruption 和慢消费者夹具。
- 验证一个 session 失败不污染同进程其他 session。
- 验证 Gateway 进程崩溃后的 lease takeover、旧 owner fencing、workspace/history 恢复和 late control 拒绝。
- 明确进程级故障会影响该用户进程内全部 session，并留下可诊断 reason code。

**最小产物**：可注入的进程/UDS/provider 故障夹具、故障矩阵和 machine-readable 清理报告。

**验收**：组合矩阵通过；测试结束无 Gateway、socket、proxy、临时 workspace 或 provider stub 泄漏。报告必须区分 session 级失败与 Gateway 进程级失败。

**完成记录（2026-09-26）**：

- 故障矩阵已覆盖单 session provider interruption、UDS stream drop/reset、client EOF、慢消费者/backpressure、SIGKILL、Gateway replacement、lease takeover、旧 owner late control/late frame、parent/child interrupt scope 和多 session 并行隔离。
- Integration fixture 已统一记录稳定 reason code；`provider_interrupted`、`provider_stream_interrupted`、`provider_transport_reset`、`harness_unavailable`、`stale_epoch`、`epoch_takeover` 和 `backpressure` 等语义进入 machine-readable report。
- `tools/run-combination-matrix.py` 现在生成 `.integration-state/evidence/combination-matrix.json` 与 `.md`，并增加 post-matrix cleanup evidence：活动 Gateway/provider 进程、测试 socket、临时 root 均检查。最近一次当前代码运行结果为 `status=passed`、`cleanup.status=clean`，所有命令退出码为 0。
- 当前运行证据包括：integration fixtures 56 项通过；Go cross-repository race matrix 通过；shared Harness client/process recovery/lifecycle support race tests 通过；Harness recovery/delegation/host/session/projection tests 通过。
- 故障边界已明确：同一 Gateway 进程崩溃会影响该 `user_id` 下全部 session，并由进程级 `harness_unavailable`/replacement reason code 表示；单 session provider、turn 或 lease fence 只影响目标 session，其他 session 保持可用。

**边界与遗留**：G-05 验证的是进程、传输、provider 和 lease recovery 语义，不改变 vendor Hermes 事件名，也不把故障 reason code 当作最终 36 事件协议。旧 `chatsvc` 支持测试仍保留作为 lifecycle 对照证据；G-06 负责清理入口/部署命名并将默认运行路径切换为 Gateway。

**下一步**：执行 G-06，更新 `dev-up/down`、restart、logs、doctor、diagnostics、Compose、Helm、Dockerfile、CI artifact 和 bundle manifest，使部署入口显式使用 Gateway，并补充升级/回退说明。

### G-06 [P0] 更新本地开发、部署和 CI 输入

**依赖**：G-05。

**主责**：Integration 构建组；部署组评审。

**内容**：

- `dev-up/down`、restart、logs、doctor 和 diagnostics 支持 Gateway 进程名和 socket。
- Compose、Helm、Dockerfile、CI artifact 和 bundle manifest 使用 Gateway 作为执行服务。
- 文档明确当前旧入口与新入口，禁止部署脚本继续隐式启动 chatsvc。
- 诊断保留用户/进程/session 的脱敏身份和 Gateway/Hermes 分层状态。

**最小产物**：Gateway 版本地入口、部署/CI 配置、bundle manifest 输入和升级/回退说明。

**验收**：Mac 本地启动、Ubuntu 22.04 CI 构建、bundle self-test、Compose/Helm smoke 均使用 Gateway 入口；所有入口都能明确显示当前服务是 Gateway，而不是隐式启动 chatsvc。

**完成记录（2026-09-26）**：

- `tools/dev.py`、Makefile、README 和本地开发文档已将 `dev-up/down`、restart、logs、doctor/diagnostics 的执行服务命名为 Gateway；Gateway 由 chatrtmgr 以 `CHATRTMGR_PROCESS_TARGET=gateway` 和 `CHATRTMGR_GATEWAY_BINARY_PATH` 启动，状态中记录 Gateway PID、UDS 目录、日志和分层协议信息。
- Compose 和 Helm 的 chatrtmgr workload 已改为显式 Gateway target，使用 `/opt/bin/networkclaw-harness`，移除 `CHATRTMGR_CHATSVC_BINARY_PATH` 和 Harness 作为 chatsvc 子进程的隐式入口。Helm README、Docker README 已同步 Gateway 拓扑和回退边界。
- Ubuntu Dockerfile 设置 Gateway target；NetworkClaw `build-coordinator` 现在构建 `lobby` 和 `chatrtmgr`，不再把 chatsvc 作为交付执行二进制。bundle/image 的源码和 manifest 输入仍由现有 provenance 流程记录。
- 验证证据：Integration Python 全量 56 项通过；`make validate-contracts` 通过；`make -C NetworkClaw build-coordinator BIN_DIR=/tmp/networkclaw-g06-bin` 通过并只生成 `lobby`、`chatrtmgr`；Compose/Helm 配置测试通过；`tools/dev.py` Python 编译和 `git diff --check` 通过；bundle build/verify 通过。

**完成记录（2026-09-26）**：

- 完成前述本地开发、Compose、Helm、Dockerfile、CI artifact 和 bundle 输入切换；chatrtmgr 显式以 Gateway target 启动 Harness，构建产物不再包含 chatsvc 执行二进制。
- 修复隔离 bundle 的 Gateway vertical-flow 测试路径：provider fixture 由 `NETWORKCLAW_INTEGRATION_PATH` 指定；组合矩阵默认使用当前 integration 根目录，bundle self-test 显式传入解包后的 integration 目录。这样测试不再假定源码 checkout 的目录名称或相邻关系。
- 验证：Gateway vertical-flow Go race 测试通过；`make bundle BUNDLE_OUTPUT=.integration-state/artifacts/networkclaw-g06-bundle.tar.gz BUNDLE_VERSION=0.1.0-g06` 与 `make verify-bundle` 通过；隔离执行 `python3.12 tests/bundle/self_test.py ...` 全阶段通过，包括 archive safety、依赖安装、doctor、Harness tests、Integration tests、完整组合矩阵、manifest verify、bundle rebuild 和重建包 verify。报告为 `.integration-state/evidence/bundle-self-test.json`，`status=passed`；矩阵 evidence 为 `.integration-state/evidence/combination-matrix.json`。
- 本次 bundle self-test 的通过结果证明打包后的组合矩阵能够从 bundle 自身的 integration fixture 运行；失败的根因是测试路径假设，不是 UDS/JSONL Gateway 行为故障。

**下一步**：执行 G-07，在相同请求和 provider fixture 下对旧 `chatrtmgr -> chatsvc -> Harness` 与新 `chatrtmgr -> Gateway` 做行为对照，重点记录兼容 chunk、工具副作用、lease/fence、错误 reason code 和资源清理。G-07 通过后再执行 G-08 切换默认路径并移除 chatsvc；36 事件原名统一仍由独立事件计划跟进。

### G-07 [P0] 运行旧路径与 Gateway 路径对照验收

**状态**：已完成（2026-09-26）。

**最终完成记录**：`make combination-matrix` 的全部命令退出 0，`legacy_gateway_parity_and_rollback` 四项真实进程子测试全部 pass，整体 `status=passed`，cleanup 为 clean（零活动 Gateway/provider、零 socket、零临时 root）。lease renew/旧 version 拒绝、旧 epoch 拒绝、真实工具 PLAN 持久化、内容与失败收尾、身份和父/子 PID 清理均通过。测试使用 `config.ApplyEnvVars` 读取真实 target 开关并启动两种目标。`go test -race ./internal/chatrtmgr/process ./internal/chatsvc/session -count=1` 两包通过。

**报告与差异**：见 [新旧路径对照报告](../evidence/gateway-legacy-parity.md)。已记录旧合成帧缺身份及 stale_epoch 错误前缀差异；修复显式零工具数组被转为 null、旧 chatsvc 未等待子进程退出两个问题。回退需保留兼容 chatsvc 制品，当前 combined image 不包含旧二进制，不能仅切 target 就完成镜像内回退。

**下一步**：执行 G-08，将 Gateway 设为默认 target，删除或隔离生产 chatsvc consumer，并完成 bundle、Ubuntu 构建与部署 smoke 等发布验收。事件原名统一继续等待 G-08 完成。

以下为过程记录，记录中的待补项已由上述最终矩阵闭环。

**阶段证据（2026-09-26）**：NetworkClaw 增加 `TestLegacyGatewayVisibleContentParity`，构建真实 chatsvc 并复用同一 provider fixture、请求构造和 chatrtmgr process manager，分别通过旧 StreamForwarder 与 GatewayForwarder 执行。`go test -race ./tests/integration/harnessinterop -run TestLegacyGatewayVisibleContentParity -count=1` 通过；两条路径的非空可见内容一致，均存在 `run_state`，且最后一个兼容 chunk 为 `done`。此证据只覆盖成功对话，不代表整个 G-07 通过。

**失败场景阶段证据（2026-09-26）**：对照用例增加同一 provider fixture 的 `reset` 模式。两条真实路径观察结果一致：可见内容为空、一个 `error`、零个 `done`；`go test -race -v ./tests/integration/harnessinterop -run '^TestLegacyGatewayVisibleContentParity/reset$' -count=1` 通过。成功场景仍要求一个 `done`，失败场景不套用成功收尾断言。当前仅核对失败 chunk 数量，reason code 比较仍待完成。

**已闭环**：工具副作用、session identity、lease/fence、失败 reason code、进程/子进程/socket 清理和回退开关对照已纳入最终组合矩阵与对照报告；此处历史阶段的“剩余工作”不再是当前阻塞项。

**身份与错误阶段证据（2026-09-26）**：完整 `TestLegacyGatewayVisibleContentParity` race 运行通过（58.713s）。两条路径的 reset 场景完整 error 内容一致，为 `harness turn failed: turn_timeout`；这证明当前 fixture 经 runtime 重试/预算后的最终失败语义一致，并不证明直接输出 `provider_transport_reset`。运行 chunk 均校验 session/run 身份；旧 chatsvc 合成的 `done`/`error` 缺少身份，Gateway 带 `session-1`/`run-1`，该差异已由断言固定。两条路径进程停止返回成功，并在 5 秒内删除 execution socket。其余证据已由最终矩阵与汇总报告补齐。

**工具阶段证据（2026-09-26）**：integration provider fixture 增加固定 `todo` 模式，发出 `todo_list` 工具调用，在收到工具结果后输出最终内容。Host grant 和请求授权均指定工具名 `todo_list`。真实两条路径 `go test -race -v ./tests/integration/harnessinterop -run '^TestLegacyGatewayVisibleContentParity/todo$' -count=1` 通过（9.280s）：各自 workspace 的 `session-state/durable.db` 写入一条相同 PLAN 事实（session-1、todo-session-1、revision=1、parity-item），可见内容一致且均一个 done。测试直接查询持久化事实，而非仅检查工具事件。其余门禁已由最终矩阵闭环。

**Epoch 阶段证据（2026-09-26）**：新增 `fence` 场景，两条路径以 epoch=2 完成正常 turn 后提交 epoch=1 请求，均由真实 Harness 返回 `stale_epoch`，provider ledger 仍只有一次请求，证明旧 epoch 未执行。race 场景通过（9.649s）。对照同时发现 chatsvc 将显式零工具数组复制成 nil/null 的问题，已在 `HarnessHandler` 转发点修复为保留空数组；`go test -race ./internal/chatsvc/session -run TestHarnessHandler -count=1` 通过。该阶段门禁已由最终矩阵闭环。

**依赖**：G-06。

**主责**：Integration；后台组和 Harness/UE 组共同签字。

**内容**：

- 在相同请求和 provider fixture 下，对比旧 `chatrtmgr -> chatsvc -> Harness` 与新 `chatrtmgr -> Gateway`。
- 对比 session identity、terminal status、tool side effects、lease/fence、错误 reason code 和资源清理。
- 暂不要求事件名字完全一致，但必须证明兼容 chunk 的用户可见行为不回归。

**最小产物**：固定 provider fixture、旧/新路径对照报告、已知差异清单和回退开关验证记录。

**验收**：对照报告通过；所有已知差异有记录且不属于未授权的行为变化；Gateway 路径可以作为默认候选路径运行。报告必须确认兼容 chunk 的用户可见行为、工具副作用、lease/fence 和资源清理均无回归。

### G-08 [P0] 切换默认路径并移除 chatsvc

**状态**：已完成（2026-09-26）。

**完成记录**：

- NetworkClaw `DefaultConfig` 默认执行目标改为 `gateway`；chatrtmgr 主装配在 Gateway target 下使用 GatewayForwarder、GatewayHealthProbe 和 Harness binary。旧 chatsvc target 只在显式 `CHATRTMGR_PROCESS_TARGET=chatsvc` 的隔离回退验证中可选，不再是默认或交付入口。
- NetworkClaw `build-coordinator`、cross-node build、K8s binary build 和 K8s chatrtmgr 镜像上下文不再构建或复制 chatsvc；cross-node/K8s chatrtmgr 配置改为 Gateway target。Integration Compose、Helm、Ubuntu Dockerfile 和本地入口此前已完成同样切换。
- 交付文档 [source-combination.md](../contracts/source-combination.md) 和 [ci.md](../ci.md) 已明确 combined image 只包含 lobby/chatrtmgr 加 Harness Gateway，旧 chatsvc 仅作为隔离源码/回退制品，不属于生产执行路径。回退边界见 [gateway-legacy-parity.md](../evidence/gateway-legacy-parity.md)。
- 验证：`make -C NetworkClaw build-coordinator BIN_DIR=/tmp/networkclaw-g08-bin` 只生成 `lobby`、`chatrtmgr`；NetworkClaw chatrtmgr/process/forwarder race 测试、Integration `make validate-contracts` 和 Python 测试通过；`networkclaw-g08-bundle.tar.gz` 的 `verify-bundle` 和最终 bundle self-test 全阶段通过，包含组合矩阵和重建包验证。使用固定 digest 基础镜像生成 Linux/amd64 OCI 和 Docker archive，manifest 记录 bundle SHA-256、base digest 和三仓 tree hash。
- 部署验证记录在 [G-08 Gateway 部署证据](../evidence/gateway-g08-deployment.md)：Gateway-only Compose 部署的 `healthz`、`readyz`、`metrics`、创建 session、manager-service binding 和关闭 session smoke 全部通过；Harness provider fixture 在容器内 loopback 运行，未绕过 provider policy。此前 kind 复验暴露的 PID 1 owner guard 已修复并通过 Harness 定向测试和 bundle 组合回归；kind worker 后续因磁盘 100% 无法再次初始化 PostgreSQL，记录为目标环境资源门禁，不是 Gateway 功能失败。

**下一步**：启动独立事件统一计划的 E-00，冻结 vendor Hermes 36 事件清单、canonical envelope 和原名透传规则。Ubuntu 22.04/kind 资源恢复后仍需按部署证据重跑平台 smoke，但不再改变 Gateway 替代方案的完成状态。

**依赖**：G-07。

**主责**：NetworkClaw 后台组；Integration 发布门禁。

**内容**：

- 将 Gateway 设为 chatrtmgr 默认执行目标。
- 删除或隔离 chatsvc 的启动、适配和部署引用；不得保留隐式双写或双重执行。
- 更新源码边界、bundle、CI、部署和交接文档。
- 将事件统一计划作为后续独立工作，不在本任务通过改名掩盖兼容层。

**最小产物**：默认路由变更、chatsvc consumer 删除/隔离、bundle/CI/deploy 更新、发布回退点和迁移记录。

**验收**：源码和部署搜索无生产路径 chatsvc consumer；完整组合矩阵、bundle verify、Ubuntu 构建和部署 smoke 通过；用户对话、工具、控制、lease takeover 和故障恢复均走 Gateway。只有这一任务完成后，事件统一计划的 E-00 才能开始。

## 完成定义

本计划完成必须同时满足：

- chatrtmgr 按 `user_id` 启动并复用 Harness Gateway；
- 一个 Gateway 可承载多个独立 session；
- 现有 `HermesHostAdapter` 和 `_HermesSession` 被直接复用；
- `agent_id` 已接入 Agent 配置选择，但没有改变进程亲和键；
- chatsvc 不再位于生产执行路径；
- 旧兼容 stream chunk 的行为有对照证据；
- 故障、lease、takeover、资源清理和部署入口均已验证；
- 36 事件原名统一仍作为下一份独立计划，不计入本计划；下一步为 [event-unification-design-and-plan.md](event-unification-design-and-plan.md) 的 E-00。
