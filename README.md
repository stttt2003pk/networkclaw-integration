# NetworkClaw Integration

这是 NetworkClaw 的构建组仓库，负责组合三个独立 Git 仓库：

```text
networkclaw.git              Go 后台
networkclaw-harness.git      Python Harness + vendor/hermes
networkclaw-integration.git  本仓库：联调、测试、CI、bundle、镜像、部署输入
```

本仓库不复制前两个仓库的业务源码。客户可以在本地同时修改 Go 和 Harness，然后通过本仓库的工具联调；CI 则从 `sources.lock.yaml` checkout 可验证的源码组合。

## Primary 设置是否合理

将本仓库作为 Codex project 的 primary 是合理的，因为跨仓库任务的入口通常是“组合行为”：启动 Go + Harness、验证协议、构建 bundle、生成镜像和排查联调问题。它不是 Go 或 Python 业务代码的替代 primary，而是协调层 primary。

primary 必须通过以下信息了解其他仓库，而不是把源码复制进来：

- NetworkClaw 仓库内的 `AGENTS.md`；修改该仓库前必须读取。
- Harness 仓库内的 `AGENTS.md`；修改该仓库前必须读取。
- Harness 文档中的 `docs/integration.md` 协议边界。
- `workspace.local.yaml`（本地路径，个人配置，不提交）
- `sources.lock.yaml`（CI/交付组合，提交）

## 本地工作区

推荐目录：

```text
<workspace>/
├── NetworkClaw/
├── networkclaw-harness/
└── networkclaw-integration/
```

复制配置并按本机情况调整路径：

```bash
cp workspace.local.example.yaml workspace.local.yaml
make bootstrap
make doctor
```

当前本地联合开发入口：

```bash
make dev-up
make restart-go
make restart-harness
make logs
make bundle
make dev-down
```

`make restart-harness` 会重启其拥有者 chatsvc，因为 Harness 是 chatsvc 管理的 JSONL 子进程，而不是独立 daemon。Integration 状态和日志落在 `.integration-state/`。provider 本地配置从 NetworkClaw `.env` 读取（shell 环境优先），值不会进入日志。契约示例可通过 `make validate-contracts` 校验。

故障夹具和真实跨仓验收入口：

```bash
make fault-fixtures
make integration-test
make combination-matrix
```

`make fault-fixtures` 只运行 Integration 自身的离线 provider/transport 夹具，不需要外部模型 key。`make integration-test` 在此基础上运行 NetworkClaw 的真实 Go ↔ Harness interop；可以设置 `NETWORKCLAW_SKIP_REAL_INTEROP=1` 只验证夹具。JSONL fault proxy 包裹真实 Harness 的示例见 [`docs/fault-fixtures.md`](docs/fault-fixtures.md)。

`make combination-matrix` 与 `make integration-test` 使用同一矩阵入口，生成 `.integration-state/evidence/combination-matrix.json`；场景和 Mac 验收证据见 [`docs/evidence/combination-matrix.md`](docs/evidence/combination-matrix.md)。

CI 组合配置模板见 [`sources.lock.example.yaml`](sources.lock.example.yaml)。不要把模板占位值当作已验证的源码版本。

## 实施计划

任务依赖、阶段顺序、旧计划缺口映射和验收门禁见 [`docs/plan/integration-plan.md`](docs/plan/integration-plan.md)。

## 交付关系

```text
三个源码仓库
      │
      ▼
networkclaw-integration
      │
      ├── customer source bundle
      └── Linux/amd64 image
```

`networkclaw-bundle` 是构建产物，不是第四个长期维护源码仓库。客户可以继续维护三个仓库，也可以把 bundle 导入自己的单仓库。
