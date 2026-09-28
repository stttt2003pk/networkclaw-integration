# 客户源码包交接

客户交付物是 `networkclaw-bundle.tar.gz`、同名 `.sha256`，以及需要可信来源时的 detached `.sig`。bundle 解压后包含 `networkclaw/`、`networkclaw-harness/`、`integration/` 和 provenance manifest；它是无 Git 元数据的源码快照，不是第四个长期源码仓库。

## 解包后自验

需要 CPython 3.12、Go toolchain（运行组合矩阵时）、Harness 支持的构建工具，以及可访问 Python package index，或预先准备好兼容平台 wheelhouse。自测会在系统临时目录解压，不使用原始源码仓库、Git metadata 或已有 virtualenv：

```bash
python3.12 integration/tests/bundle/self_test.py networkclaw-bundle.tar.gz \
  --report bundle-self-test.json
```

禁网环境可提供依赖 wheelhouse；它必须包含 Harness 的 `requirements.lock`、`requirements-dev.lock`、`requirements-build.lock` 与 Integration `pyproject.toml` 所需依赖的 wheel：

```bash
python3.12 integration/tests/bundle/self_test.py networkclaw-bundle.tar.gz \
  --wheelhouse /path/to/wheelhouse \
  --report bundle-self-test.json
```

自测按顺序执行 archive safety、依赖安装、doctor、Harness 全量测试、Integration 测试、Go↔Python 组合矩阵、bundle manifest/checksum 验证，以及从解压源码重建并再次验证 bundle。失败报告包含失败阶段、退出码、脱敏且限长的错误尾部和缺失输入线索。测试不继承 `NETWORKCLAW_*` 等本机组合路径设置。临时目录总会清理；排查失败时可增加 `--keep-workspace`。

本地快速使用已有相邻工作树时，运行 `make bundle-self-test`；这是便利入口，不替代客户交付前对最终 bundle 执行上述隔离自测。macOS arm64 结果是源码交付 smoke，不代表 Ubuntu 22.04 Linux/amd64 镜像构建通过；目标平台构建仍由 I-08 验收。

## 交给客户的依赖边界

- Harness Python runtime、development 和 build 依赖分别由 bundle 内 `requirements.lock`、`requirements-dev.lock`、`requirements-build.lock` 固定，并要求 CPython 3.12。
- Integration Python 依赖由 bundle 内 `integration/pyproject.toml` 固定版本声明；安装时需要 package index，或准备对应 wheelhouse。目标 Ubuntu CI 的离线 wheelhouse/base image 与禁网复验由 I-08 建立。
- 组合矩阵依赖 Go toolchain、Harness Python 环境、bundle 中的源码和本地 loopback/socket 能力；provider stub 不需要真实模型 key。
- 最终 OCI 镜像、Linux/amd64 artifact、SBOM 和安全扫描不是本地自测的产物，属于 I-08。

## 三组协作与首次部署

- 后台组在 `networkclaw` 修改 Go 服务与数据库 migration；Harness/UE 组在 `networkclaw-harness` 修改 Python、Hermes vendor；构建组在 `networkclaw-integration` 维护源码解析、组合测试、bundle、Ubuntu CI、镜像和部署输入。不要将 bundle 当成第四个长期源码仓库。
- 日常本地联调按 [`docs/local-development.md`](local-development.md) 使用两个相邻源码工作树和 Integration `make dev-up`；组合变更运行 `make integration-test`。vendor 更新先按 [`docs/vendor-upgrade.md`](vendor-upgrade.md) 完成兼容性回归。
- 构建组交付 source bundle、checksum、I-08 OCI 归档及 build manifest；部署组核对归档，推送到客户 registry 后记录可拉取的 image digest。build manifest 的归档 SHA-256 不等于 registry digest。
- 首次部署按 [`docs/deployment.md`](deployment.md) 准备 PostgreSQL/Redis、执行 migration、创建 Secret、安装 Helm chart，并用 `--session` smoke 验证 Go → chatrtmgr → Harness Gateway 启动链。实时事件使用 canonical envelope；旧 chatsvc 仅保留在隔离回退和历史读取兼容范围内。Docker/Compose 仅用于本地或单机验证。
- 失败时保留构建报告、镜像 digest、Helm values（不含密钥）、Pod 状态和脱敏诊断；按故障所属仓库回交权威团队。对外分享日志前人工检查敏感信息。
