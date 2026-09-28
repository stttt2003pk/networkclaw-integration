# Docker 运行入口

I-08 生成的 combined image 包含 `lobby`、`chatrtmgr` 和 Harness Gateway runtime。`chatrtmgr` 以 `gateway` target 启动并按 `user_id` 管理 Gateway 进程。先设置 `IMAGE_REPOSITORY` 和含 `sha256:` 前缀的 `REGISTRY_DIGEST`；镜像默认 entrypoint 是 `chatrtmgr`，启动 lobby 时显式覆盖 entrypoint：

```bash
docker run --rm --name networkclaw-chatrtmgr \
  --entrypoint /opt/bin/chatrtmgr \
  --env-file ./runtime.env \
  -p 50052:50052 -p 9101:9101 \
  "$IMAGE_REPOSITORY@$REGISTRY_DIGEST"

docker run --rm --name networkclaw-lobby \
  --entrypoint /opt/bin/lobby \
  --env-file ./runtime.env \
  -p 8080:8080 -p 9100:9100 \
  "$IMAGE_REPOSITORY@$REGISTRY_DIGEST"
```

`runtime.env` 由部署人员在安全位置维护，不纳入源码包。它至少需要数据库、Redis、服务发现和 `ONGRID_JWT_SECRET` 配置；Harness 真实 provider 调用还需要 `OPENAI_API_KEY` 和允许的 `OPENAI_BASE_URL`。两个进程通常需要连接同一个 Compose/Kubernetes 网络中的依赖服务，因此单机联调优先使用 [`../compose/docker-compose.yml`](../compose/docker-compose.yml)。

不要使用未经 I-08/I-09 验证的镜像，也不要在运行时从源码重建镜像。OCI 归档的 SHA-256 不是 registry digest；推送后须记录并核对 registry digest。首装及数据库迁移优先按 [`docs/deployment.md`](../../docs/deployment.md) 使用 Helm 或 Compose。
