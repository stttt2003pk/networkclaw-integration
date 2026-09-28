# NetworkClaw Bundle Helm Chart

客户 Kubernetes 首装入口。Chart 消费同一 combined image，分别运行 `web2`、`lobby` 和 `chatrtmgr`；后者以 `target=gateway` 按用户亲和启动 Harness Gateway，并通过 UDS + JSONL 承接 session。Ingress 将 `/` 交给 web2，web2 将 `/api`、`/ws` 转发到 Lobby。默认使用 Kubernetes Service/Endpoints 做发现；设置 `discovery.type=etcd`、`discovery.etcdEndpoints` 和 `discovery.etcdPrefix` 可切换到 etcd 注册/发现。详细步骤和排障见 [`docs/deployment.md`](../../../docs/deployment.md)。

## 前置

- PostgreSQL 和 Redis 已准备并可从 Pod 访问。默认用 Kubernetes Endpoints 发现 chatrtmgr；etcd 模式还需要平台或独立基础设施提供 `etcd:2379`。
- 从交付 bundle 的 `networkclaw/internal/lobby/database/migrations/*.up.sql` 按文件名顺序迁移数据库，使用 `psql -X -v ON_ERROR_STOP=1`，失败即停止。应用启动不会自动迁移。
- 在目标 namespace 预先创建 `networkclaw-runtime` Secret，至少包含 `ONGRID_DB_PASSWORD`、`ONGRID_JWT_SECRET`、`ONGRID_OIDC_SECRET_KEY`。Redis 启用密码时增加 `ONGRID_REDIS_PASSWORD`；真实 provider 调用时增加 `OPENAI_API_KEY`。用客户 Secret 管理器或权限受控的本地文件创建，不把值写进 Helm values、shell 命令参数或 Git。
- 若 registry 私有，提前创建 imagePullSecret，并通过 `image.pullSecrets` 引用。`image.digest` 是推送到客户 registry 后读取的 digest，不是 build manifest 中 OCI 归档的 SHA-256。

## 首次安装

根据环境覆盖 `image.repository`、`image.digest`、`database.*`、`redis.address`、`auth.webOrigins`、`secrets.existingSecret`。先设置 `IMAGE_REPOSITORY`、`REGISTRY_DIGEST`（含 `sha256:` 前缀）、`POSTGRES_HOST`、`REDIS_ADDRESS`、`WEB_ORIGIN`；例如：

```bash
helm lint deploy/helm/networkclaw-bundle
helm upgrade --install networkclaw deploy/helm/networkclaw-bundle \
  -n networkclaw --create-namespace --wait \
  --set-string image.repository="$IMAGE_REPOSITORY" \
  --set-string image.digest="$REGISTRY_DIGEST" \
  --set-string database.host="$POSTGRES_HOST" \
  --set-string redis.address="$REDIS_ADDRESS" \
  --set-string auth.webOrigins="$WEB_ORIGIN" \
  --set secrets.existingSecret=networkclaw-runtime
```

`lobby` 仅有读取本 namespace Endpoints 的权限；`chatrtmgr` 和 `web2` 不挂 API token。lobby 与 web2 使用 HTTP `/readyz`、`/healthz`，chatrtmgr 使用 gRPC health probe。默认 `chatrtmgr` 的 workspace 为 `emptyDir`，Pod 替换会丢失本地状态；需要保留时设置 `harness.existingClaim`，并按 PVC 访问模式规划副本。

分布式 etcd 模式至少运行两个副本时：

```bash
helm upgrade --install networkclaw deploy/helm/networkclaw-bundle \
  -n networkclaw --create-namespace --wait \
  --set replicas.lobby=2 --set replicas.chatrtmgr=2 \
  --set discovery.type=etcd \
  --set-string discovery.etcdEndpoints=etcd:2379 \
  --set-string discovery.etcdPrefix=/services
```

本 chart 不创建 etcd；kind 手动验收工具会在临时 namespace 创建单节点 etcd。

## 验证和排障

```bash
kubectl -n networkclaw get pods -l app.kubernetes.io/part-of=networkclaw-bundle
kubectl -n networkclaw logs deploy/networkclaw-networkclaw-bundle-lobby --all-containers
kubectl -n networkclaw logs deploy/networkclaw-networkclaw-bundle-chatrtmgr --all-containers
python3 tools/collect_k8s_diagnostics.py --namespace networkclaw --output ./diagnostics
```

仅 Pod ready 不代表 Harness 已处理启动请求。启用 `ingress.enabled=true` 并设置 `ingress.host` 后，浏览器访问该域名；无 Ingress 时可转发 web2 Service 的 5174 端口。使用 `tools/deployment_smoke.py --session` 创建并关闭测试 Session，确认 manager/service binding；凭据由 `NETWORKCLAW_SMOKE_*` 环境变量提供。当前非生产范围不建设独立灰度、自动回滚或 systemd 部署系统。
