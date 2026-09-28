# NetworkClaw Integration Development Guide

本仓库是 NetworkClaw 交付体系的构建与联动仓库，不拥有 Go 后台或 Python Harness 的业务源码。
它负责把三个独立仓库组合成可本地调试、可在 Ubuntu 22.04 CI 验证、可交付和可部署的工程工作区。

## 仓库边界

三个仓库的职责必须保持清晰：

- `networkclaw`：Go 后台、服务协议和 Go 侧测试。
- `networkclaw-harness`：Python Host Adapter、Hermes runtime、`vendor/hermes` 和 Python 测试。
- `networkclaw-integration`（本仓库）：源码定位、启动编排、跨进程测试、故障夹具、CI、bundle、镜像和部署输入。

禁止在本仓库复制 Go 或 Harness 的业务源码作为第三份长期副本。联调使用外部源码路径、临时 checkout 或生成的 bundle；权威修改必须回到对应源码仓库。

## 工作区模型

推荐的本地布局：

```text
workspace/
├── networkclaw/
├── networkclaw-harness/
└── networkclaw-integration/
```

本地开发通过 `workspace.local.yaml` 指向前两个仓库；CI/发布通过 `sources.lock.yaml` 固定仓库、ref 和可验证的 commit/tree hash（格式模板见 `sources.lock.example.yaml`）。未提交的本地修改允许用于调试，但生成 bundle 时必须记录 dirty 状态和源码树 hash。

## 运行边界

- Go 仍是平台/路由/生命周期的一侧；不得在 integration 中实现第二套 Agent、model、tool、retry、plan 或 delegation loop。
- Harness 仍是 Hermes Agent 的 headless 执行侧；vendor 更新必须在 `networkclaw-harness` 中完成，并使用其同步和校验脚本。
- integration 只启动、连接、观测和验证两边，不解释模型文本，不绕过 Host Protocol，不持有用户 transcript 事实。
- 本地 Mac 是开发和快速验证环境；Ubuntu 22.04 Linux/amd64 CI 是最终镜像和部署制品基线。
- 部署消费 integration 生成的 bundle/image 和 manifest，不自行拼接两个源码仓库。

## 必须保留的验证路径

本地和 CI 应共享同一组高层入口，至少覆盖：

1. `doctor`：检查两个源码路径、Python/Go 版本、工具和配置，不输出密钥。
2. `dev-up` / `dev-down`：启动和停止 Go + Harness 联调工作区。
3. `test`：运行本仓库工具测试及两个子仓库的受支持测试入口。
4. `integration-test`：运行真实 Go ↔ Harness 协议和故障验收。
5. `bundle`：生成脱离原始 Git/绝对路径仍可使用的源码交付包。
6. `verify-bundle`：在临时目录验证 bundle 不依赖原始工作区。
7. `image`：在目标 CI 环境从 bundle 构建最终 Linux/amd64 镜像。

新增跨仓库协议或生命周期行为时，必须同时增加组合测试和失败语义证据；单仓库单测不能替代互操作验收。

## Bundle 与 provenance

`networkclaw-bundle` 是本仓库的构建产物，不是第四个长期维护源码仓库。Bundle 必须包含：两个源码快照、integration 工具/测试、CI/deploy 文件、文档和 manifest。

Manifest 至少记录：bundle 版本、三个源码树 hash、可用时的 Git commit、dirty 状态/diff hash、Harness vendor tree hash、Host Protocol 版本、目标平台和 customized 状态。源码包没有 `.git` 时，tree hash 仍必须可生成；Git commit 是可选 provenance，不是客户交付的前置条件。

Docker HUB 连接很慢，可以考虑使用一些CN国内镜像源。
py pip 源官方也不太稳，也可以考虑使用一些国内镜像源。
对于linux ubuntu等rpm或者apt源 也可以设置成CN国内镜像源，方便调试。


## Vendor 升级

不要直接在本仓库编辑 `networkclaw-harness/vendor/hermes`。先在 Harness 仓库执行 Hermes 同步、patch、vendor 验证和 Harness 回归，再在本仓库更新 `sources.lock.yaml` 并运行组合验收。

## 安全与操作约束

- 不提交 `.env`、密钥、token、客户数据或绝对本机路径。
- JSONL stdout 必须保持协议数据；诊断输出走 stderr 或受控 artifact。
- 临时 workspace、provider stub 和测试数据必须在测试结束时清理。
- 不使用 destructive Git 操作；不覆盖用户工作区未提交修改。
- 跨仓库任务结束时，分别报告三个仓库的状态、测试命令、计划/文档变更和遗留问题。

详细设计和交付决策见：

- [`README.md`](README.md)
- [`docs/adr/0001-three-repository-delivery.md`](docs/adr/0001-three-repository-delivery.md)
- [`docs/local-development.md`](docs/local-development.md)
- [`docs/bundle.md`](docs/bundle.md)
- [`docs/plan/integration-plan.md`](docs/plan/integration-plan.md)
