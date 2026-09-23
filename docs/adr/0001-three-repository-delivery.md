# ADR-0001：三仓库组合交付模型

## 状态

已接受，作为 integration 仓库的初始架构基线。

## 背景

NetworkClaw Go 后台、Python Harness/Hermes runtime 和构建部署工具由不同职责团队维护。客户希望分别维护两个源码仓库，同时获得本地联合调试、CI、镜像构建、部署和后续 vendor 升级能力。

如果只交付两个源码仓库，客户还需要自行解决路径、启动顺序、协议联调、故障注入、bundle 和 CI。若建立第四个长期 bundle 源码仓库，又会产生源码权威和同步分叉问题。

## 决策

长期维护三个仓库：

1. `networkclaw`：Go 后台及其测试。
2. `networkclaw-harness`：Python Harness、Hermes vendor、同步/校验和 Python 测试。
3. `networkclaw-integration`：组合工作区、跨仓库测试、CI、bundle、镜像和部署输入。

`networkclaw-bundle` 是 integration 的不可变源码交付产物，不是第四个日常开发仓库。可以将 bundle 压缩包、manifest 和校验文件存入客户制品库或归档系统。

本地模式读取两个真实源码工作树，允许调试未提交修改；CI/发布模式使用 lock 文件 checkout 固定组合。两种模式共享高层测试和构建入口。

## 结果

- 客户可以分别演进 Go、Harness 和 integration。
- 本地 Mac 支持 IDE/debugger 和真实跨进程联调。
- Ubuntu 22.04 Linux/amd64 CI 负责最终镜像和部署制品。
- vendor 更新在 Harness 仓库完成，integration 负责组合验证。
- bundle 脱离原始 Git 和绝对路径后仍应能够测试和构建。
- manifest 记录源码树身份、vendor 来源、协议和目标平台；Git commit 是 provenance，不是无 Git 源码包的硬前置条件。

## 不采用的方案

- 不在 integration 复制 NetworkClaw/Harness 业务源码作为第三份长期副本。
- 不在 integration 重写 Hermes Agent loop、Go 路由或 SessionDB 事实管理。
- 不把 bundle 作为第四个长期维护的源码仓库。

## 验收门槛

在实现完成前，必须证明：

```text
三个独立仓库
  -> Mac 本地 bootstrap / 联调
  -> 跨进程测试
  -> bundle 生成
  -> 删除 .git 和原始路径依赖后重新测试
  -> Ubuntu 22.04 CI 构建 Linux/amd64 image
```

