#!/usr/bin/env python3
"""Build reproducible Linux/amd64 Go artifacts and an offline OCI image."""
from __future__ import annotations
import hashlib, json, os, platform, runpy, shutil, subprocess, tarfile, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
import sys
sys.path.insert(0, str(ROOT / "tools"))

NETWORKCLAW = Path(os.environ.get("NETWORKCLAW_PATH", ROOT / "../NetworkClaw")).resolve()
HARNESS = Path(os.environ.get("HARNESS_PATH", ROOT / "../networkclaw-harness")).resolve()
WHEELHOUSE = Path(os.environ.get("CI_WHEELHOUSE", HARNESS / "offline/wheels")).resolve()
BUNDLE = Path(os.environ.get("BUNDLE_OUTPUT", ROOT / ".integration-state/artifacts/networkclaw-bundle.tar.gz")).resolve()
OUT = ROOT / ".integration-state/artifacts/ubuntu-22.04-linux-amd64"
BASE_IMAGE = "python:3.12-slim-bookworm"
BASE_IMAGE_REF = os.environ.get(
    "BASE_IMAGE",
    "python:3.12-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e",
)

def run(command, **kwargs):
    subprocess.run(command, check=True, **kwargs)

def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""): h.update(chunk)
    return h.hexdigest()


def extract_build_input(archive: Path, destination: Path) -> tuple[Path, dict]:
    """Verify all payload hashes and safe paths before consuming bundle sources."""
    verifier = runpy.run_path(str(ROOT / "tools/verify-bundle.py"))
    verifier["verify"](archive, None)
    with tarfile.open(archive, "r:gz") as bundle:
        bundle.extractall(destination, filter="data")
    root = destination / "networkclaw-bundle"
    manifest = json.loads((root / "manifest/bundle-manifest.json").read_text())
    if manifest["target"] != {"os": "ubuntu", "version": "22.04", "architecture": "amd64"}:
        raise ValueError("image requires an Ubuntu 22.04 amd64 bundle")
    return root, manifest


def host_identity() -> dict[str, str]:
    system = platform.system().lower()
    version = platform.release()
    if system == "linux":
        os_release = Path("/etc/os-release")
        if os_release.is_file():
            values = dict(line.split("=", 1) for line in os_release.read_text(encoding="utf-8").splitlines() if "=" in line)
            system = values.get("ID", system).strip('"')
            version = values.get("VERSION_ID", version).strip('"')
    elif system == "darwin":
        version = platform.mac_ver()[0] or version
    return {"os": system, "version": version}

def prepare_context(stage: Path, bundle_root: Path, source_data: dict) -> Path:
    networkclaw = bundle_root / source_data["networkclaw"]["path"]
    harness = bundle_root / source_data["harness"]["path"]
    integration = bundle_root / source_data["integration"]["path"]
    env = os.environ | {"GOOS": "linux", "GOARCH": "amd64", "CGO_ENABLED": "0"}
    run(["make", "-C", str(networkclaw), "build-coordinator", f"BIN_DIR={stage / 'bin'}"], env=env)
    run(["go", "build", "-o", str(stage / "bin/web2-server"), str(integration / "tools/web2-server/main.go")],
        env=env | {"GO111MODULE": "off"})
    context = stage / "context"
    (context / "bin").mkdir(parents=True)
    web_source = networkclaw / "web2"
    web_build = stage / "web2"
    shutil.copytree(web_source, web_build, ignore=shutil.ignore_patterns(".env", ".env.*", "node_modules", "dist"))
    run(["npm", "ci"], cwd=web_build)
    run(["npm", "run", "build"], cwd=web_build)
    shutil.copytree(web_build / "dist", context / "web2/dist")
    shutil.copytree(harness, context / "harness", ignore=shutil.ignore_patterns(".git", ".venv", "__pycache__", "*.pyc"))
    release = integration / "release"
    if not release.is_dir():
        raise ValueError("image requires bundled frozen capability release")
    shutil.copytree(release, context / "release")
    image_wheels = context / "harness/offline/wheels"
    image_wheels.mkdir(parents=True, exist_ok=True)
    for wheel in sorted(WHEELHOUSE.glob("*.whl")):
        shutil.copy2(wheel, image_wheels / wheel.name)
    shutil.copytree(stage / "bin", context / "bin", dirs_exist_ok=True)
    shutil.copy2(integration / "ci/ubuntu-22.04/Dockerfile", context / "Dockerfile")
    shutil.copy2(integration / "ci/ubuntu-22.04/harness-entrypoint", context / "harness-entrypoint")
    return context


def context_files(context: Path) -> dict[str, str]:
    return {path.relative_to(context).as_posix(): sha(path) for path in sorted(context.rglob("*")) if path.is_file()}


def load_prepared_context(context: Path, bundle_hash: str) -> dict:
    identity = json.loads(context.with_suffix(".identity.json").read_text())
    if identity["bundle_sha256"] != bundle_hash or identity["files"] != context_files(context):
        raise ValueError("prepared image context identity mismatch")
    return identity["builder"]


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="networkclaw-linux-amd64-") as td:
        stage = Path(td)
        bundle_root, bundle_manifest = extract_build_input(BUNDLE, stage / "input")
        source_data = bundle_manifest["sources"]
        networkclaw = bundle_root / source_data["networkclaw"]["path"]
        harness = bundle_root / source_data["harness"]["path"]
        integration = bundle_root / source_data["integration"]["path"]
        prepared = os.environ.get("CI_PREPARED_IMAGE_CONTEXT")
        if prepared:
            context = Path(prepared).resolve()
            builder = load_prepared_context(context, sha(BUNDLE))
        else:
            context = prepare_context(stage, bundle_root, source_data)
            builder = host_identity()
        if os.environ.get("CI_PREPARE_IMAGE_CONTEXT"):
            destination = Path(os.environ["CI_PREPARE_IMAGE_CONTEXT"]).resolve()
            shutil.copytree(context, destination)
            identity = {"bundle_sha256": sha(BUNDLE), "builder": builder, "files": context_files(destination)}
            destination.with_suffix(".identity.json").write_text(json.dumps(identity, indent=2) + "\n")
            print(json.dumps({"status": "prepared", "builder": builder, "bundle_sha256": identity["bundle_sha256"]}))
            return 0
        tag = os.environ.get("NETWORKCLAW_IMAGE_TAG", "networkclaw:ci-linux-amd64")
        source_data = bundle_manifest["sources"]
        bundle_sha = sha(BUNDLE) if BUNDLE.is_file() else None
        build_args = [
            "--build-arg", f"BASE_IMAGE={BASE_IMAGE_REF}",
            "--build-arg", f"SOURCE_COMMIT={source_data['networkclaw']['commit'] or 'unknown'}",
            "--build-arg", f"HARNESS_COMMIT={source_data['harness']['commit'] or 'unknown'}",
            "--build-arg", f"INTEGRATION_COMMIT={source_data['integration']['commit'] or 'unknown'}",
            "--build-arg", f"BUNDLE_SHA256={bundle_sha or 'unknown'}",
        ]
        if bundle_sha is None:
            raise RuntimeError(f"bundle is required before image build: {BUNDLE}")
        image = OUT / "networkclaw-linux-amd64.oci.tar"
        scan_image = OUT / "networkclaw-linux-amd64.docker.tar"
        builder_args = []
        if os.environ.get("BUILDX_BUILDER"):
            builder_args = ["--builder", os.environ["BUILDX_BUILDER"]]
        archive_format = "oci"
        try:
            run(["docker", "buildx", "build", *builder_args, "--platform=linux/amd64", "--network=none",
                 "--tag", tag, "--output", f"type=oci,dest={image}", *build_args, str(context)])
            # Trivy's --input mode consumes Docker archives, while the release
            # artifact remains OCI for registry-compatible distribution.
            run(["docker", "buildx", "build", *builder_args, "--platform=linux/amd64", "--network=none",
                 "--tag", tag, "--output", f"type=docker,dest={scan_image}", *build_args, str(context)])
        except subprocess.CalledProcessError:
            # Docker Desktop's default docker driver may lack the OCI exporter;
            # keep Mac validation usable while Ubuntu Buildx remains OCI-first.
            archive_format = "docker"
            run(["docker", "build", "--platform=linux/amd64", "--network=none", "-t", tag, *build_args, str(context)])
            with scan_image.open("wb") as output:
                run(["docker", "save", tag], stdout=output)
            shutil.copy2(scan_image, image)
        run(["docker", "load", "--input", str(scan_image)])
        archive_names = subprocess.check_output(["tar", "-tf", str(image)], text=True).splitlines()
        archive_format = "oci" if "oci-layout" in archive_names else "docker"
        base_inspect = json.loads(subprocess.check_output([
            "docker", "image", "inspect", BASE_IMAGE_REF, "--format", "{{json .RepoDigests}}"
        ], text=True))
        if not base_inspect:
            raise RuntimeError("base image has no immutable RepoDigest")
        manifest = {"schema_version": 1, "platform": "linux/amd64",
                    "builder": builder, "packager": host_identity(),
                    "runtime": {"base_image": BASE_IMAGE_REF, "os": "debian", "version": "12"},
                    "archive_format": archive_format,
                    "base_image_digests": base_inspect,
                    "bundle_sha256": bundle_sha,
                    "source_input": "verified_bundle",
                    "customized": bundle_manifest["customized"],
                    "capability_release": bundle_manifest["capability_release"],
                    "sources": source_data,
                    "image_archive": image.name, "image_sha256": sha(image),
                    "scan_archive": scan_image.name,
                    "binaries": {p.name: sha(p) for p in sorted((context / "bin").iterdir())}}
    (OUT / "build-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, sort_keys=True))
    return 0

if __name__ == "__main__": raise SystemExit(main())
