# Bundle 交付

`networkclaw-bundle.tar.gz` 是由 NetworkClaw、Harness 和 Integration 三个独立源码树生成的交付快照，不是第四个长期维护仓库。归档内容位于 `networkclaw-bundle/` 下，包含三个源码目录、`manifest/bundle-manifest.json` 和 audited capability release payload；Integration 源码中会带入 CI、部署、脚本、测试和文档等已纳入版本控制或未忽略的文件。

## 本地/custom bundle

本地调试和客户二次开发允许 dirty Git 工作树或无 Git 的源码包。manifest 会分别记录三个源码树的 tree SHA-256、可用的 commit、dirty 状态及 diff SHA-256；无 Git 时 commit/dirty/diff 为 `null`，并标记为 customized。所有 local bundle 顶层 `customized` 均为 `true`，不能作为正式 release provenance。

```bash
make bundle
make verify-bundle
```

默认读取 Integration 同级的 `../NetworkClaw` 与 `../networkclaw-harness`。其他工作区可传 `NETWORKCLAW_PATH`、`HARNESS_PATH`，或直接调用 `tools/build-bundle.py --networkclaw ... --harness ...`。输出默认写到 `.integration-state/artifacts/networkclaw-bundle.tar.gz`，同目录生成 `.sha256` sidecar。自定义输出若放在源码树内，必须处于明确排除的构建/缓存目录。

## 正式 release bundle

release 必须提供 `sources.lock.yaml`，三个源码树均需有 Git metadata、clean worktree，并且 commit 与 tree hash 同 lock 完全一致。release lock 的 tree hash 使用 Integration `source_tree.py` 的规则计算；可通过 `tools/resolve_sources.py --json` 查看同一身份 hash。dirty 源码或无 Git 源码不能通过 release gate。

```bash
make bundle BUNDLE_RELEASE=1 BUNDLE_VERSION=1.2.3
make verify-bundle
```

可选 OpenSSL detached signature：

```bash
make bundle BUNDLE_SIGNING_KEY=/secure/path/release.pem
make verify-bundle BUNDLE_PUBLIC_KEY=/secure/path/release-public.pem
```

没有传公钥时 verifier 仍检查 checksum 和归档完整性，但不会声称签名可信。私钥只由签名步骤读取，不写进 bundle 或 manifest。

## 内容与完整性规则

- `.git`、virtualenv、缓存（包括 `.codebase-memory`）、常见构建产物、本机 `.claude/ecc/install-state.json` / `.codebuddy/ecc-install-state.json` / `.codebuddy/hooks/hooks.json`、生成的 `*.delivery.json` / `*.visual-check.json` 收据、`.env` 文件和 `.DS_Store` 不进入源码快照。
- 拒绝不安全 symlink、私钥/疑似凭证内容和 `/Users/<name>`、`/home/<name>` 本机路径；同一检查也由 verifier 对归档再次执行。
- tree hash 按相对路径、文件模式及内容 SHA-256 计算；symlink 按相对路径和 link target 计算。它是交付快照身份，不等同于 Git tree object hash。
- manifest 内 `artifacts.files` 列出每个归档 payload 的 SHA-256。manifest 自身不哈希自身；归档整体 checksum 在 `.sha256` sidecar，避免循环依赖。
- verifier 只读取 bundle、checksum sidecar 及可选公钥，不访问原始工作区。它验证路径安全、manifest schema、文件清单与 hash、敏感内容和可选签名。

`verify-bundle` 同时证明 capability release payload 与 bundle schema、release hash、三仓 provenance、vendor gate、check/diff 和 migration plan 一致。它不证明脱离原工作区后的源码测试或镜像构建可成功；后者属于 I-07 / I-08。

源码 manifest 的 `sources.harness.path` 为归档中的 `networkclaw-harness`；验证器要求各来源路径确实定位源码 marker，镜像消费者按 manifest 获取路径。

目标构建可分为 Ubuntu 源码编译与镜像打包两步。运行 `ci/ubuntu-22.04/build-artifacts.py` 时设置 `CI_PREPARE_IMAGE_CONTEXT=<输出目录>`，从已验证 bundle 编译并生成 context 及邻接 `.identity.json`；后续 `make image` 设置 `CI_PREPARED_IMAGE_CONTEXT=<该目录>`。消费者校验 bundle SHA256 与全部 context 文件，变更、缺失或新增文件均失败。build manifest 分别记录实际 `builder` 与 `packager` 宿主，避免将 Mac 打包记录成 Ubuntu 编译。普通 CI 不设置这两个参数时仍执行原有完整入口。
# 普通会话交付验收

首次安装且没有 Agent Profile 时，编译 release 应显式使用空 Profile 导出：

```bash
make bundle BUNDLE_CAPABILITY_RELEASE=1 \
  CAPABILITY_RELEASE_AGENTS=tests/fixtures/capability-release/empty-agent-discovery-v1.json \
  BUNDLE_OUTPUT=.integration-state/artifacts/session-execution-bundle.tar.gz
make bundle-self-test BUNDLE_OUTPUT=.integration-state/artifacts/session-execution-bundle.tar.gz
```

这仍包含完整 Tool/Skill release。默认 Agent discovery 测试夹具引用测试 Profile；客户导出含可选 Profile 时，导入前须满足其配置资产前提，不能创建占位 Profile 绕过普通会话授权。

`make session-image-acceptance NETWORKCLAW_IMAGE_TAG=<镜像> BUNDLE_OUTPUT=<已验证 bundle>` 使用镜像中的 Linux/amd64 Go、Web2 与原生 Hermes，验证无 Profile 创建、普通 turn、冻结 Skill、TLS 模型 Broker、会话关闭和凭证扫描。依赖本机可创建隔离数据库的 PostgreSQL 与 `redis-server`；`MODEL_ACCEPTANCE_PGADMIN` 可指定夹具管理员。数据库、Redis、容器和临时目录由 runner 清理，运行时不挂载业务源码。Docker Desktop 宿主依赖连接与完整 Compose/Kubernetes 集群部署是不同验证范围。

镜像 manifest 分别记录 Ubuntu 编译宿主与打包宿主，并校验 prepared context 的 bundle 身份及全部文件 hash。`customized=true` 的交付调试制品不能据此宣称为 clean publishable release。镜像漏洞扫描与凭证扫描结果分别记录。

交付镜像默认 `HERMES_DISABLE_LAZY_INSTALLS=1`，缺失的可选依赖不会在客户运行路径在线安装。Docker Desktop amd64 仿真验收为同步 HTTP 设置 180 秒写超时；socket 使用容器 tmpfs，workspace/SessionDB 使用独立 bind 目录，避免宿主文件共享不支持 Unix socket。该超时属于验收部署配置，不改变业务 turn 的冻结预算。
