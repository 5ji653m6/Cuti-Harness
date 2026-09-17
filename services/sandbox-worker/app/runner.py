import base64
import binascii
import hashlib
import io
import json
import mimetypes
import os
import shutil
import subprocess
import sys
import tarfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import docker
from docker.models.containers import Container
from requests import Timeout

from app.config import Settings
from app.models import Artifact, NetworkMode, RunEnvelope, RunRequest, RunStatus
from app.network_proxy import proxy_script
from app.security import confined_path


@dataclass
class RunRecord:
    run_id: str
    status: RunStatus = RunStatus.QUEUED
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    artifacts: list[Artifact] = field(default_factory=list)
    error: str | None = None
    container: Container | None = None
    proxy_container: Container | None = None
    process: subprocess.Popen | None = None
    cancel_requested: bool = False
    lock: threading.RLock = field(default_factory=threading.RLock)

    def snapshot(self) -> RunEnvelope:
        with self.lock:
            return RunEnvelope(
                run_id=self.run_id,
                status=self.status,
                exit_code=self.exit_code,
                stdout=self.stdout,
                stderr=self.stderr,
                artifacts=list(self.artifacts),
                error=self.error,
            )


class SandboxRunner:
    def __init__(self, settings: Settings, client: Any | None = None) -> None:
        self.settings = settings
        self.client = (
            client
            if client is not None
            else None if settings.unsafe_dev_mode else docker.from_env()
        )
        self.settings.staging_root.mkdir(parents=True, exist_ok=True)
        self._records: dict[str, RunRecord] = {}
        self._records_lock = threading.RLock()
        self._executor = ThreadPoolExecutor(
            max_workers=settings.max_concurrent_runs,
            thread_name_prefix="sandbox",
        )

    def submit(self, request: RunRequest) -> RunEnvelope:
        if request.timeout_seconds > self.settings.max_timeout_seconds:
            raise ValueError(f"timeout exceeds {self.settings.max_timeout_seconds} seconds")
        run_id = uuid.uuid4().hex
        record = RunRecord(run_id=run_id)
        with self._records_lock:
            self._records[run_id] = record
        self._executor.submit(self._execute, record, request)
        return record.snapshot()

    def get(self, run_id: str) -> RunEnvelope | None:
        with self._records_lock:
            record = self._records.get(run_id)
        return record.snapshot() if record else None

    def cancel(self, run_id: str) -> RunEnvelope | None:
        with self._records_lock:
            record = self._records.get(run_id)
        if record is None:
            return None
        with record.lock:
            if record.status in {
                RunStatus.SUCCEEDED,
                RunStatus.FAILED,
                RunStatus.TIMED_OUT,
                RunStatus.CANCELLED,
            }:
                return record.snapshot()
            record.cancel_requested = True
            record.status = RunStatus.CANCELLED
            container = record.container
            proxy_container = record.proxy_container
            process = record.process
        if container is not None:
            try:
                container.kill()
            except docker.errors.DockerException:
                pass
        if proxy_container is not None:
            try:
                proxy_container.kill()
            except docker.errors.DockerException:
                pass
        if process is not None:
            try:
                process.kill()
            except OSError:
                pass
        return record.snapshot()

    def close(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)
        if self.client is not None:
            self.client.close()

    def _execute(self, record: RunRecord, request: RunRequest) -> None:
        workspace = self.settings.staging_root / record.run_id
        container: Container | None = None
        proxy_container: Container | None = None
        egress_network = None
        volume = None
        try:
            self._stage_inputs(workspace, request)
            with record.lock:
                if record.cancel_requested:
                    return
                record.status = RunStatus.RUNNING
            if self.settings.unsafe_dev_mode:
                self._execute_unsafe_subprocess(record, request, workspace)
                return

            if self.client is None:
                raise RuntimeError("Docker client is unavailable for isolated sandbox execution")

            volume = self.client.volumes.create(
                name=f"cuti-sandbox-{record.run_id}",
                labels={"cuti.sandbox.run_id": record.run_id},
            )
            container_environment = dict(request.environment)
            common_options = {
                "working_dir": "/workspace",
                "environment": container_environment,
                "volumes": {volume.name: {"bind": "/workspace", "mode": "rw"}},
                "init": True,
                "stdin_open": False,
                "tty": False,
            }
            if self.settings.unsafe_dev_mode:
                execution_options = {
                    "user": "0:0",
                    "network_mode": "bridge",
                    "read_only": False,
                    "privileged": True,
                }
            else:
                execution_options = {
                    "user": (
                        f"{self.settings.sandbox_uid}:{self.settings.sandbox_gid}"
                    ),
                    "network_mode": "none",
                    "read_only": True,
                    "cap_drop": ["ALL"],
                    "security_opt": ["no-new-privileges:true"],
                    "mem_limit": self.settings.memory_limit,
                    "nano_cpus": self.settings.nano_cpus,
                    "pids_limit": self.settings.pids_limit,
                    "tmpfs": {"/tmp": "rw,noexec,nosuid,nodev,size=64m"},
                }
                if request.network.mode == NetworkMode.ALLOWLIST:
                    egress_network = self.client.networks.create(
                        name=f"cuti-sandbox-net-{record.run_id}",
                        driver="bridge",
                        internal=True,
                        labels={"cuti.sandbox.run_id": record.run_id},
                    )
                    proxy_container = self._start_egress_proxy(
                        record,
                        request,
                        egress_network,
                    )
                    proxy_url = "http://egress-proxy:8080"
                    container_environment.update({
                        "HTTP_PROXY": proxy_url,
                        "HTTPS_PROXY": proxy_url,
                        "http_proxy": proxy_url,
                        "https_proxy": proxy_url,
                        "NO_PROXY": "",
                        "no_proxy": "",
                    })
                    execution_options.pop("network_mode", None)
                    execution_options["network"] = egress_network.name
            try:
                self.client.images.get(request.image)
            except docker.errors.ImageNotFound:
                self.client.images.pull(request.image)
            container = self.client.containers.create(
                request.image,
                request.command,
                **common_options,
                **execution_options,
            )
            container.put_archive("/workspace", self._workspace_archive(workspace))
            container.start()
            with record.lock:
                record.container = container
                record.proxy_container = proxy_container
                cancelled = record.cancel_requested
            if cancelled:
                container.kill()

            try:
                result = container.wait(timeout=request.timeout_seconds)
            except Timeout:
                container.kill()
                container.wait(timeout=10)
                with record.lock:
                    if not record.cancel_requested:
                        record.status = RunStatus.TIMED_OUT
                        record.error = "execution timed out"
                return

            exit_code = int(result.get("StatusCode", -1))
            stdout = self._bounded_log(container.logs(stdout=True, stderr=False))
            stderr = self._bounded_log(container.logs(stdout=False, stderr=True))
            with record.lock:
                if record.cancel_requested:
                    return
                record.exit_code = exit_code
                record.stdout = stdout
                record.stderr = stderr
                if exit_code == 0:
                    record.artifacts = self._collect_artifacts(container, request.artifacts)
                    record.status = RunStatus.SUCCEEDED
                else:
                    record.status = RunStatus.FAILED
                    record.error = f"container exited with code {exit_code}"
        except (ValueError, OSError, RuntimeError, binascii.Error, docker.errors.DockerException) as exc:
            with record.lock:
                if not record.cancel_requested:
                    record.status = RunStatus.FAILED
                    record.error = str(exc)
        finally:
            if container is not None:
                try:
                    container.remove(force=True)
                except docker.errors.DockerException:
                    pass
            if proxy_container is not None:
                try:
                    proxy_container.remove(force=True)
                except docker.errors.DockerException:
                    pass
            if egress_network is not None:
                try:
                    egress_network.remove()
                except docker.errors.DockerException:
                    pass
            if volume is not None:
                try:
                    volume.remove(force=True)
                except docker.errors.DockerException:
                    pass
            with record.lock:
                record.container = None
                record.proxy_container = None
                record.process = None
            shutil.rmtree(workspace, ignore_errors=True)

    def _start_egress_proxy(self, record: RunRecord, request: RunRequest, network) -> Container:
        """Start a trusted dual-homed proxy; the untrusted job sees only its internal network."""
        proxy_image = "python:3.11-slim"
        try:
            self.client.images.get(proxy_image)
        except docker.errors.ImageNotFound:
            self.client.images.pull(proxy_image)
        proxy = self.client.containers.create(
            proxy_image,
            ["python", "-u", "-c", proxy_script()],
            name=f"cuti-egress-proxy-{record.run_id}",
            environment={
                "CUTI_ALLOWED_DOMAINS": json.dumps(request.network.allowed_domains),
            },
            network_mode="bridge",
            read_only=True,
            cap_drop=["ALL"],
            security_opt=["no-new-privileges:true"],
            mem_limit="128m",
            nano_cpus=min(self.settings.nano_cpus, 500_000_000),
            pids_limit=64,
            tmpfs={"/tmp": "rw,noexec,nosuid,nodev,size=16m"},
            init=True,
            stdin_open=False,
            tty=False,
            labels={"cuti.sandbox.run_id": record.run_id},
        )
        network.connect(proxy, aliases=["egress-proxy"])
        proxy.start()
        with record.lock:
            record.proxy_container = proxy
            cancelled = record.cancel_requested
        if cancelled:
            proxy.kill()
            raise RuntimeError("sandbox run was cancelled while starting egress proxy")
        for _ in range(40):
            probe = proxy.exec_run([
                "python",
                "-c",
                "import socket; s=socket.create_connection(('127.0.0.1',8080),.2); s.close()",
            ])
            exit_code = getattr(probe, "exit_code", None)
            if exit_code is None and isinstance(probe, tuple):
                exit_code = probe[0]
            if exit_code == 0:
                return proxy
            time.sleep(0.05)
        proxy.remove(force=True)
        raise RuntimeError("sandbox egress proxy did not become ready")

    def _execute_unsafe_subprocess(
        self,
        record: RunRecord,
        request: RunRequest,
        workspace: Path,
    ) -> None:
        command = [
            str(workspace) + part[len("/workspace"):]
            if part.startswith("/workspace")
            else part
            for part in request.command
        ]
        if command[0] in {"python", "python3"}:
            command[0] = sys.executable
        environment = os.environ.copy()
        environment.update({
            key: (
                str(workspace) + value[len("/workspace"):]
                if value.startswith("/workspace")
                else value
            )
            for key, value in request.environment.items()
        })
        process = subprocess.Popen(
            command,
            cwd=workspace,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        with record.lock:
            record.process = process
            cancelled = record.cancel_requested
        if cancelled:
            process.kill()
        try:
            stdout, stderr = process.communicate(timeout=request.timeout_seconds)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()
            with record.lock:
                if not record.cancel_requested:
                    record.status = RunStatus.TIMED_OUT
                    record.error = "execution timed out"
                    record.stdout = self._bounded_log(stdout)
                    record.stderr = self._bounded_log(stderr)
            return
        with record.lock:
            if record.cancel_requested:
                return
            record.exit_code = process.returncode
            record.stdout = self._bounded_log(stdout)
            record.stderr = self._bounded_log(stderr)
            if process.returncode == 0:
                record.artifacts = self._collect_local_artifacts(
                    workspace,
                    request.artifacts,
                )
                record.status = RunStatus.SUCCEEDED
            else:
                record.status = RunStatus.FAILED
                record.error = f"process exited with code {process.returncode}"

    def _stage_inputs(self, workspace: Path, request: RunRequest) -> None:
        workspace.mkdir(mode=0o700, parents=False, exist_ok=False)
        (workspace / "output").mkdir()
        seen: set[str] = set()
        total = 0
        for item in request.inputs:
            if item.path in seen:
                raise ValueError(f"duplicate input path: {item.path}")
            seen.add(item.path)
            data = base64.b64decode(item.content_base64, validate=True)
            total += len(data)
            if total > self.settings.max_input_bytes:
                raise ValueError("input size limit exceeded")
            destination = confined_path(workspace, item.path)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
            os.chmod(destination, 0o666)
        for directory in [workspace, *(path for path in workspace.rglob("*") if path.is_dir())]:
            os.chmod(directory, 0o777)

    @staticmethod
    def _workspace_archive(workspace: Path) -> bytes:
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w") as archive:
            for path in sorted(workspace.rglob("*")):
                archive.add(path, arcname=path.relative_to(workspace).as_posix())
        return buffer.getvalue()

    def _collect_artifacts(self, container: Container, paths: list[str]) -> list[Artifact]:
        artifacts: list[Artifact] = []
        total = 0
        for relative in paths:
            stream, _stat = container.get_archive(f"/workspace/{relative}")
            archive_bytes = b"".join(stream)
            with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:*") as archive:
                members = [item for item in archive.getmembers() if item.isfile()]
                if len(members) != 1:
                    raise ValueError(
                        f"artifact is missing or not a regular file: {relative}"
                    )
                extracted = archive.extractfile(members[0])
                if extracted is None:
                    raise ValueError(f"artifact cannot be read: {relative}")
                data = extracted.read(self.settings.max_artifact_bytes + 1)
            total += len(data)
            if total > self.settings.max_artifact_bytes:
                raise ValueError("artifact size limit exceeded")
            artifacts.append(
                Artifact(
                    path=relative,
                    media_type=mimetypes.guess_type(relative)[0] or "application/octet-stream",
                    size_bytes=len(data),
                    sha256=hashlib.sha256(data).hexdigest(),
                    content_base64=base64.b64encode(data).decode("ascii"),
                )
            )
        return artifacts

    def _collect_local_artifacts(self, workspace: Path, paths: list[str]) -> list[Artifact]:
        artifacts: list[Artifact] = []
        total = 0
        for relative in paths:
            path = confined_path(workspace, relative)
            if path.is_symlink() or not path.is_file():
                raise ValueError(f"artifact is missing or not a regular file: {relative}")
            data = path.read_bytes()
            total += len(data)
            if total > self.settings.max_artifact_bytes:
                raise ValueError("artifact size limit exceeded")
            artifacts.append(Artifact(
                path=relative,
                media_type=mimetypes.guess_type(relative)[0] or "application/octet-stream",
                size_bytes=len(data),
                sha256=hashlib.sha256(data).hexdigest(),
                content_base64=base64.b64encode(data).decode("ascii"),
            ))
        return artifacts

    def _bounded_log(self, value: bytes | str) -> str:
        data = value.encode() if isinstance(value, str) else value
        if len(data) > self.settings.max_log_bytes:
            data = data[: self.settings.max_log_bytes] + b"\n[truncated]"
        return data.decode("utf-8", errors="replace")
