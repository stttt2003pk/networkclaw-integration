#!/usr/bin/env python3
"""Bring up a disposable NetworkClaw stack in an existing kind cluster."""

from __future__ import annotations

import argparse
import base64
import json
import os
import secrets
import shlex
import subprocess
import sys
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ACTIVE_CONTEXT = ""
NAMESPACE_RE = re.compile(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")


def run(command: list[str], *, input_text: str | None = None) -> str:
    if command[0] == "kubectl" and "--context" not in command and ACTIVE_CONTEXT:
        command = ["kubectl", "--context", ACTIVE_CONTEXT, *command[1:]]
    result = subprocess.run(
        command,
        input=input_text,
        text=True,
        capture_output=True,
    )
    if result.returncode:
        if result.stdout:
            print(result.stdout, file=sys.stderr, end="")
        if result.stderr:
            print(result.stderr, file=sys.stderr, end="")
        raise SystemExit(f"command failed ({result.returncode}): {shlex.join(command)}")
    return result.stdout


def image_parts(image: str) -> tuple[str, str, str | None]:
    if "@" in image:
        repository, digest = image.split("@", 1)
        return repository, "", digest
    last_slash = image.rfind("/")
    last_colon = image.rfind(":")
    if last_colon > last_slash:
        return image[:last_colon], image[last_colon + 1 :], None
    return image, "latest", None


def locate_networkclaw(explicit: str | None) -> Path:
    candidates = []
    if explicit:
        candidates.append(Path(explicit).expanduser())
    if os.environ.get("NETWORKCLAW_PATH"):
        candidates.append(Path(os.environ["NETWORKCLAW_PATH"]).expanduser())
    candidates.extend((ROOT.parent / "NetworkClaw", ROOT.parent / "networkclaw", ROOT / "networkclaw"))
    for candidate in candidates:
        migration_dir = candidate / "internal/lobby/database/migrations"
        if migration_dir.is_dir() and list(migration_dir.glob("*.up.sql")):
            return candidate.resolve()
    raise SystemExit("NetworkClaw migrations were not found; pass --networkclaw or set NETWORKCLAW_PATH")


def locate_migrations(networkclaw: Path) -> Path:
    return networkclaw / "internal/lobby/database/migrations"


def read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("export "):
            stripped = stripped[7:].lstrip()
        if "=" not in stripped:
            continue
        key, raw = stripped.split("=", 1)
        key = key.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            continue
        try:
            parsed = shlex.split(raw, comments=True, posix=True)
        except ValueError as error:
            raise SystemExit(f"invalid provider env file {path}: {error}") from error
        values[key] = parsed[0] if parsed else ""
    return values


def provider_env_path(explicit: str | None, networkclaw: Path) -> Path | None:
    raw = explicit or os.environ.get("NETWORKCLAW_PROVIDER_ENV_FILE")
    if raw:
        path = Path(raw).expanduser()
        if not path.is_file():
            raise SystemExit(f"provider env file does not exist: {path}")
        return path.resolve()
    default = networkclaw / ".env"
    return default.resolve() if default.is_file() else None


def quote(value: str) -> str:
    return json.dumps(value)


def apply_dependencies(namespace: str, postgres_image: str, redis_image: str, etcd_image: str) -> None:
    manifest = f"""\
apiVersion: apps/v1
kind: Deployment
metadata:
  name: postgres
  namespace: {namespace}
  labels: {{app: networkclaw-kind-dependency, component: postgres}}
spec:
  replicas: 1
  selector:
    matchLabels: {{app: networkclaw-kind-dependency, component: postgres}}
  template:
    metadata:
      labels: {{app: networkclaw-kind-dependency, component: postgres}}
    spec:
      containers:
        - name: postgres
          image: {quote(postgres_image)}
          imagePullPolicy: Never
          ports: [{{containerPort: 5432}}]
          env:
            - name: POSTGRES_USER
              value: ongrid
            - name: POSTGRES_DB
              value: ongrid
            - name: POSTGRES_PASSWORD
              valueFrom: {{secretKeyRef: {{name: networkclaw-runtime, key: ONGRID_DB_PASSWORD}}}}
          readinessProbe:
            exec: {{command: [pg_isready, -U, ongrid, -d, ongrid]}}
            periodSeconds: 2
          volumeMounts: [{{name: data, mountPath: /var/lib/postgresql/data}}]
      volumes: [{{name: data, emptyDir: {{}}}}]
---
apiVersion: v1
kind: Service
metadata:
  name: postgres
  namespace: {namespace}
spec:
  selector: {{app: networkclaw-kind-dependency, component: postgres}}
  ports: [{{name: postgres, port: 5432, targetPort: 5432}}]
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: redis
  namespace: {namespace}
  labels: {{app: networkclaw-kind-dependency, component: redis}}
spec:
  replicas: 1
  selector:
    matchLabels: {{app: networkclaw-kind-dependency, component: redis}}
  template:
    metadata:
      labels: {{app: networkclaw-kind-dependency, component: redis}}
    spec:
      containers:
        - name: redis
          image: {quote(redis_image)}
          imagePullPolicy: Never
          ports: [{{containerPort: 6379}}]
          readinessProbe:
            exec: {{command: [redis-cli, ping]}}
            periodSeconds: 2
---
apiVersion: v1
kind: Service
metadata:
  name: redis
  namespace: {namespace}
spec:
  selector: {{app: networkclaw-kind-dependency, component: redis}}
  ports: [{{name: redis, port: 6379, targetPort: 6379}}]
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: etcd
  namespace: {namespace}
  labels: {{app: networkclaw-kind-dependency, component: etcd}}
spec:
  replicas: 1
  selector:
    matchLabels: {{app: networkclaw-kind-dependency, component: etcd}}
  template:
    metadata:
      labels: {{app: networkclaw-kind-dependency, component: etcd}}
    spec:
      containers:
        - name: etcd
          image: {quote(etcd_image)}
          imagePullPolicy: Never
          command: [/usr/local/bin/etcd]
          args:
            - --name=etcd
            - --advertise-client-urls=http://etcd:2379
            - --listen-client-urls=http://0.0.0.0:2379
            - --initial-advertise-peer-urls=http://etcd:2380
            - --listen-peer-urls=http://0.0.0.0:2380
            - --initial-cluster=etcd=http://etcd:2380
            - --initial-cluster-state=new
            - --initial-cluster-token=networkclaw-kind
          ports:
            - name: client
              containerPort: 2379
            - name: peer
              containerPort: 2380
          readinessProbe:
            exec:
              command: [etcdctl, endpoint, health]
            periodSeconds: 2
            timeoutSeconds: 3
---
apiVersion: v1
kind: Service
metadata:
  name: etcd
  namespace: {namespace}
spec:
  selector: {{app: networkclaw-kind-dependency, component: etcd}}
  ports:
    - name: client
      port: 2379
      targetPort: client
    - name: peer
      port: 2380
      targetPort: peer
"""
    run(["kubectl", "apply", "-f", "-"], input_text=manifest)
    run(["kubectl", "-n", namespace, "rollout", "status", "deployment/postgres", "--timeout=180s"])
    run(["kubectl", "-n", namespace, "rollout", "status", "deployment/redis", "--timeout=180s"])
    run(["kubectl", "-n", namespace, "rollout", "status", "deployment/etcd", "--timeout=180s"])


def apply_migrations(namespace: str, migration_dir: Path, postgres_image: str) -> None:
    configmap = f"networkclaw-kind-migrations"
    run(["kubectl", "-n", namespace, "delete", "configmap", configmap, "--ignore-not-found"])
    command = ["kubectl", "-n", namespace, "create", "configmap", configmap]
    command.extend(f"--from-file={path.name}={path}" for path in sorted(migration_dir.glob("*.up.sql")))
    run(command)
    run(["kubectl", "-n", namespace, "delete", "job", "networkclaw-kind-migrate", "--ignore-not-found"])
    job = f"""\
apiVersion: batch/v1
kind: Job
metadata:
  name: networkclaw-kind-migrate
  namespace: {namespace}
spec:
  backoffLimit: 0
  template:
    spec:
      restartPolicy: Never
      containers:
        - name: migrate
          image: {quote(postgres_image)}
          imagePullPolicy: Never
          env:
            - name: PGPASSWORD
              valueFrom: {{secretKeyRef: {{name: networkclaw-runtime, key: ONGRID_DB_PASSWORD}}}}
          command: [/bin/sh, -ec]
          args:
            - |
              psql -X -v ON_ERROR_STOP=1 -h postgres -U ongrid -d ongrid -c \
                'CREATE TABLE IF NOT EXISTS networkclaw_kind_migrations (filename text PRIMARY KEY, sha256 text NOT NULL)'
              for migration in /migrations/*.up.sql; do
                name=${{migration##*/}}
                case "$name" in *[!a-zA-Z0-9_.-]*) echo "invalid migration filename" >&2; exit 1;; esac
                digest=$(sha256sum "$migration" | cut -d ' ' -f1)
                applied=$(psql -X -v ON_ERROR_STOP=1 -At -h postgres -U ongrid -d ongrid -c \
                  "SELECT sha256 FROM networkclaw_kind_migrations WHERE filename = '$name'")
                if [ -n "$applied" ]; then
                  if [ "$applied" != "$digest" ]; then
                    echo "migration changed after application: $name" >&2
                    exit 1
                  fi
                  echo "already applied: $name"
                  continue
                fi
                echo "applying: $name"
                psql -X -v ON_ERROR_STOP=1 -1 -h postgres -U ongrid -d ongrid -f "$migration" \
                  -c "INSERT INTO networkclaw_kind_migrations (filename, sha256) VALUES ('$name', '$digest')"
              done
          volumeMounts: [{{name: migrations, mountPath: /migrations, readOnly: true}}]
      volumes: [{{name: migrations, configMap: {{name: {configmap}}}}}]
"""
    run(["kubectl", "apply", "-f", "-"], input_text=job)
    try:
        run(["kubectl", "-n", namespace, "wait", "--for=condition=complete", "job/networkclaw-kind-migrate", "--timeout=180s"])
    except SystemExit:
        print(run(["kubectl", "-n", namespace, "logs", "job/networkclaw-kind-migrate"]), file=sys.stderr, end="")
        raise


def apply_model_catalog_seed(namespace: str, postgres_image: str, provider_env: dict[str, str]) -> None:
    models = list(dict.fromkeys(item.strip() for item in (provider_env.get("OPENAI_MODELS") or provider_env.get("OPENAI_MODEL", "")).split(",") if item.strip()))
    if not models:
        return
    for model in models:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", model):
            raise SystemExit(f"invalid OPENAI_MODELS entry: {model!r}")
    statements = [
        "INSERT INTO catalog_models (id, provider, model_id, base_url, display_name, enabled, deployed) VALUES",
    ]
    rows = []
    for model in models:
        rows.append(f"    ('seed-openai-{model}', 'openai', '{model}', '', '{model}', true, true)")
    statements.append(",\n".join(rows) + "\nON CONFLICT (provider, model_id) DO NOTHING;")
    configured = ", ".join(f"'{model}'" for model in models)
    statements.append(f"UPDATE catalog_models SET deployed = false WHERE id LIKE 'seed-openai-%' AND model_id NOT IN ({configured});")
    sql = "\n".join(statements) + "\n"
    configmap = "networkclaw-kind-model-catalog"
    run(["kubectl", "-n", namespace, "delete", "configmap", configmap, "--ignore-not-found"])
    run(["kubectl", "-n", namespace, "create", "configmap", configmap, f"--from-literal=catalog.sql={sql}"])
    run(["kubectl", "-n", namespace, "delete", "job", "networkclaw-kind-model-catalog", "--ignore-not-found"])
    job = f"""\
apiVersion: batch/v1
kind: Job
metadata:
  name: networkclaw-kind-model-catalog
  namespace: {namespace}
spec:
  backoffLimit: 0
  template:
    spec:
      restartPolicy: Never
      containers:
        - name: seed-models
          image: {quote(postgres_image)}
          imagePullPolicy: Never
          env:
            - name: PGPASSWORD
              valueFrom: {{secretKeyRef: {{name: networkclaw-runtime, key: ONGRID_DB_PASSWORD}}}}
          command: [/bin/sh, -ec]
          args: ["psql -X -v ON_ERROR_STOP=1 -h postgres -U ongrid -d ongrid -f /seed/catalog.sql"]
          volumeMounts: [{{name: seed, mountPath: /seed, readOnly: true}}]
      volumes: [{{name: seed, configMap: {{name: {configmap}}}}}]
"""
    run(["kubectl", "apply", "-f", "-"], input_text=job)
    run(["kubectl", "-n", namespace, "wait", "--for=condition=complete", "job/networkclaw-kind-model-catalog", "--timeout=180s"])


def write_credentials(path: Path, values: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write("".join(f"{key}={value}\n" for key, value in values.items()))
    path.chmod(0o600)


def read_credentials(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.startswith("#"):
            key, value = line.split("=", 1)
            values[key] = value
    return values


def read_runtime_secret(namespace: str, key: str) -> str:
    try:
        output = run(["kubectl", "-n", namespace, "get", "secret", "networkclaw-runtime", "-o", "json"])
    except SystemExit:
        return ""
    try:
        encoded = json.loads(output).get("data", {}).get(key, "")
        return base64.b64decode(encoded).decode("utf-8") if encoded else ""
    except (ValueError, UnicodeDecodeError):
        return ""


def up(args: argparse.Namespace) -> None:
    networkclaw = locate_networkclaw(args.networkclaw)
    migration_dir = locate_migrations(networkclaw)
    env_path = provider_env_path(args.provider_env_file, networkclaw)
    provider_env = read_env_file(env_path) if env_path else {}
    for key in ("OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_MODEL", "OPENAI_MODELS", "NETWORKCLAW_HARNESS_ALLOWED_MODELS"):
        if os.environ.get(key):
            provider_env[key] = os.environ[key]
    repository, tag, digest = image_parts(args.image)
    if digest:
        raise SystemExit("--image digest is not supported for kind-up; use a local tagged image")
    for image in (args.image, args.postgres_image, args.redis_image, args.etcd_image):
        run(["docker", "image", "inspect", image])
        run(["kind", "load", "docker-image", image, "--name", args.cluster])

    namespace = args.namespace
    run(["kubectl", "--context", args.context, "apply", "-f", "-"], input_text=f"apiVersion: v1\nkind: Namespace\nmetadata:\n  name: {namespace}\n")
    credentials_path = Path(args.credentials).expanduser()
    old_credentials = read_credentials(credentials_path)
    db_password = os.environ.get("NETWORKCLAW_KIND_DB_PASSWORD") or old_credentials.get("NETWORKCLAW_KIND_DB_PASSWORD") or read_runtime_secret(namespace, "ONGRID_DB_PASSWORD") or secrets.token_urlsafe(24)
    jwt_secret = os.environ.get("NETWORKCLAW_KIND_JWT_SECRET") or old_credentials.get("NETWORKCLAW_KIND_JWT_SECRET") or read_runtime_secret(namespace, "ONGRID_JWT_SECRET") or secrets.token_urlsafe(32)
    oidc_secret = os.environ.get("NETWORKCLAW_KIND_OIDC_SECRET") or old_credentials.get("NETWORKCLAW_KIND_OIDC_SECRET") or read_runtime_secret(namespace, "ONGRID_OIDC_SECRET_KEY") or secrets.token_urlsafe(32)
    seed_password = os.environ.get("NETWORKCLAW_KIND_SEED_ADMIN_PASSWORD") or "admin"
    for key in ("OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_MODEL", "OPENAI_MODELS", "NETWORKCLAW_HARNESS_ALLOWED_MODELS"):
        if not provider_env.get(key):
            provider_env[key] = read_runtime_secret(namespace, key)
    if not provider_env.get("NETWORKCLAW_HARNESS_ALLOWED_MODELS"):
        provider_env["NETWORKCLAW_HARNESS_ALLOWED_MODELS"] = provider_env.get("OPENAI_MODELS") or provider_env.get("OPENAI_MODEL", "")
    credentials = {
        "NETWORKCLAW_SMOKE_EMAIL": args.seed_admin_email,
        "NETWORKCLAW_SMOKE_PASSWORD": seed_password,
        "NETWORKCLAW_KIND_NAMESPACE": namespace,
    }
    secret_manifest = f"""\
apiVersion: v1
kind: Secret
metadata:
  name: networkclaw-runtime
  namespace: {namespace}
type: Opaque
stringData:
  ONGRID_DB_PASSWORD: {quote(db_password)}
  ONGRID_JWT_SECRET: {quote(jwt_secret)}
  ONGRID_OIDC_SECRET_KEY: {quote(oidc_secret)}
  ONGRID_SEED_ADMIN_PASSWORD: {quote(seed_password)}
  OPENAI_API_KEY: {quote(provider_env.get("OPENAI_API_KEY", ""))}
  OPENAI_BASE_URL: {quote(provider_env.get("OPENAI_BASE_URL", ""))}
  OPENAI_MODEL: {quote(provider_env.get("OPENAI_MODEL", ""))}
  OPENAI_MODELS: {quote(provider_env.get("OPENAI_MODELS", ""))}
  NETWORKCLAW_HARNESS_ALLOWED_MODELS: {quote(provider_env.get("NETWORKCLAW_HARNESS_ALLOWED_MODELS", ""))}
"""
    run(["kubectl", "--context", args.context, "apply", "-f", "-"], input_text=secret_manifest)
    apply_dependencies(namespace, args.postgres_image, args.redis_image, args.etcd_image)
    apply_migrations(namespace, migration_dir, args.postgres_image)
    apply_model_catalog_seed(namespace, args.postgres_image, provider_env)
    helm = [
        "helm", "upgrade", "--install", args.release, str(ROOT / "deploy/helm/networkclaw-bundle"),
        "--kube-context", args.context, "--namespace", namespace,
        "--set-string", f"image.repository={repository}", "--set-string", f"image.tag={tag}",
        "--set", "image.pullPolicy=Never", "--set", "secrets.existingSecret=networkclaw-runtime",
        "--set-string", "database.host=postgres", "--set-string", "redis.address=redis:6379",
        "--set", "replicas.lobby=2", "--set", "replicas.chatrtmgr=2",
        "--set-string", "discovery.type=etcd", "--set-string", "discovery.etcdEndpoints=etcd:2379",
        "--set-string", f"auth.seedAdminEmail={args.seed_admin_email}",
        "--set-string", "auth.seedAdminPasswordSecretKey=ONGRID_SEED_ADMIN_PASSWORD",
        "--set", "ingress.enabled=true", "--set-string", "ingress.host=networkclaw.localhost",
        "--set-string", "auth.webOrigins=http://networkclaw.localhost:8081",
        "--wait", "--timeout", "180s",
    ]
    run(helm)
    run(["kubectl", "--context", args.context, "-n", namespace, "rollout", "status", f"deployment/{args.release}-networkclaw-bundle-lobby", "--timeout=180s"])
    run(["kubectl", "--context", args.context, "-n", namespace, "rollout", "status", f"deployment/{args.release}-networkclaw-bundle-chatrtmgr", "--timeout=180s"])
    run(["kubectl", "--context", args.context, "-n", namespace, "rollout", "status", f"deployment/{args.release}-networkclaw-bundle-web2", "--timeout=180s"])
    write_credentials(credentials_path, credentials)
    lobby_service = f"{args.release}-networkclaw-bundle-lobby"
    print(f"namespace={namespace}")
    print(f"image={args.image}")
    print(f"credentials_file={credentials_path.resolve()}")
    if env_path:
        print(f"provider_env_file={env_path}")
    print(f"port_forward=kubectl --context {args.context} -n {namespace} port-forward svc/{lobby_service} 8080:8080 9100:9100")
    print(f"ingress_port_forward=kubectl --context {args.context} -n ingress-nginx port-forward svc/ingress-nginx-controller 8081:80")
    print("web2=http://networkclaw.localhost:8081/")
    print(f"smoke=python3 tools/deployment_smoke.py --url http://127.0.0.1:8080 --metrics-url http://127.0.0.1:9100 --session")
    print(f"status=kubectl --context {args.context} -n {namespace} get pods,job")


def down(args: argparse.Namespace) -> None:
    if not NAMESPACE_RE.fullmatch(args.namespace) or args.namespace in {"default", "kube-system", "kube-public", "kube-node-lease", "ongrid"}:
        raise SystemExit(f"refusing to delete protected namespace: {args.namespace!r}")
    run(["helm", "uninstall", args.release, "--kube-context", args.context, "--namespace", args.namespace, "--ignore-not-found"])
    run(["kubectl", "--context", args.context, "delete", "namespace", args.namespace, "--ignore-not-found", "--wait=true", "--timeout=120s"])
    print(f"removed namespace={args.namespace}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("up", "down"), nargs="?", default="up")
    parser.add_argument("--context", default=os.environ.get("KUBE_CONTEXT", "kind-ongrid"))
    parser.add_argument("--cluster", default=os.environ.get("KIND_CLUSTER"))
    parser.add_argument("--namespace", default=os.environ.get("NETWORKCLAW_KIND_NAMESPACE", "networkclaw-manual"))
    parser.add_argument("--release", default="networkclaw-manual")
    parser.add_argument("--image", default=os.environ.get("NETWORKCLAW_KIND_IMAGE", "networkclaw:ci-linux-amd64"))
    parser.add_argument("--postgres-image", default="postgres:16-alpine")
    parser.add_argument("--redis-image", default="redis:7.0.5")
    parser.add_argument("--etcd-image", default="quay.io/coreos/etcd:v3.5.5")
    parser.add_argument("--networkclaw", help="NetworkClaw repository containing internal/lobby/database/migrations")
    parser.add_argument("--provider-env-file", help="local env file for provider settings; defaults to NetworkClaw .env")
    parser.add_argument("--seed-admin-email", default=os.environ.get("NETWORKCLAW_KIND_SEED_ADMIN_EMAIL", "admin"))
    parser.add_argument("--credentials", default=str(ROOT / ".integration-state/kind/manual-credentials.env"))
    args = parser.parse_args()
    if not NAMESPACE_RE.fullmatch(args.namespace):
        raise SystemExit(f"namespace must be a DNS label: {args.namespace!r}")
    if args.action == "up" and args.namespace in {"default", "kube-system", "kube-public", "kube-node-lease", "ongrid"}:
        raise SystemExit(f"refusing to deploy disposable stack into protected namespace: {args.namespace!r}")
    if not args.cluster:
        if args.context.startswith("kind-") and len(args.context) > len("kind-"):
            args.cluster = args.context.removeprefix("kind-")
        else:
            raise SystemExit("--cluster is required when --context is not a kind-* context")
    if args.context != f"kind-{args.cluster}":
        raise SystemExit("kind tool requires --context kind-<cluster> matching --cluster")
    global ACTIVE_CONTEXT
    ACTIVE_CONTEXT = args.context
    if args.action == "up":
        up(args)
    else:
        down(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
