# NetworkClaw 首次部署与调试

客户主要使用 Kubernetes。首选 [`deploy/helm/networkclaw-bundle`](../deploy/helm/networkclaw-bundle/)；Docker Compose 是独立的容器栈，宿主机源码全栈联调使用 [`docs/local-development.md`](local-development.md) 的 `make dev-up`。

## 部署输入

I-08 `build-manifest.json` 记录 Linux/amd64 OCI 归档的 SHA-256、bundle SHA-256 和三个源码树身份，**不记录客户 registry digest**。先核对归档 SHA-256 与 manifest 中的 `image_sha256`，再将归档推送到客户 registry；推送后从 registry 读取 digest，核对拉回的镜像内容与已验证归档，并以 `repository@sha256:...` 部署。不要把归档 SHA-256、Docker 本地 image ID 和 registry digest 混为一谈。若镜像内容在重打标或推送时改变，重新验收镜像。

I-08 同时生成同一构建输入的 Docker archive（manifest 的 `scan_archive`）。可按客户 registry 流程装载、推送和核对；先设置 `IMAGE_REPOSITORY`、`OCI_ARCHIVE`、`DOCKER_ARCHIVE` 为该次构建对应的值。推送后从输出中记录含 `sha256:` 前缀的 `REGISTRY_DIGEST`：

```bash
# 核对 shasum -a 256 "$OCI_ARCHIVE" 与 build-manifest.json 的 image_sha256 相同。
docker load -i "$DOCKER_ARCHIVE"
docker image inspect networkclaw:ci-linux-amd64 --format '{{.Id}} {{json .Config.Labels}}'
docker tag networkclaw:ci-linux-amd64 "$IMAGE_REPOSITORY:ci-linux-amd64"
docker push "$IMAGE_REPOSITORY:ci-linux-amd64"
docker buildx imagetools inspect "$IMAGE_REPOSITORY:ci-linux-amd64"  # 记录 registry 返回的 sha256 digest 为 REGISTRY_DIGEST
docker pull --platform linux/amd64 "$IMAGE_REPOSITORY@$REGISTRY_DIGEST"
docker image inspect "$IMAGE_REPOSITORY@$REGISTRY_DIGEST" --format '{{.Id}} {{json .Config.Labels}}'
```

拉回的 Linux/amd64 image ID 和来源标签须与推送前一致；再用 registry digest 替代 Helm 的 `image.digest`。若 registry 重写镜像导致 ID/标签不一致，不把该 digest 作为已验证输入。`DOCKER_ARCHIVE` 与 OCI 归档是两个文件，不能拿 OCI 归档的 SHA-256 充当 Docker archive 校验值。

交付输入还包括 source bundle 中 `networkclaw/internal/lobby/database/migrations/*.up.sql`。镜像不会自动迁移数据库；首次安装前由部署人员在受控连接上按文件名顺序执行，失败即停止：

```bash
# psql 连接和密码由客户的 Secret 管理方式提供；不要将密码写入命令行。
for migration in networkclaw/internal/lobby/database/migrations/*.up.sql; do
  psql -X -v ON_ERROR_STOP=1 -f "$migration" || exit 1
done
```

执行后检查 `sessions`、`users`、`harness_run_admissions` 等表存在。`psql` 所用账号须有对应 DDL 权限，应用账号可使用较低权限。首次部署前还要确认 PostgreSQL、Redis 地址可达，按 chart README 创建 Secret，并配置 `image.pullSecrets`（私有 registry 时）、`auth.webOrigins`（实际 UI/烟测 Origin）及可选 Ingress。

## Kubernetes 首装

同一 combined image 内含 web2 生产构建、Go 后台和 Harness。`web2` 以 `/opt/bin/web2-server` 启动，提供静态页面并将 `/api`、`/ws` 转发到 Lobby；`lobby` 以 `/opt/bin/lobby` 启动；`chatrtmgr` 以 `/opt/bin/chatrtmgr` 启动并按用户亲和管理 Harness Gateway。Ingress 的 `/` 指向 web2 Service，浏览器只需访问一个域名。Chart 用 Kubernetes Endpoints 做发现，因此此部署路径**不需要 etcd**。默认一个 chatrtmgr Pod，`/tmp/ongrid` 使用 `emptyDir`，Pod 替换会丢失本地 Session workspace；需跨 Pod 保留时设置 `harness.existingClaim`，并按存储访问模式规划副本数。

```bash
helm lint deploy/helm/networkclaw-bundle
helm upgrade --install networkclaw deploy/helm/networkclaw-bundle \
  -n networkclaw --create-namespace --wait \
  --set-string image.repository="$IMAGE_REPOSITORY" \
  --set-string image.digest="$REGISTRY_DIGEST" \
  --set secrets.existingSecret=networkclaw-runtime \
  --set-string auth.webOrigins="$WEB_ORIGIN" \
  --set-string database.host="$POSTGRES_HOST" \
  --set-string redis.address="$REDIS_ADDRESS"
kubectl -n networkclaw get pods -l app.kubernetes.io/part-of=networkclaw-bundle
kubectl -n networkclaw rollout status deploy/networkclaw-networkclaw-bundle-chatrtmgr
kubectl -n networkclaw rollout status deploy/networkclaw-networkclaw-bundle-lobby
kubectl -n networkclaw rollout status deploy/networkclaw-networkclaw-bundle-web2
```

启用 Ingress 时设置 `ingress.enabled=true`、`ingress.host` 和 `auth.webOrigins` 为实际浏览器 Origin。无 Ingress 的本地调试可在独立终端执行 `kubectl -n networkclaw port-forward svc/networkclaw-networkclaw-bundle-web2 5174:5174`，随后在浏览器打开 `http://localhost:5174/`；API 通过同一地址转发。若需直接检查 Lobby metrics，可另行转发其 9100 端口。

```bash
python3 tools/deployment_smoke.py --url http://127.0.0.1:5174
# 要证明 Go -> chatrtmgr -> Harness Gateway 启动链路，再提供专用烟测账号：
python3 tools/deployment_smoke.py --url http://127.0.0.1:5174 \
  --session --origin https://networkclaw.example.com
```

`--session` 从 `NETWORKCLAW_SMOKE_ACCESS_TOKEN` 或 `NETWORKCLAW_SMOKE_EMAIL/PASSWORD` 读取凭据，创建并关闭测试 Session，检查 manager/service binding，不发起真实模型请求。凭据不写入报告；建议由 Secret 管理器注入环境。`healthz`/`readyz`/metrics 和 TCP 端口仅是基础检查，不能单独证明 Harness 参与了业务链路。
如果创建请求超时，客户端可能拿不到 Session ID；在部署侧检查是否留有 `deployment-smoke` 测试 Session 并清理。

## Docker Compose 首装

Compose 需要相邻的 `networkclaw` 源码树中的迁移文件，不复制业务源码；若源码目录叫 `NetworkClaw` 或在其他位置，设置 `NETWORKCLAW_MIGRATIONS_DIR` 为迁移目录的绝对路径。若使用解包 bundle，在 `integration/` 目录运行即可。一次性 `migrate` 服务成功执行后才启动 lobby。

```bash
# 默认读取相邻 NetworkClaw/.env；也可设置 NETWORKCLAW_PROVIDER_ENV_FILE 指定未提交的本地 env。
make compose-up
make compose-status
python3 tools/deployment_smoke.py --url http://127.0.0.1:5174 \
  --metrics-url http://127.0.0.1:9100 --chatrtmgr 127.0.0.1:50052
```

`make compose-up` 每次都会先关闭已有 Compose 栈，再从当前源码重建 bundle、Go/Web 产物和 Linux/amd64 镜像，最后启动并等待健康状态。只有显式设置 `NETWORKCLAW_REBUILD=0` 才跳过重建；旧栈仍会先关闭。

Compose 在 `http://localhost:5174/` 直接提供前端，不使用 Ingress；默认本地种子账号为 `admin` / `admin`。将对应值注入 `NETWORKCLAW_SMOKE_EMAIL/PASSWORD` 后可加 `--session`。客户环境应通过环境变量覆盖本地默认账号。停止使用 `make compose-down`，默认保留 PostgreSQL 数据卷；只有明确需要清理测试数据时才直接执行带 `-v` 的 Compose 命令。

## 本地 kind 手动验收

首次启动可从相邻 NetworkClaw 的未提交 `.env` 导入模型；也可用 `NETWORKCLAW_PROVIDER_ENV_FILE=.env.kind make kind-up` 指定。工具经管理员 API 将连接、模型与凭证写入 Lobby，已有配置时跳过导入。provider 环境变量不传给 chatrtmgr 或 Gateway；后续修改使用管理员模型页面。Lobby 与 chatrtmgr 使用挂载 Secret 中的 Bearer token 和 TLS 证书同步私有 snapshot，每 30 秒拉取，超过 5 分钟未成功确认则拒绝新轮次。生产应提供与 Lobby Service DNS 匹配的受信证书；本地工具生成临时证书。凭证不进入 Helm values、公共模型目录或 bundle。请勿将真实凭据写入 Git、命令参数或生成清单。

已有本地 kind 集群和 ingress-nginx controller 时，可用 Integration 工具在独立 namespace 启动分布式验收拓扑。默认使用 `kind-ongrid` context、`networkclaw:ci-linux-amd64` 本地镜像，并从相邻 `NetworkClaw` 工作树读取 migration；可用 `--context`、`--cluster`、`--image`、`--networkclaw` 覆盖。工具会先加载镜像，在 namespace 内创建临时 PostgreSQL、Redis、单节点 etcd，提交并等待 migration Job 完成，然后以 etcd 发现安装 **2 个 lobby、2 个 chatrtmgr 和 1 个 web2**，Ingress 的 `/` 指向 web2。每个 chatrtmgr 通过 Pod IP 向 `/services` 注册；生成的 smoke 登录凭据保存在 `.integration-state/kind/manual-credentials.env`（权限 `0600`）：

```bash
make kind-up
kubectl --context kind-ongrid -n ingress-nginx port-forward \
  svc/ingress-nginx-controller 8081:80
```

`make kind-up` 每次都会先卸载本工具管理的 release 和 namespace，再重建并加载当前镜像，重新应用依赖、数据库迁移和模型目录 seed，最后重新安装 Helm release 并等待 rollout。设置 `NETWORKCLAW_REBUILD=0` 可复用已有镜像，但不会跳过清理、迁移或 rollout。

保持 port-forward 运行即可从浏览器访问 `http://networkclaw.localhost:8081/`，入口经过 Ingress 和 web2。kind 本地默认种子账号为 `admin` / `admin`；另开终端运行完整 smoke：

```bash
set -a
. .integration-state/kind/manual-credentials.env
set +a
python3 tools/deployment_smoke.py \
  --url http://networkclaw.localhost:8081 \
  --session --origin http://networkclaw.localhost:8081
```

如果需要直接检查 chatrtmgr 的 gRPC 端口，可另开终端转发 `50052:50052`；Session smoke 本身已经会验证 lobby 找到 chatrtmgr，并完成 Gateway binding。检查注册：

```bash
kubectl --context kind-ongrid -n networkclaw-manual exec deploy/etcd -- \
  etcdctl get /services --prefix --keys-only
```

验收完毕后执行 `make kind-down`，它会卸载 release 并删除整个 `networkclaw-manual` namespace，包括该 namespace 的临时数据库数据。工具拒绝删除 `default`、`ongrid` 和 Kubernetes 系统 namespace。不要把本地产生的 secret 文件提交。

## 排障

先看 Pod/容器状态和两侧日志，再核对镜像可拉取、Secret 键、迁移、PostgreSQL/Redis 连通、Endpoint RBAC、CSRF Origin 和 Harness workspace 写权限。`chatrtmgr` 的 gRPC probe 通过不代表 Gateway 已完成协议协商；`--session` 失败时检查 chatrtmgr 的 Gateway 日志和 Harness 启动错误。Kubernetes 诊断工具默认只收集名称、状态、副本数和端口，不读取 Secret、完整 Deployment YAML 或事件文本：

```bash
python3 tools/collect_k8s_diagnostics.py --namespace networkclaw --output ./diagnostics
# 多个 kube context 时显式指定目标 kind context：
python3 tools/collect_k8s_diagnostics.py --context kind-ongrid \
  --namespace networkclaw-manual --output ./diagnostics
```

`--include-logs` 会做常见凭据模式脱敏，但不能保证任意应用日志都无敏感数据；对外分享前必须人工审阅。镜像切换使用客户既有 Helm/Kubernetes 流程和另一份已验证 registry digest；本阶段不建设独立灰度或自动回滚系统。
