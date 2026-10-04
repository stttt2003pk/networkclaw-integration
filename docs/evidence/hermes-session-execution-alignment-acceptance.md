# Hermes 普通会话执行对齐最终验收

日期：2026-10-05。结论：[alignment plan](../plan/hermes-session-execution-alignment-plan.md) T01～T11 完成（11/11）。功能、真实组合、用户流程和冻结交付验证通过。公开发布安全扫描退出 1，`publishable=false`，不宣称 clean release。

## 任务与职责核对

业务修改留在 Go/Harness，Integration 仅持有契约、编排、测试和生成制品。durable Session 与可回收 AIAgent 分开；每个准入 turn 一次 native `run_conversation()`。Hermes SessionDB 是执行历史权威，页面记录不用于重建 transcript，无 chatsvc 替换范围。

| 任务 | 最终产物与验收 |
| --- | --- |
| T01 | `session-execution.v1` 三侧契约/schema/proto、canonical hash、父子/显式空授权正负样例；缺失、篡改、越权及私有模型配置泄漏拒绝 |
| T02 | Go migration 031、独立 Session 策略、等价旧快照转换；隔离 PG 完整迁移、存取、幂等转换、损坏和不安全回退拒绝 |
| T03 | 无 Profile resolver、可选预设权限收窄、冻结 Tool/Skill release；实际零 Profile `{}` 创建 201，发布/依赖/越权负例 |
| T04 | 独立完整 Host Grant、run/turn admission 与 lease/epoch；双 Lobby HTTP/WS、归属拒绝、边界续租、过期/旧版本/旧 epoch 不能续活 |
| T05 | chatrtmgr 独立策略转发、Broker、run pin、受限 child grant；30 秒实际收敛、可控时钟 5 分钟过期、固定配置丢失拒绝、控制/回放不启动新 turn |
| T06 | Harness validator/native adapter/cache；相同身份复用、模型/连接/凭证变化重建保留 SessionDB/workspace、空授权、重建失败拒绝、epoch fencing、单次 native turn |
| T07 | deployed release、FrozenSkillView、patch 0005/0006；实际冻结正文/version/hash/support files、workspace Tool、disabled/越权/篡改拒绝、并发和重建隔离 |
| T08 | durable child authority、native delegation；真实无 Profile child，固定模型/effort/max output 及受限能力继承；7 native 场景涵盖成功、策略/容量拒绝、分配超时、预算越界、child provider 失败和 active child cancel 清理 |
| T09 | native binding/SessionDB、Go migration 032；实际旋转压缩、模型/凭证重建、全新 OS 进程更高 epoch 恢复、迟到/generation/conflict 拒绝；manager 重启旧 run 不重执行，新 turn 准入前恢复路由和 native tip |
| T10 | Web2 普通 `{}` 创建与可选预设、可恢复草稿；339 passed/1 skipped、typecheck/build；实际 Chrome 登录、无 Profile 首轮、同 Session 模型切换、零旧 Agent Catalog 请求 |
| T11 | 双 Lobby/manager public 流程、实际 GPT、完整组合、独立 dev-up/down、冻结 bundle 解包/重建、Ubuntu 编译/native 验证、最终镜像部署与凭证扫描 |

具体源码路径、错误语义和协议兼容策略见主计划、[session execution 契约](../contracts/session-execution-v1.md)及三仓模块计划。

## 命令与证据

运行报告存于 `.integration-state/evidence/`，以下文件只包含脱敏断言或受控诊断。机器可读[验收摘要](hermes-session-execution-alignment-acceptance.json)记录最终报告哈希、命令退出码及制品身份。

| 入口/命令 | 结果 | 证据 |
| --- | --- | --- |
| `make session-execution-acceptance SESSION_EXECUTION_ACCEPTANCE_ARGS='--browser --real-gpt'`（隔离夹具与已有 GPT 配置） | 退出 0；同次双 Lobby/manager、native Skill/Tool/child、模型/凭证切换、manager 重启、真实 GPT 与 Chrome | `session-public-final.json` |
| `make session-dev-lifecycle-acceptance` | 退出 0；独立 dev-up/down、普通 native turn、Vite ready、DB/进程清理 | `session-dev-lifecycle.json` |
| `make test` | 退出 0；Integration 141 tests/OK，Go web2-server race | `session-tools-final-v3.log` |
| `make combination-matrix` | 退出 0；10 命令、15 场景，89 个 Go 测试记录；cleanup=clean | `session-combination-final.json` / `.md` |
| Go `make test-session-execution-storage TEST_RUN='.'`、coordinator `make test-context` | 退出 0；真实隔离 PG 完整迁移与 Go race；开发库未迁移 | 主计划第 9 节及组合 child-authority evidence |
| Go `go test -race -count=1 ./internal/lobby/...` | 退出 0；包含准入前 runtime route 恢复和拒绝签 run 回归 | `/tmp/session-route-race-final.log`（原始日志已复制为 `session-lobby-race-final.log`） |
| Harness `scripts/run_tests.sh`；`scripts/run_tests.sh tests/test_native_execution_delegation.py -q` | 退出 0；CPython 3.12、全量 supported tests、7 native delegation 场景、1104 vendor 文件及 imports/offline/globals closure | 最终 bundle self-test `source_tests` 与主计划第 9 节 |
| Ubuntu 22.04/amd64 解包源码的 native admission/Skill/delegation/history tests | 退出 0；30 场景，CPython 3.12.15；Harness tree 与最终 bundle 相同 | `session-ubuntu-native-v5.log` |
| 空 Profile export 的 `make bundle`、最终 `make verify-bundle` | 退出 0；archive/content 凭证扫描、manifest/源码路径验证、Tool/Skill release 保留 | `session-bundle-build-final.log` / `session-verify-bundle-final.log` |
| `BUNDLE_OUTPUT=.integration-state/artifacts/session-execution-bundle-final.tar.gz make bundle-self-test` | 退出 0；14 步全部通过，临时解包目录已删除 | `session-bundle-self-final.json` |
| 最终已验证 bundle/Ubuntu prepared context 的 `make image` | 退出 0；linux/amd64、冻结身份匹配、禁止 lazy installs | `session-ubuntu-image-context-final.log` / `session-image-build-final.log`、build manifest |
| `NETWORKCLAW_IMAGE_TAG=networkclaw:session-execution-final BUNDLE_OUTPUT=.integration-state/artifacts/session-execution-bundle-final.tar.gz make session-image-acceptance` | 退出 0；nonroot、TLS Broker、完整迁移、无 Profile、native 普通 turn/frozen Skill、Web2、close、凭证扫描、容器/DB/workspace 清理 | `session-image-deployment.json` |
| `make security-scan`（最终镜像归档，已有 Trivy DB） | **退出 1**；secret=0、misconfiguration=0、34 HIGH/4 CRITICAL；`publishable=false` | `session-image-security-summary.json` |

最终解包自测 14 步包括 archive safety、两个 venv/锁定依赖安装、doctor、Harness tests、Integration tests、真实组合矩阵、manifest verify、capability check、无 Git 重建与重建验证。测试使用外部源码路径或可删除的交付快照，没有保留第三份长期业务源码。

故障矩阵涵盖：同 Session 冲突、steer/cancel、takeover/stale controls、provider drop/reset、request replay/hash conflict、SIGKILL replacement、EOF fanout/backpressure、lease revoke/late frames、父子中断隔离、未知副作用禁止重放与 exactly-once release。稳定 reason 包含 `turn_already_active`、`user_cancel`、`stale_epoch`、`epoch_takeover`、`model_config_stale`、`model_config_pin_lost`、`unknown_side_effect`。

## 冻结制品身份

最终 bundle：`.integration-state/artifacts/session-execution-bundle-final.tar.gz`。

- Bundle SHA256：`5c844ec6645075d984e0a05eaac9e325efb11a9216d0f4851c36ec9dc484f839`
- Image tag：`networkclaw:session-execution-final`
- Image ID：`sha256:67f79a32d863cf9de6de32c639351bb847faf6bca3f0d29c66b66fe95f0dca81`
- OCI archive SHA256：`37d9c13a924e06bdbbf348edc02f06e8503d1af25a6fe3392b5ca61b0c5f89ec`
- Frozen capability release：`sha256:71c198b48baa1e070abece89b96f1494da6c3fc0a21b71af5e05763011fe0382`

制品目录 `.integration-state/artifacts/ubuntu-22.04-linux-amd64/` 保留 OCI/Docker archives 与 `build-manifest.json`。Go/Web2 builder 为 Ubuntu 22.04，image packager 为 Darwin 26.5.2，runtime 为 Debian 12。native Ubuntu 30 场景测试和最终 image 部署是不同证据，不混用平台描述。

| 冻结源码 | Tree SHA256 |
| --- | --- |
| Go | `3dd4d7889827ec8d81809ed0505bd9ba91ab380cf0613f2d32e4b0b3ccf5b698` |
| Harness | `bec1ba50565683437ed7c6a742bef4899ba0dc5ea2b14e121cd2d33e29c228e5` |
| Integration | `a080ca68ed5aad30be70e85c91a12e8f250298c7d672add1453dc86636def6c4` |

三仓均为 dirty/customized 快照，commit/diff/vendor tree provenance 在 manifest。此验收摘要及三仓最终计划更新在制品冻结后形成，属于制品旁验收记录；当前文档树与归档冻结树可以不同，不改写已验证归档身份。

## 清理和限制

本任务专用 `networkclaw-session-ubuntu-runner` 容器及 `.integration-state/ci/session-runner/` 临时源码快照已删除，prepared-context identity 已移入 evidence。最终 public、矩阵、解包自测与 image 报告均证明各自测试资源清理；保留最终制品与必要证据。既有开发 chatrtmgr、Lobby、Vite 进程仍运行。三仓用户既有修改和 Integration 的 staged `.codebase-memory` 删除保留；未 commit/reset/clean。收尾三仓 `git diff --check` 与 staged diff check 均通过。

SessionDB、binding 文件、workspace 必须持久化并能由恢复节点访问；没有共享或可靠迁移时不能承诺跨节点历史恢复。Lobby 页面 exchange 为 best-effort，执行事实不因页面记录写失败而改变。未知旧 turn 禁止自动重执行。

本计划要求的模型凭证扫描通过。额外镜像漏洞扫描发现 cached immutable Debian base 有 34 HIGH / 4 CRITICAL 可修复系统包漏洞，Trivy DB 未刷新。公开发布前必须修复基础镜像并重跑安全/目标制品验收；目前 `publishable=false`。Go 全树 `go test ./...` 不在本次通过声明内，旧 Catalog CRUD 与 migration 029 的历史失败记录保留。本次没有迁移开发数据库。
