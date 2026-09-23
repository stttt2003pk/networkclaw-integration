# Bundle 交付

bundle 是由三个仓库组合生成的源码快照：

```text
networkclaw-bundle/
├── networkclaw/
├── networkclaw-harness/
├── integration/
├── ci/
├── deploy/
├── docs/
└── manifest/
```

生成的 bundle 不应包含 `.git`、本机绝对路径、未声明的本地 virtualenv 或客户之外的密钥。manifest 必须记录每个源码树的 hash；若源码来自 Git，再记录 commit；若工作树 dirty，再记录 dirty 状态和 diff hash。

bundle 验证必须在临时目录进行，不能偷偷读取原始三个仓库。验证目标是：源码测试、组合测试和目标镜像构建所需的输入都已包含或由明确的 CI 步骤提供。

