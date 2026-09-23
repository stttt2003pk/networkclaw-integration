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
/Users/maxrocketman/myproject/
├── NetworkClaw/
├── networkclaw-harness/
└── networkclaw-integration/
```

复制配置并按本机情况调整路径：

```bash
cp workspace.local.example.yaml workspace.local.yaml
make doctor
```

后续入口预留为：

```bash
make dev-up
make test
make integration-test
make bundle
make verify-bundle
make image
```

当前仓库刚初始化，入口先作为稳定契约保留；实现应按 ADR 和 AGENTS 约束逐步落地，不要先造一个新的 runtime 或 scheduler。

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
