#!/usr/bin/env python3
"""Fail-closed bootstrap for the immutable Coze server and web runtime bundles."""

from __future__ import annotations

import hashlib
import json
import os
import pwd
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any

MANIFEST_SCHEMA_VERSION = 1
SOURCE_REF_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
BUILD_SOURCE_RE = re.compile(r"^BUILD_SOURCE-([0-9a-f]{40})\.json$")
MAX_ARTIFACT_BYTES = 10 * 1024 * 1024 * 1024
MAX_ARTIFACT_MEMBERS = 100_000
MAX_UNPACKED_BYTES = 16 * 1024 * 1024 * 1024
COMPONENTS = {
    "server": {
        "destination": Path("/app"),
        "required": Path("opencoze"),
        "artifact_prefix": "coze-server-app",
        "dockerfile": "backend/Dockerfile",
    },
    "web": {
        "destination": Path("/opt/coze-web"),
        "required": Path("index.html"),
        "artifact_prefix": "coze-web-dist",
        "dockerfile": "frontend/Dockerfile",
    },
}
UPSTREAM_REPOSITORY = "coze-dev/coze-studio"
WRAPPER_REPOSITORY = "BlueSkyXN/Coze-all-in-one-HFS"


class BootstrapError(RuntimeError):
    """Safe bootstrap failure that never exposes credential values."""


class SafeArtifactRedirect(urllib.request.HTTPRedirectHandler):
    """Follow only the HF Xet download redirect without forwarding credentials."""

    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> Any:
        target = urllib.parse.urlsplit(newurl)
        if target.scheme != "https" or target.hostname != "cas-bridge.xethub.hf.co":
            raise urllib.error.HTTPError(req.full_url, code, "artifact redirect target is not allowed", headers, fp)
        return urllib.request.Request(
            newurl,
            headers={"User-Agent": "coze-hfs-runtime-bootstrap/1"},
            method=req.get_method(),
        )


def require_https_url(value: str, field: str) -> urllib.parse.SplitResult:
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise BootstrapError(f"{field} must be a direct HTTPS URL without credentials, query, or fragment")
    return parsed


def manifest_artifact_url(manifest_url: str, artifact: str) -> str:
    parsed = require_https_url(manifest_url, "COZE_RUNTIME_MANIFEST_URI")
    if not parsed.path or parsed.path.endswith("/"):
        raise BootstrapError("COZE_RUNTIME_MANIFEST_URI must identify a manifest file")
    base = parsed._replace(path=parsed.path.rsplit("/", 1)[0] + "/")
    return urllib.parse.urlunsplit(base) + urllib.parse.quote(artifact, safe="._-")


def download(url: str, destination: Path, token: str) -> None:
    parsed = require_https_url(url, "runtime artifact URL")
    if token and parsed.hostname != "huggingface.co":
        raise BootstrapError("bearer-authenticated runtime downloads must use huggingface.co")
    headers = {"User-Agent": "coze-hfs-runtime-bootstrap/1"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    opener = urllib.request.build_opener(SafeArtifactRedirect())
    try:
        with opener.open(request, timeout=60) as response, destination.open("wb") as output:
            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > MAX_ARTIFACT_BYTES:
                raise BootstrapError("runtime download exceeds the maximum supported size")
            copied = 0
            while chunk := response.read(1024 * 1024):
                copied += len(chunk)
                if copied > MAX_ARTIFACT_BYTES:
                    raise BootstrapError("runtime download exceeds the maximum supported size")
                output.write(chunk)
    except urllib.error.HTTPError as exc:
        host = urllib.parse.urlsplit(exc.url).hostname or "unknown-host"
        raise BootstrapError(f"runtime download returned HTTP {exc.code} from {host}") from exc
    except (OSError, ValueError, urllib.error.URLError) as exc:
        if isinstance(exc, BootstrapError):
            raise
        raise BootstrapError(f"unable to download runtime input: {exc.__class__.__name__}") from exc


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def expected_artifact_name(component: str, source_ref: str) -> str:
    return f"{COMPONENTS[component]['artifact_prefix']}-{source_ref}.tar.gz"


def expected_build_source_name(source_ref: str) -> str:
    return f"BUILD_SOURCE-{source_ref}.json"


def validate_manifest(data: Any) -> tuple[str, list[dict[str, Any]], dict[str, str]]:
    if not isinstance(data, dict) or data.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise BootstrapError("runtime manifest has an unsupported schema version")
    if data.get("source_kind") != "commit":
        raise BootstrapError("runtime manifest source_kind must be commit")
    source_ref = data.get("source_ref")
    if not isinstance(source_ref, str) or not SOURCE_REF_RE.fullmatch(source_ref):
        raise BootstrapError("runtime manifest source_ref must be a full lowercase Git commit")
    if not isinstance(data.get("generated_at"), str) or not data["generated_at"]:
        raise BootstrapError("runtime manifest must record generated_at")
    build_source = data.get("build_source")
    build_source_sha256 = data.get("build_source_sha256")
    if build_source != expected_build_source_name(source_ref) or not isinstance(build_source_sha256, str) or not SHA256_RE.fullmatch(build_source_sha256):
        raise BootstrapError("runtime manifest must checksum a commit-named BUILD_SOURCE.json")
    artifacts = data.get("artifacts")
    if not isinstance(artifacts, list) or len(artifacts) != len(COMPONENTS):
        raise BootstrapError("runtime manifest must contain exactly the server and web artifacts")

    found: set[str] = set()
    validated: list[dict[str, Any]] = []
    for item in artifacts:
        if not isinstance(item, dict):
            raise BootstrapError("runtime manifest artifact entries must be objects")
        component = item.get("component")
        artifact = item.get("artifact")
        digest = item.get("sha256")
        size_bytes = item.get("size_bytes")
        if component not in COMPONENTS or component in found:
            raise BootstrapError("runtime manifest components must contain server and web exactly once")
        if artifact != expected_artifact_name(component, source_ref):
            raise BootstrapError("runtime artifact filename must match its component and full source commit")
        if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
            raise BootstrapError("runtime artifact must provide a SHA-256 checksum")
        if not isinstance(size_bytes, int) or not 0 < size_bytes <= MAX_ARTIFACT_BYTES:
            raise BootstrapError("runtime artifact must provide a bounded positive size_bytes")
        found.add(component)
        validated.append({"component": component, "artifact": artifact, "sha256": digest, "size_bytes": size_bytes})
    if found != set(COMPONENTS):
        raise BootstrapError("runtime manifest must contain server and web artifacts")
    return source_ref, validated, {"artifact": build_source, "sha256": build_source_sha256}


def validate_build_source(path: Path, source_ref: str) -> None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BootstrapError("BUILD_SOURCE.json is not valid JSON") from exc
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise BootstrapError("BUILD_SOURCE.json has an unsupported schema version")
    if data.get("upstream_repository") != UPSTREAM_REPOSITORY or data.get("source_kind") != "commit":
        raise BootstrapError("BUILD_SOURCE.json has an unexpected upstream source")
    if data.get("source_ref") != source_ref or not isinstance(data.get("generated_at"), str) or not data["generated_at"]:
        raise BootstrapError("BUILD_SOURCE.json does not match the runtime manifest")
    if data.get("wrapper_repository") != WRAPPER_REPOSITORY:
        raise BootstrapError("BUILD_SOURCE.json has an unexpected wrapper repository")
    wrapper_ref = data.get("wrapper_ref")
    if not isinstance(wrapper_ref, str) or not SOURCE_REF_RE.fullmatch(wrapper_ref):
        raise BootstrapError("BUILD_SOURCE.json must record an immutable wrapper commit")
    workflow_run_id = data.get("workflow_run_id")
    if not isinstance(workflow_run_id, str) or not workflow_run_id.isdecimal() or int(workflow_run_id) <= 0:
        raise BootstrapError("BUILD_SOURCE.json must record its workflow run id")

    components = data.get("components")
    if not isinstance(components, list) or len(components) != len(COMPONENTS):
        raise BootstrapError("BUILD_SOURCE.json must describe server and web exactly once")
    found: set[str] = set()
    for item in components:
        if not isinstance(item, dict):
            raise BootstrapError("BUILD_SOURCE.json component entries must be objects")
        component = item.get("component")
        if component not in COMPONENTS or component in found:
            raise BootstrapError("BUILD_SOURCE.json components must contain server and web exactly once")
        if item.get("upstream_repository") != UPSTREAM_REPOSITORY or item.get("source_ref") != source_ref:
            raise BootstrapError("BUILD_SOURCE.json component provenance does not match the runtime manifest")
        if item.get("dockerfile") != COMPONENTS[component]["dockerfile"]:
            raise BootstrapError("BUILD_SOURCE.json component Dockerfile does not match its component")
        dockerfile_sha256 = item.get("dockerfile_sha256")
        if not isinstance(dockerfile_sha256, str) or not SHA256_RE.fullmatch(dockerfile_sha256):
            raise BootstrapError("BUILD_SOURCE.json component must checksum its Dockerfile")
        found.add(component)


def archive_members(archive: Path) -> dict[str, tarfile.TarInfo]:
    try:
        with tarfile.open(archive, "r:gz") as bundle:
            members = bundle.getmembers()
    except (OSError, tarfile.TarError) as exc:
        raise BootstrapError("runtime artifact is not a readable gzip tar archive") from exc
    if len(members) > MAX_ARTIFACT_MEMBERS:
        raise BootstrapError("runtime artifact contains too many tar members")

    safe_members: dict[str, tarfile.TarInfo] = {}
    unpacked_bytes = 0
    for member in members:
        path = Path(member.name)
        canonical_name = str(path)
        if path.is_absolute() or ".." in path.parts or member.issym() or member.islnk() or member.isdev():
            raise BootstrapError("runtime artifact contains an unsafe tar member")
        if not (member.isdir() or member.isfile()) or member.mode & (stat.S_ISUID | stat.S_ISGID):
            raise BootstrapError("runtime artifact contains an unsupported tar member")
        if canonical_name in safe_members:
            raise BootstrapError("runtime artifact contains duplicate tar members")
        if member.isfile():
            unpacked_bytes += member.size
            if unpacked_bytes > MAX_UNPACKED_BYTES:
                raise BootstrapError("runtime artifact exceeds the maximum unpacked size")
        safe_members[canonical_name] = member
    return safe_members


def validate_tar_members(archive: Path) -> None:
    archive_members(archive)


def validate_component_archive(archive: Path, component: str) -> None:
    members = archive_members(archive)
    required_name = str(COMPONENTS[component]["required"])
    required = members.get(required_name)
    if required is None or not required.isfile():
        raise BootstrapError(f"runtime {component} artifact is missing its required entrypoint")
    if component == "server" and not required.mode & 0o111:
        raise BootstrapError("runtime server entrypoint is not executable")


def remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)


def prepare_component(archive: Path, component: str, destination: Path) -> tuple[Path, Path]:
    """Extract a validated component beside its destination without replacing it."""
    validate_component_archive(archive, component)
    try:
        stage_parent = Path(tempfile.mkdtemp(prefix=f".coze-{component}-", dir=destination.parent))
        stage = stage_parent / component
        stage.mkdir()
        with tarfile.open(archive, "r:gz") as bundle:
            bundle.extractall(stage)
    except (OSError, tarfile.TarError) as exc:
        raise BootstrapError("runtime artifact could not be extracted into a staging directory") from exc
    return stage_parent, stage


def commit_prepared_components(prepared: list[tuple[str, Path, Path, Path]]) -> None:
    """Replace the pair only after both bundles are ready, restoring on failure."""
    moved: list[tuple[Path, Path | None]] = []
    try:
        for component, _stage_parent, stage, destination in prepared:
            backup: Path | None = None
            if destination.exists() or destination.is_symlink():
                backup = destination.parent / f".coze-{component}-previous-{uuid.uuid4().hex}"
                os.replace(destination, backup)
            moved.append((destination, backup))
            os.replace(stage, destination)
    except OSError as exc:
        for destination, backup in reversed(moved):
            try:
                remove_path(destination)
                if backup is not None and (backup.exists() or backup.is_symlink()):
                    os.replace(backup, destination)
            except OSError:
                pass
        raise BootstrapError("runtime artifact pair could not be atomically installed") from exc
    try:
        for _destination, backup in moved:
            if backup is not None:
                remove_path(backup)
    except OSError as exc:
        raise BootstrapError("runtime artifact installation left an unsafe previous payload") from exc


def install_component(archive: Path, component: str, destination: Path) -> None:
    """Install one component for local tests and standalone validation helpers."""
    stage_parent, stage = prepare_component(archive, component, destination)
    try:
        commit_prepared_components([(component, stage_parent, stage, destination)])
    finally:
        shutil.rmtree(stage_parent, ignore_errors=True)


def set_runtime_owner(paths: list[Path]) -> None:
    try:
        account = pwd.getpwnam("user")
        for root in paths:
            os.chown(root, account.pw_uid, account.pw_gid)
            for directory, directories, files in os.walk(root):
                for name in [*directories, *files]:
                    os.chown(Path(directory) / name, account.pw_uid, account.pw_gid, follow_symlinks=False)
    except (KeyError, OSError) as exc:
        raise BootstrapError("unable to assign the Coze runtime owner") from exc


def verify_server_dependencies(server_binary: Path) -> None:
    result = subprocess.run(["ldd", str(server_binary)], text=True, capture_output=True, check=False)
    if result.returncode != 0 or "not found" in result.stdout:
        raise BootstrapError("runtime server dynamic dependencies are unresolved")


def install_runtime_components(archives: dict[str, Path]) -> None:
    """Stage, validate, and install the complete server/web pair as one operation."""
    if set(archives) != set(COMPONENTS):
        raise BootstrapError("runtime installation requires exactly server and web artifacts")
    prepared: list[tuple[str, Path, Path, Path]] = []
    try:
        for component in COMPONENTS:
            destination = COMPONENTS[component]["destination"]
            stage_parent, stage = prepare_component(archives[component], component, destination)
            prepared.append((component, stage_parent, stage, destination))
        set_runtime_owner([stage for _component, _parent, stage, _destination in prepared])
        server_stage = next(stage for component, _parent, stage, _destination in prepared if component == "server")
        verify_server_dependencies(server_stage / COMPONENTS["server"]["required"])
        commit_prepared_components(prepared)
    finally:
        for _component, stage_parent, _stage, _destination in prepared:
            shutil.rmtree(stage_parent, ignore_errors=True)


def write_provenance(
    run_dir: Path,
    manifest_sha256: str,
    source_ref: str,
    build_source: dict[str, str],
    artifacts: list[dict[str, Any]],
) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "manifest_sha256": manifest_sha256,
        "source_kind": "commit",
        "source_ref": source_ref,
        "build_source": build_source,
        "artifacts": artifacts,
    }
    temporary = run_dir / ".runtime-provenance.json.tmp"
    target = run_dir / "runtime-provenance.json"
    temporary.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    temporary.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)
    os.replace(temporary, target)


def main() -> int:
    manifest_url = os.environ.get("COZE_RUNTIME_MANIFEST_URI", "")
    download_token = os.environ.get("COZE_RUNTIME_DOWNLOAD_TOKEN", "")
    if not manifest_url:
        raise BootstrapError("COZE_RUNTIME_MANIFEST_URI is required")
    require_https_url(manifest_url, "COZE_RUNTIME_MANIFEST_URI")

    app_dir = Path(os.environ.get("COZE_APP_DIR", "/app"))
    web_dir = Path(os.environ.get("COZE_WEB_DIR", "/opt/coze-web"))
    if app_dir != COMPONENTS["server"]["destination"] or web_dir != COMPONENTS["web"]["destination"]:
        raise BootstrapError("runtime destinations must remain /app and /opt/coze-web")
    run_dir = Path(os.environ.get("RUN_DIR", "/run/coze"))

    with tempfile.TemporaryDirectory(prefix="coze-runtime-", dir="/tmp") as temporary:
        workdir = Path(temporary)
        manifest_path = workdir / "manifest.json"
        download(manifest_url, manifest_path, download_token)
        manifest_sha256 = sha256(manifest_path)
        try:
            manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise BootstrapError("runtime manifest is not valid JSON") from exc
        source_ref, artifacts, build_source = validate_manifest(manifest_data)
        build_source_path = workdir / build_source["artifact"]
        download(manifest_artifact_url(manifest_url, build_source["artifact"]), build_source_path, download_token)
        if sha256(build_source_path) != build_source["sha256"]:
            raise BootstrapError("BUILD_SOURCE.json checksum does not match its manifest")
        validate_build_source(build_source_path, source_ref)
        archives: dict[str, Path] = {}
        for item in artifacts:
            artifact_path = workdir / item["artifact"]
            download(manifest_artifact_url(manifest_url, item["artifact"]), artifact_path, download_token)
            if artifact_path.stat().st_size != item["size_bytes"]:
                raise BootstrapError("runtime artifact size does not match its manifest")
            if sha256(artifact_path) != item["sha256"]:
                raise BootstrapError("runtime artifact checksum does not match its manifest")
            archives[item["component"]] = artifact_path
        install_runtime_components(archives)
        write_provenance(run_dir, manifest_sha256, source_ref, build_source, artifacts)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BootstrapError as exc:
        print(f"[runtime-bootstrap] {exc}", file=sys.stderr)
        raise SystemExit(1)
