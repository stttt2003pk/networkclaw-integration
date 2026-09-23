# 本地联合开发

本地联合开发使用三个 sibling Git 仓库，不要求把源码复制进 integration：

```text
workspace/
├── networkclaw/
├── networkclaw-harness/
└── networkclaw-integration/
```

`workspace.local.yaml` 只保存本机路径，不提交到 Git。路径可使用相对 integration 仓库的路径或绝对路径。integration 工具通过它启动两个真实工作树，因此 Go 或 Harness 的未提交修改可以立即参与联调。

本地开发的目标命令：

```bash
make doctor
make dev-up
make integration-test
make dev-down
```

实现工具时，应支持显式路径参数作为配置文件的覆盖，并避免依赖当前 cwd、软链接或绝对路径推断。软链接可以作为便利入口，但不能成为协议或 bundle 的前置条件。

Mac 本地负责快速反馈和调试；最终 Linux/amd64 镜像仍由 Ubuntu 22.04 CI 构建。
