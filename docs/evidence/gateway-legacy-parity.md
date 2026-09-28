# G-07 新旧执行路径对照

## 可重复验收

运行 `make combination-matrix`。源码位置由 workspace 配置解析；bundle 内仍使用自身 integration fixture。

权威测试为 NetworkClaw 的 `TestLegacyGatewayVisibleContentParity`。测试构建真实 chatsvc，分别由 chatrtmgr ProcessManager 启动 chatsvc 和 Harness Gateway，使用真实 StreamForwarder/GatewayForwarder、同一请求构造及 integration provider fixture。各路径使用独立 workspace，不双写同一对话。

机器报告为 `.integration-state/evidence/combination-matrix.json`，检查 `legacy_gateway_parity_and_rollback` 的四项子测试均为 pass，整体 status 为 passed，cleanup 为 clean。测试中的输出比较与清理断言失败都会使矩阵失败。

## 对照范围

| 场景 | 断言 |
| --- | --- |
| stream | 非空可见内容一致、零 error、一个 done、run_state 存在 |
| reset | 完整错误内容一致、一个 error、零 done；runtime 预算后的最终原因是 turn_timeout |
| todo | 真正执行 todo_list，两个 durable.db 中仅有一条相同 PLAN 事实，revision=1，未重复提交 |
| fence | epoch=2 正常执行；lease version=3 renew 成功；旧 version=2 renew 被拒绝；epoch=1 返回 stale_epoch；provider 总调用数仍为 1 |
| identity | 运行 chunk 的 session/run 身份匹配；Gateway 的 done/error 也匹配 |
| cleanup | Stop 成功；执行 PID、真实 chatsvc Harness 子 PID 和 socket 在 5 秒内消失；provider 和 workspace 由测试 cleanup 释放 |

这些结果覆盖固定 fixture 的迁移兼容性；reset 的终态不能解释为直接验证 provider_transport_reset 的事件投影。

## 已知差异与修复

| 项目 | 旧路径 | Gateway | 判定 |
| --- | --- | --- | --- |
| done/error 身份 | chatsvc 合成帧没有 session_id/run_id | 保留 session_id/run_id | 增补身份，不改变内容或终态；测试分别断言 |
| stale_epoch 拒绝位置 | chatsvc 报错有 open harness session 前缀 | ForwardStream 建流时返回 Harness 错误 | 均拒绝且不调用 provider；允许边界文本差异 |
| 显式零工具 | 原先复制为空 nil，输出 null | 保留空数组 | 修复旧 HarnessHandler 保留 []，防止 allowed_tools_invalid |
| 进程回收 | 原先未调用 cmd.Wait | 有 waiter | ProcessStarter 统一 waiter，避免旧路径停止后留下 zombie |

## 回退选择记录

测试通过真实 config.ApplyEnvVars 读取 `CHATRTMGR_PROCESS_TARGET=chatsvc` 或 `gateway`，并将解析后的 target/binary 交给真实进程管理器。每个 fixture 都执行两种选择，证明旧目标仍可构建并启动，切回旧目标不会进入另一套 Agent loop：chatsvc 显式启用 CHATSVC_HARNESS_ENABLED，执行仍由 Hermes 承担。

回退要求保留与当前 Host Protocol 匹配的 chatsvc 二进制，并设置 CHATSVC_HARNESS_COMMAND。当前交付 build-coordinator 已不含 chatsvc，因此运行镜像内不能仅改 target 就获得回退二进制；应使用保留的旧制品或显式构建的隔离验证制品。禁止同一 session 两条路径同时执行。

## 下一步

G-08 切换默认路径并删除或隔离生产 chatsvc consumer，重新验证构建、bundle、Ubuntu 部署 smoke 和完整组合矩阵。36 个 Hermes 事件原名统一继续等待 G-08 完成。
