# Bundle 交付

`networkclaw-bundle.tar.gz` 是由 NetworkClaw、Harness 和 Integration 三个独立源码树生成的交付快照，不是第四个长期维护仓库。归档内容位于 `networkclaw-bundle/` 下，包含三个源码目录与 `manifest/bundle-manifest.json`；Integration 源码中会带入 CI、部署、脚本、测试和文档等已纳入版本控制或未忽略的文件。

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

`verify-bundle` 证明 bundle 内部内容和 provenance 记录一致，不证明脱离原工作区后的源码测试或镜像构建可成功；后者属于 I-07 / I-08。
