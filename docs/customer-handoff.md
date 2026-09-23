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
