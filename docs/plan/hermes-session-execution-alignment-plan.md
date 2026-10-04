# Hermes 普通会话执行与 Snapshot 职责对齐计划

日期：2026-10-05。状态：T01～T11 已完成（11/11），逐任务验收记录见第 9 节及[最终验收摘要](../evidence/hermes-session-execution-alignment-acceptance.md)。公开发布安全门禁未通过，制品为 customized 调试交付。

本文件记录设计、任务依赖、实施与验收要求。三仓实现、真实进程组合、浏览器/真实 GPT 和最终交付制品复验已完成。数据库测试使用可清理的隔离夹具，未迁移开发数据库。

## 1. 整体任务解决的问题

当前普通聊天首次发送要求选择 Agent Profile 和 Published Revision；Lobby 的会话创建、Host Grant 生成、Harness 准入及子 Agent 授权又与 Agent Snapshot/Revision 耦合。结果是没有发布 Profile 的用户无法开始普通会话，已有模型配置也无法独立支撑完整聊天链路。

整体目标是让用户选择合法模型后即可开始普通会话，同时保留分布式授权、配置冻结、执行租约、历史连续性和 Hermes 原生 Tool/Skill/子 Agent 行为。

Agent、Skill、Tool 是数据库管理的配置资产；Session/turn 传递它们的冻结 snapshot 或不可变引用，最终接入 AIAgent 的加载与执行机制。数据库 Agent 配置与运行时 AIAgent 是不同对象：前者可作为可选预设，后者是每次执行所需、可复用或重建的对象。

本计划解决以下问题：

- 普通会话不再以已发布 Agent Profile/Revision 为创建和执行前提。
- Lobby 冻结授权和版本，chatrtmgr 固定并转发本轮模型配置，执行侧加载对应能力资产。
- Tool 注册、Skill 索引和正文读取使用相同的冻结版本和会话授权范围。
- Hermes 自行决定工具调用、Skill 加载和子 Agent 派遣；平台只提供授权、资源和生命周期约束。
- 模型切换、凭证轮换和 Agent 重建保留执行历史、workspace 与冻结能力权限。
- Hermes 压缩产生的内部 Session 变化能够正确关联平台 Session，页面记录与执行历史职责清晰。

范围不包含输入框 `@agent profile`、加号上下文交互、另一套 Agent loop、额外的 chatsvc 替换工作或整个配置数据库的重新建设。

## 2. 目标链路与职责

以下编号用于任务映射，不表示新增服务。

| 链路 | 行为 | 负责模块 |
| --- | --- | --- |
| L01 | 收到消息后创建或查询平台 Session、校验归属 | Lobby |
| L02 | 签发本轮 run/turn、执行租约和 epoch | Lobby |
| L03 | 解析授权策略、模型引用及最低版本 | Lobby |
| L04 | 从 Broker 解析模型配置、固定本轮配置、转发 | chatrtmgr |
| L05 | 校验租约和本地准入，打开运行时会话 | Harness |
| L06 | 复用或创建主 AIAgent，读取 Hermes SessionDB 历史 | Harness |
| L07 | 每个准入 turn 调用一次原生 `run_conversation()` | agent core；Harness 调用入口 |
| L08 | 调用工具、加载 Skill、决定派遣子 Agent | agent core |
| L09 | 保存执行历史、执行压缩 | agent core |
| L10 | 维护运行时绑定、发布结果和事件 | Harness |
| L11 | 保存页面消息记录、平台状态和关联信息 | Lobby |

平台 Session 是归属、路由和执行权的持久身份；Hermes Session 是原生执行历史与上下文的身份，压缩时可能变化；AIAgent 是可回收的执行对象。chatrtmgr 不组装 transcript，Lobby 页面消息记录不能替代 Hermes SessionDB。

准入分层沿用现有机制：Lobby 持久执行权，chatrtmgr 本地冲突与配置固定，Harness 租约/epoch 和本地执行锁。图中顺序表达职责；事务内授权校验与执行权签发的具体顺序应保证授权失败不会留下可执行 run。

## 3. Snapshot 与加载边界

### 3.1 不可变引用

“指针”必须能定位冻结内容，不是只包含 ID、执行时查询最新值的引用。按资产类型携带 ID/name、revision/version、内容或 schema hash、release/catalog 身份以及 snapshot hash；具体字段和 canonical hash 规则由 T01 冻结。

数据库负责配置事实、发布和授权。Harness 通过受信 snapshot 对照已部署的 release、Hermes registry 与本地资产，校验版本和内容；AIAgent 通过原生机制加载配置、工具和 Skill。此设计不要求 Agent 直接连接平台数据库，也不引入客户运行路径上的在线安装或下载。

旧 release 的保留与可用性必须支持仍引用它的会话；资产缺失或 hash 不符明确失败，不能静默换成最新版本。

### 3.2 两种冻结周期

| 对象 | 冻结周期 | 内容和用途 |
| --- | --- | --- |
| 会话执行策略及 Agent/Skill/Tool 引用 | Session | prompt 配置、权限模式、工具授权、Skill 版本与模式、预算和派遣上限；Agent Profile 来源可选 |
| 模型执行配置和本轮有效参数 | run/turn | 模型配置 ID、执行版本、凭证版本、连接、协议和参数；同一 run 重试复用 |
| 租约、epoch、run/turn 身份 | 本轮执行授权及显式续租 | 执行权与 fencing；独立于能力 snapshot，不混入资产内容 hash |

无 Profile 不等于无策略或无权限：普通会话必须形成完整可信授权。显式空工具集合表示不授予工具，字段缺失表示契约不完整，不能触发宽松默认工具集。

会话内本轮工具参数只能在冻结授权范围内收窄。模型选择独立于能力冻结，已有 Agent Revision 的模型引用只可作为经授权的默认值，不能固定所有后续 turn。

### 3.3 沿用模型同步设计

沿用 [Model configuration snapshot v1](../contracts/model-config-snapshot-v1.md)：Lobby 是模型配置权威来源；chatrtmgr 启动同步并每 30 秒轮询，单次超时 5 秒，最后成功确认超过 5 分钟拒绝新 turn；不在 turn 临时回源。模型版本不足返回可重试同步错误，不替换模型。

含凭证的 `model_execution` 是私有执行输入，不能进入会话能力 snapshot、公共事件、页面消息或导出包。凭证版本触发 Agent 重建，密钥原值或摘要不进入缓存身份。

## 4. 与现有计划的关系及实施基线

- [Capability 重建计划](hermes-capability-rebuild-plan.md) 提供配置资产、发布和 snapshot 基础，本计划调整普通会话对 Agent Revision 的强依赖，不撤销资产版本和授权机制。
- [Capability Contract v1](../contracts/capability-snapshot-v1.md) 的旧 Agent Revision 绑定由 T01 的 [session-execution.v1](../contracts/session-execution-v1.md) 补充：新增独立 execution snapshot，保留旧投影摘要兼容校验。实际协议以契约/schema 为准，本文记录实现和验收。
- [Capability 前端计划](hermes-capability-frontend-plan.md) 的配置管理页面继续沿用；本计划只处理普通聊天发送入口。
- [Integration 组合交付计划](integration-plan.md) 的测试、bundle 和目标平台入口继续使用。

本轮 review 确认的改造入口如下。路径以所属源码仓库为根，不是 Integration 内的业务源码副本。

| 仓库 | 入口 | 本计划关注的问题 |
| --- | --- | --- |
| NetworkClaw | `web2/src/pages/HomePage.tsx` | 首次发送要求 Profile/Revision，普通路径依赖旧 Agent Catalog |
| NetworkClaw | `internal/lobby/usecase/session.go`、`session_snapshots.go` | 建会话及能力冻结从 Profile/Revision 开始 |
| NetworkClaw | `internal/lobby/repository/harness_authority.go` | 完整能力和预算生成受 Agent Snapshot 条件控制 |
| NetworkClaw | `internal/chatrtmgr/forwarder/gateway.go`、`delegation_grant.go` | 已有模型固定链路；子授权依赖 Agent projection |
| networkclaw-harness | `src/networkclaw_harness/host/server.py` | 准入要求能力、Skill、Agent 三份 snapshot 齐全 |
| networkclaw-harness | `src/networkclaw_harness/runtime/hermes_host_adapter.py` | 已有原生调用与重建；空工具 fallback、独立策略和内部 Session 绑定需闭合 |
| networkclaw-harness | `src/networkclaw_harness/skills/catalog.py` | 已有冻结校验和投影；原生发现、索引与读取的一致视图仍需验收 |

实施前重新核对实际源码和已有测试，复用已满足目标的能力；不得根据旧文档状态重复重建功能。

## 5. 依赖与执行顺序

下表和后续任务正文均按拓扑顺序排列，被依赖任务在前。依赖表示进入实现和正式验收所需的前置产物；接口草案、测试夹具可提前准备。

| 顺序 | 任务 | 直接依赖 | 对应链路 | 主责 |
| --- | --- | --- | --- | --- |
| 1 | T01 冻结独立执行契约 | 无 | 全链路，重点 L03～L05 | Integration 协调；Go/Harness 联合 |
| 2 | T02 平台 Session 存储解耦 | T01 | L01、L11 | Go / Lobby |
| 3 | T03 普通会话授权和资产引用冻结 | T01、T02 | L01、L03 | Go / Lobby |
| 4 | T04 本轮执行权与独立 Host Grant | T01、T02、T03 | L02、L03 | Go / Lobby |
| 5 | T05 chatrtmgr 固定与转发 | T01、T04 | L04 | Go / chatrtmgr |
| 6 | T06 Harness 准入与主 Agent 生命周期 | T01、T05 | L05、L06、L07 | Harness |
| 7 | T07 原生 Tool/Skill 加载接入 | T03、T06 | L06、L08 | Harness |
| 8 | T08 原生子 Agent 派遣授权接入 | T04、T05、T06、T07 | L08；子执行复用 L02、L05～L07 | Go + Harness |
| 9 | T09 历史、压缩和运行时绑定连续性 | T02、T06 | L06、L09、L10、L11 | Harness；Go 配合 |
| 10 | T10 普通聊天发送入口 | T04、T05、T06 | 收到消息、L01～L04 | Go / web2 |
| 11 | T11 分布式组合与交付验收 | T01～T10 | L01～L11 | Integration；Go/Harness 配合 |

推荐执行顺序为 `T01 -> T02 -> T03 -> T04 -> T05 -> T06 -> T07 -> T08 -> T09 -> T10 -> T11`。

T06 完成后，T07、T09、T10 可分别推进；T08 必须等待 T07。T11 必须等待全部前置任务验收，不能以普通消息回复成功替代 Skill、派遣和历史验收。

## 6. 具体任务

### T01 冻结独立会话执行与资产引用契约

**状态**：已完成，验收记录见第 9 节。**依赖**：无。**链路**：全链路，重点 L03～L05。

**目的**：让普通会话、主 Agent 和子 Agent 在无 Profile/Revision 时仍有完整、可校验的执行输入，避免三侧各自解释 snapshot。

**具体任务**：

- 定义 Session 冻结策略与 Agent/Skill/Tool 引用；Agent Profile/Revision 作为可选来源信息，不控制能力与策略是否存在。
- 定义模型引用、最低执行/凭证版本、私有模型执行配置与本轮参数边界，沿用既有模型契约。
- 定义 Host Grant、租约、epoch、父子 lineage 和平台/Hermes Session ID 的独立字段语义。
- 明确缺失、空集合、optional 资产、版本/hash 不符及资产未部署的稳定错误语义；确定兼容滚动发布和协议版本规则。
- 在 Integration 契约/schema、Go `.proto` 和 Harness validator 设计中留下对应记录与脱敏样例；生成代码通过现有入口生成。

**产物与验收**：三侧一致的版本化契约和正/负样例；不含 Profile 的父/子输入可以完整表达授权，空授权、篡改引用和私有配置泄漏样例被明确拒绝。验收通过后下游才能依赖新契约。

### T02 平台 Session 存储与旧会话转换

**状态**：已完成，验收记录见第 9 节。**依赖**：T01。**链路**：L01、L11。**主责**：Go / Lobby。

**目的**：让平台 Session 的持久身份、冻结权限和执行策略独立于可选 Agent 配置。

**具体任务**：

- 独立存储 prompt 配置、权限模式、预算、派遣策略、能力引用和 snapshot 身份；保留可选 Profile 来源。
- 更新 model、repository、创建/查询接口和必要 migration，只补本计划所需存储。
- 将已有冻结 Agent projection 转为等价独立策略，保留原授权、版本和来源；转换需幂等且可审计。
- 不完整旧会话明确拒绝执行，不通过默认值扩大权限，也不创建占位 Profile。
- 记录 schema、数据转换的回退限制；回退代码不能把新会话重新解释为宽松旧授权。

**产物与验收**：必要 migration、持久化结构和兼容转换测试；无 Profile 会话可存取完整冻结配置，旧会话权限不变，部分数据损坏明确失败。

### T03 普通会话授权与能力引用冻结

**状态**：已完成，验收记录见第 9 节。**依赖**：T01、T02。**链路**：L01、L03。**主责**：Go / Lobby。

**目的**：普通会话可从平台/组织/用户授权与已发布资产形成执行基础，不要求预先发布 Agent Profile。

**具体任务**：

- 建立独立 resolver，从现有平台设置与组织/用户权限确定基础策略、允许的 Tool/Skill 和不可变资产引用；配置来源和优先级须明确。
- 校验发布状态、依赖和授权，冻结 ID、版本、hash 与 release 身份；不加载 Skill 正文或工具 handler。
- 取消普通会话的 `agent_profile_required`；可选 Profile 仍可提供预设，最终权限受平台授权约束。
- 普通能力授权包含合法的 Skill 发现/读取及派遣能力时应能正常使用，不以关闭全部工具绕过耦合。
- 既有 Session 使用已冻结引用；发布变更仅影响后续新 Session，资产不可用时返回明确失败。

**产物与验收**：独立授权 resolver 和会话冻结测试；零 Profile/Revision 时可创建合法普通会话，越权、未发布资产和依赖不满足均有失败证据。

### T04 本轮执行权与独立 Host Grant

**状态**：已完成，验收记录见第 9 节。**依赖**：T01、T02、T03。**链路**：L02、L03。**主责**：Go / Lobby。

**目的**：每轮执行权和完整授权从 Session 独立策略生成，不因缺少 Agent Snapshot 而退回旧默认权限。

**具体任务**：

- 保留现有 run/turn、执行租约、epoch、续租、takeover 和重复请求处理机制。
- 从独立冻结策略生成 Host Grant、预算、能力与 Skill 引用，解除 `session.AgentSnapshot != nil` 条件耦合。
- 校验会话归属、本轮模型启用与权限、参数及最低版本；授权失败不能产生可执行请求。
- 明确第一次与后续 turn、同步与流式路径的相同语义；每轮基础信息指向同一冻结会话配置。

**产物与验收**：授权/admission 和转发输入适配；无 Profile 可取得完整 Host Grant，模型停用与越权及时拒绝，重复 admission、续租和接管行为不回归。

### T05 chatrtmgr 本轮固定和转发契约

**状态**：已完成，验收记录见第 9 节。**依赖**：T01、T04。**链路**：L04。**主责**：Go / chatrtmgr。

**目的**：将可信会话引用和一次固定的模型执行配置送达 Harness，保留现有 Broker 与重试语义。

**具体任务**：

- 转发独立策略、snapshot 引用、Host Grant、run/turn、租约和 epoch，按契约区分缺失与显式空集合。
- 沿用 30 秒 Broker 与最低版本检查，一次读取不可变 snapshot 后固定本轮模型、参数和执行身份。
- 同一 run 重试使用已固定配置；进程或节点丢失固定状态后不能用最新配置自动重执行。
- 保留取消、控制和事件回放路径，它们不重新解析模型；错误保持可重试/不可重试区别。
- 不增加 transcript 组装、Skill 正文解析、工具执行或模型文本规划逻辑。

**产物与验收**：Go forwarding 适配及协议捕获夹具；输入引用与身份一致，模型同步不足可重试，刷新 snapshot 不改变已固定 run，控制与回放不受模型同步故障阻断。

### T06 Harness 准入、主 Agent 复用与原生 turn

**状态**：已完成，验收记录见第 9 节。**依赖**：T01、T05。**链路**：L05、L06、L07。**主责**：Harness。

**目的**：将独立可信配置接入现有 Hermes runtime，保持执行权和历史与 AIAgent 缓存对象分离。

**具体任务**：

- validator 接受完整独立策略与能力/Skill snapshot，不再要求包含 Agent Revision 的三份 snapshot 齐全。
- 校验 workspace、租约、epoch、资产身份及模型显式配置；不使用模型环境变量补齐无效执行输入。
- Agent 缓存身份采用模型执行版本、凭证版本、初始化参数和有效冻结策略/能力身份；单纯来源标签或展示字段变化不触发重建。
- 身份相同复用；变化时在 admission 锁内释放并重建，保留 SessionDB/workspace；初始化失败不能执行旧对象。
- 显式空工具授权保持为空；逐 turn effort 等参数按现有方式应用并恢复；每个准入 turn 只调用一次原生 `run_conversation()`。

**产物与验收**：validator、adapter 和缓存生命周期适配；无 Profile 可执行，复用/模型切换/连接或凭证轮换符合身份规则，空授权和重建失败不会启用旧配置，迟到事件仍被 fencing 拒绝。

### T07 原生 Tool/Skill 加载与会话隔离

**状态**：已完成，验收记录见第 9 节。**依赖**：T03、T06。**链路**：L06、L08。**主责**：Harness。

**目的**：snapshot 真正约束 Agent 可加载和调用的能力，而非只存在于数据库或 prompt 投影。

**具体任务**：

- 冻结 Tool 引用与 Hermes registry、schema/hash 和可用性检查对齐；工具集合始终不超过授权。
- 为 Skill metadata 索引、`skills_list`、`skill_view`、正文和支持文件读取提供相同的会话冻结视图。
- 按契约实现 `available`、`auto_load`、`disabled` 等模式；原生 Agent 在可见范围内决定按需加载。
- 处理 release 版本保留、内容/hash 校验、路径边界和依赖失败；不得静默读取宿主全局或其他会话 Skill。
- 覆盖主 Agent 重建和并发 Session；提供可由 T08 复用的子 Agent 能力加载入口。
- 必要 Hermes 修改经 Harness patch、同步和 vendor 校验流程，禁止直接手改 vendor。

**产物与验收**：能力加载适配和原生工具行为测试；模型能通过原生 Skill 工具读取正确冻结内容并调用授权工具，禁用/越权/篡改内容被拒绝，并发与重建保持版本和会话隔离。

### T08 原生子 Agent 派遣与有限资源授权

**状态**：已完成，验收记录见第 9 节。**依赖**：T04、T05、T06、T07。**链路**：L08，子执行复用 L02、L05～L07。**主责**：Go + Harness。

**目的**：让 Hermes 任务驱动的动态派遣在无发布子 Agent Revision 时正常工作，同时保留分布式授权与资源上限。

**具体任务**：

- core 通过原生 delegation 决定任务、目标和上下文；不要求它自动发现或选择平台数据库 Profile。
- 平台依据父会话冻结策略授权资源，chatrtmgr 在既有授权链内派生受限 child grant；Harness 验证后接入原生子 Agent 构造。
- 从独立策略读取派遣权限、深度、并发和预算，解除 Agent projection/Revision 必需条件；父子授权不扩大。
- 子 Agent 使用独立 session/workspace/SessionDB 和明确生命周期；身份、租约及 lineage 按 T01 约定，禁止自行制造平台执行权。
- 默认继承父 turn 固定的完整模型配置；特殊路由必须来自可信授权，不能被环境或独立 delegation provider 配置覆盖。
- 保留原生子 Agent 执行入口，覆盖拒绝、资源不足、超时、取消及释放；对齐 native 深度规则和平台上限。

**产物与验收**：child grant 与原生构造接入；无 Profile 的实际 delegation 可完成，子模型/能力继承正确，越权与超限拒绝，取消/失败后无资源残留，不增加第二套派遣 loop。

### T09 执行历史、压缩与运行时绑定

**状态**：已完成，验收记录见第 9 节。**依赖**：T02、T06。**链路**：L06、L09、L10、L11。**主责**：Harness；Go 配合关联存储。

**目的**：Session 历史连续性不依赖 AIAgent 对象是否仍在缓存，也不被模型切换或内部 Session 压缩破坏。

**具体任务**：

- core 沿用原生 SessionDB 历史持久化和压缩，Harness 读取正确内部 Session 的历史，不从 Lobby 页面记录重建执行 transcript。
- 维护平台 Session 到当前 Hermes Session 的可恢复绑定；压缩改变内部 ID 后，仅由有效 generation/epoch 发布新绑定。
- Agent 重建、进程恢复时重新读取同一历史；历史不可读或绑定不明时失败，不能回退到空历史。
- Harness 发布脱敏结果和关联事件，Lobby 保存页面消息、平台状态及必要关联；明确当前 best-effort 页面记录的可靠性边界。
- 分开进程重启、本节点重启和跨节点迁移的恢复条件；核实 SessionDB/workspace 的实际持久存储和可访问性。
- 保留未知副作用失败语义和旧 run 禁止自动重执行；可继续会话不等于可以重跑旧 turn。

**产物与验收**：绑定存储/恢复适配和历史连续性测试；压缩后切换模型与缓存重建不丢历史，迟到绑定更新拒绝，缺失历史明确失败。若现有存储不能跨节点恢复，必须记录限制及部署前置条件，不能宣称无条件恢复。

### T10 主页面普通发送入口

**状态**：已完成，验收记录见第 9 节。**依赖**：T04、T05、T06。**链路**：收到消息、L01～L04。**主责**：Go / web2。

**目的**：用户不需要选择 Profile/Revision 即可用授权模型开始聊天，前端输入与后端新契约一致。

**具体任务**：

- 删除首次普通发送的 Profile/Revision 必选检查，创建会话请求允许不携带这两个字段。
- 普通发送路径解除旧 Agent Catalog 依赖，避免已关闭接口阻断聊天。
- 保留本轮模型和参数选择、会话归属错误、发送状态、取消及后续 turn 行为。
- 模型尚未同步等可重试错误保留草稿或提供明确重试状态，避免出现重复或假成功消息。
- 不扩展 `@agent profile` 和加号上下文功能；已有可选预设路径不得扩大授权。

**产物与验收**：页面与 API 消费适配；无 Profile 用户从主页面首次发送成功，同会话后续切换模型正确，失败可恢复草稿，普通路径不请求旧 Agent Catalog。

### T11 分布式组合、用户流程与交付验收

**状态**：已完成，验收记录见第 9 节。**依赖**：T01～T10。**链路**：L01～L11。**主责**：Integration；Go/Harness 配合。

**目的**：证明整个职责链在真实进程、故障和交付环境中成立，不能用单仓单测或一次普通回复替代验收。

**具体任务**：

- 在两个 Lobby、两个 chatrtmgr 的真实组合中验证无 Profile 首轮、归属授权、完整 grant 和模型配置传递。
- 用确定性 provider stub 驱动原生工具、Skill 读取和 delegation，断言实际加载版本、模型、参数、lineage 与拒绝语义。
- 验证模型 A→B、同名模型不同连接、凭证轮换、Broker 30 秒收敛和 5 分钟过期；原 turn 不受刷新影响。
- 覆盖压缩后绑定、Agent 重建、重启与接管、并发准入、迟到控制/事件及固定配置丢失；区分历史恢复与未知副作用重执行。
- 通过可控时钟验证同步与过期规则；故障夹具只用于测试，清理 provider、proxy、临时 workspace 和进程。
- 扫描诊断、公共事件、页面记录、bundle 和导出包，证明无模型凭证泄漏；私有执行输入只保留脱敏断言。
- 完成 `dev-up`、浏览器普通发送与真实 GPT 验收；失败时记录阶段与原因，不把连接测试成功当成整链路成功。
- 检查 bundle 对新契约、冻结 release 和必要 vendor patch 的完整包含，验证脱离本地源码路径；目标制品在 Ubuntu 22.04 Linux/amd64 验证。

**产物与验收**：组合矩阵、失败语义、命令/退出码和脱敏 artifact；全部必验场景有证据，未覆盖限制明确列出。Go 使用 `-race`，Harness 使用 CPython 3.12 与 `scripts/run_tests.sh`，Integration 使用既有高层入口。

## 7. 验收与进度记录规则

所有任务初始为待实施。完成某任务时记录实际文件或接口、测试命令、退出码或通过数、覆盖场景、失败 reason code 和遗留问题；未达验收不得提前标记完成。

三仓证据分别归属：

- Go：协议、migration、resolver、admission、forwarding、web2 与对应模块计划记录。
- Harness：validator、加载接入、原生执行、Agent cache、绑定恢复、patch/vendor 与 Harness 计划记录。
- Integration：契约对账、组合矩阵、用户流程和交付证据；不保存业务源码副本或用户 transcript 事实。

高层验证入口沿用 `doctor`、`test`、`integration-test`、`dev-up`/`dev-down`、`bundle`、`verify-bundle`、`image`。实际命令和参数在执行后填写，不提前生成成功证据；运行期脱敏证据存入 `.integration-state/evidence/`，需要保留的审计摘要另行整理。

## 8. 实施前需闭合的设计细节

以下由对应前置任务解决，不代表需要再次确认已确定的职责链：

| 细节 | 负责闭合任务 |
| --- | --- |
| 独立策略和 asset ref 的字段、hash、兼容发布版本与错误码 | T01 |
| 普通会话基础策略的配置来源、优先级和租户/用户权限交集 | T03 |
| 旧 snapshot 到独立策略的等价转换与安全回退 | T02 |
| 已冻结旧 release 的保留与运行节点资产可用性 | T01、T07 |
| 子执行权在现有授权链中的分配及续租、取消、资源回收 | T01、T08 |
| 当前本地 SessionDB/workspace 的恢复范围与跨节点存储前提 | T09 |

配置回滚继续生成更高模型版本，不能降低 snapshot revision；能力和协议回退须保留冻结版本与授权语义。实施过程保持所有用户已有未提交工作，任务末分别报告三个仓库状态、测试证据、计划变化和未完成项。


## 9. 实施检查点（2026-10-05）

T01～T11 均达到本计划实现和验收要求，计入 11/11。功能、组合与交付验证通过；公开发布安全门禁单独记录为未通过，不将 customized/dirty 制品描述为可公开发布。审计摘要保存逐项产物、命令、证据哈希、最终制品身份和限制。

| 任务 | 已落地产物（路径以所属仓库为根） | 本地证据 / 当前缺口 |
| --- | --- | --- |
| T01 | 三仓 `session-execution.v1` 契约/schema、Host proto、父/子/空授权正负样例与 canonical hash | schema 对账、Go contract/storage race 和 Harness validator 通过；旧 capability/Skill digest 兼容已修复并通过实际派遣 |
| T02 | Go migration 031、Session 独立策略存储与等价旧会话转换 | 隔离 PostgreSQL 完整迁移、存取、幂等转换、损坏拒绝、fork 与安全回退拒绝通过；开发库未迁移 |
| T03 | Go 无 Profile resolver 与可选预设权限收窄 | 零 Profile public `{}` 创建 HTTP 201；冻结资产及发布/依赖/越权负例通过 |
| T04 | Go 独立 Host Grant、admission、租约边界续租 | 双 Lobby public HTTP/WS 与归属拒绝通过；增加 turn 前显式更新已到 renew_by 的租约；真实 PG 证明过期、旧版本和旧 epoch 不能续活 |
| T05 | chatrtmgr 版本握手、Broker、pin、受限 child grant | 双 manager 生产 30 秒收敛通过；可控时钟 5 分钟过期与刷新、pin 丢失禁止重执行、回放不启动 turn 的 Go race 测试通过 |
| T06 | Harness validator、主 Agent/cache、native turn | 全量 CPython 3.12/vendor/runtime closure 通过；模型/连接/凭证重建、空授权、epoch fence 与单次 native turn 通过。EpochError 保留稳定原始 code/reason_code |
| T07 | deployed release、FrozenSkillView、patch 0005/0006 | public native Skill 正文/hash/version 与 workspace Tool 已验证；并发/重建隔离与原生压缩工具冻结通过 |
| T08 | Go durable child authority、native delegation/child lifecycle | public 无 Profile child Skill、能力收窄、model/effort/max output 继承及分配释放通过；native 7 场景含成功、策略/容量拒绝、分配超时、预算越界、实际 child provider 失败、active child cancel 后资源清理；Go PG 深度/并发/过期/接管负例通过 |
| T09 | native binding/SessionDB、Go migration 032 与关联持久化 | 原生旋转压缩、模型/凭证重建、全新 OS 进程 epoch 3 恢复通过；public 关联写入与 Go 迟到/generation/conflict 拒绝通过；恢复存储前提见下文 |
| T10 | Web2 普通 `{}` create、可选预设与恢复草稿 | 前端 339 passed/1 skipped、typecheck/build 通过；真实 Chrome 登录、首次无 Profile 发送、同 Session 模型切换、零 Agent Catalog 请求通过 |
| T11 | 双 Lobby/manager、独立故障矩阵、浏览器与隔离 lifecycle、bundle/image | 已完成：最终 public 流程通过；组合矩阵 10 命令/15 场景全部退出 0，cleanup=clean；最终 bundle 解包自测 14 步全部退出 0；Ubuntu 22.04/amd64 编译、镜像部署及凭证扫描通过。基础镜像漏洞阻止公开发布，见独立安全记录 |

可复验入口与实际证据：

- `MODEL_ACCEPTANCE_PGADMIN=<夹具管理员> make session-execution-acceptance SESSION_EXECUTION_ACCEPTANCE_ARGS=--real-gpt`：退出 0，`session-execution-real-gpt.json` 保留成功证据。真实 GPT 普通 Session 回复通过，未导出连接凭证。
- `NODE_PATH=<Playwright 模块目录> MODEL_ACCEPTANCE_PGADMIN=<夹具管理员> make session-execution-acceptance SESSION_EXECUTION_ACCEPTANCE_ARGS=--browser`：退出 0；`session-execution-acceptance.json` 含实际 Chrome 页面流程和全部 public/native 断言。
- `MODEL_ACCEPTANCE_PGADMIN=<夹具管理员> make session-dev-lifecycle-acceptance`：对应 runner 已退出 0；`session-dev-lifecycle.json` 证明独立 DB、端口、state/workspace 与 provider 的 full `dev-up/dev-down`。已有开发栈未停止。
- Go `go test -race -count=1 ./tests/integration/harnessinterop -run '^TestIndependentExecutionFaultMatrix$'`：退出 0，包含同 Session 冲突、steer/cancel、takeover/stale control、provider drop/reset、shutdown 与迟到控制。
- Go `make test-session-execution-storage TEST_RUN='.'` 与 coordinator `make test-context`：均退出 0；新增边界续租、过期拒绝及 clock/pin loss 由增量 race 测试通过。
- Harness `scripts/run_tests.sh tests/test_native_execution_delegation.py -q`：7 场景退出 0；成功和负例均使用真实 vendored AIAgent。`scripts/run_tests.sh -q` 已通过全量、1104 vendor 文件及 imports/offline/globals closure。
- Ubuntu 22.04.5/amd64 的解包源码使用 CPython 3.12.15，native admission、deployed Skill、delegation 和 OS 历史恢复 30 场景退出 0；Ubuntu Go/Web2 编译已完成。编译产物与镜像打包宿主分别记录，不将 Mac 交叉编译写成 Ubuntu 验收。

最终冻结前补充证据：`session-public-final.json` 的 Chrome、真实 GPT、双 Lobby/manager、无 Profile Skill/派遣、凭证轮换与 manager 重启均通过。旧 run 在重启后被 `model_config_pin_lost` 拒绝且未触发 provider；新 turn 在准入前幂等恢复用户运行时路由，签发新 owner/epoch 并读取原 native tip。Go Lobby 全量 `-race` 通过。`session-combination-final.json` 全部命令退出 0、清理为 clean；清理使用每次矩阵独立环境标记，避免把并发验收进程误算为残留，环境内容不进入 artifact。

Integration 最新工具测试 141 项通过。首次安装交付显式使用空 Profile export，保留完整 Tool/Skill release；Agent mutation 负例使用独立测试资产，不要求实际发布清单含 Profile。最终镜像内普通 turn、冻结 Skill、TLS Broker、Web2 和凭证扫描通过，`session-image-deployment.json` 匹配最终 bundle SHA256 和 image ID。基础镜像扫描无 secret/misconfiguration，另有 34 HIGH / 4 CRITICAL 可修复系统包漏洞，扫描退出 1，`publishable=false`；Trivy 使用已有数据库，未更新。公开发布前须修复基础镜像并重新运行安全门禁。

最终交付复验：`BUNDLE_OUTPUT=.integration-state/artifacts/session-execution-bundle-final.tar.gz make bundle-self-test` 退出 0，`session-bundle-self-final.json` 为 passed，14 步全部退出 0，包括 doctor、Harness supported tests、Integration tests、真实组合矩阵、manifest/release 校验、无 Git 重建与重建验证；临时解包目录已删除。`make verify-bundle`、`make image` 和 `make session-image-acceptance` 对最终冻结输入均退出 0。Go/Web2 在 Ubuntu 22.04 编译，镜像在 Darwin 打包，运行基底是 Debian 12；不将三者混写为 Ubuntu runtime。

最终 bundle SHA256：`5c844ec6645075d984e0a05eaac9e325efb11a9216d0f4851c36ec9dc484f839`；image ID：`sha256:67f79a32d863cf9de6de32c639351bb847faf6bca3f0d29c66b66fe95f0dca81`。冻结源码树与制品身份见[审计摘要](../evidence/hermes-session-execution-alignment-acceptance.md)和对应 JSON。最终验收文档在制品冻结后更新，属于制品旁验收记录；不改变已验证归档的身份。

最新改动还修复 bundle manifest 的 Harness 路径：归档实际目录为 `networkclaw-harness`，manifest/schema/example 与消费方保持一致；verifier 校验源码路径确实定位归档中的源码 marker。旧 bundle 不能当作此修复的证据。三仓 dirty/customized 状态保留，如实记录 provenance，不宣称为 clean publishable release。

恢复边界：Hermes SessionDB、绑定文件与 workspace 必须持久化并可由恢复节点访问。相同持久目录支持进程重启/更高 epoch 续会话；没有共享或可靠迁移的存储时不能宣称跨节点历史恢复。平台 `session_runtime_bindings` 只保存内部 ID、epoch/generation 与 run/turn 关联，不保存 transcript。Lobby 页面 exchange 是 best-effort 记录，写失败不改变已执行事实，也不能成为重建执行历史的输入。未知旧 turn 禁止自动重放。
