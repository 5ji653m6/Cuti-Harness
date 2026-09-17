import base64
import io
import json
import sys
import tarfile
from pathlib import Path
from unittest.mock import Mock

import pytest
from pydantic import ValidationError
from requests import Timeout

from app.config import Settings
from app.models import InputFile, NetworkMode, NetworkPolicy, RunRequest, RunStatus
from app.network_proxy import proxy_script
from app.runner import RunRecord, SandboxRunner


def make_runner(tmp_path: Path, container: Mock) -> tuple[SandboxRunner, Mock]:
    client = Mock()
    client.containers.create.return_value = container
    client.volumes.create.return_value.name = "run-volume"
    settings = Settings(staging_root=tmp_path, max_artifact_bytes=1024)
    return SandboxRunner(settings, client), client


def test_success_uses_hardened_container_and_returns_artifact(tmp_path: Path) -> None:
    container = Mock()
    container.wait.return_value = {"StatusCode": 0}
    container.logs.side_effect = [b"done\n", b""]
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        info = tarfile.TarInfo("result.txt")
        info.size = len(b"result")
        archive.addfile(info, io.BytesIO(b"result"))
    container.get_archive.return_value = ([buffer.getvalue()], {})
    runner, client = make_runner(tmp_path, container)
    request = RunRequest(
        image="example/tool:1",
        command=["python", "job.py"],
        inputs=[InputFile(path="job.py", content_base64=base64.b64encode(b"print(1)").decode())],
        artifacts=["output/result.txt"],
    )
    record = RunRecord(run_id="abc")

    runner._execute(record, request)

    result = record.snapshot()
    assert result.status == RunStatus.SUCCEEDED
    assert result.stdout == "done\n"
    assert base64.b64decode(result.artifacts[0].content_base64) == b"result"
    options = client.containers.create.call_args.kwargs
    assert options["network_mode"] == "none"
    assert options["read_only"] is True
    assert options["cap_drop"] == ["ALL"]
    assert options["security_opt"] == ["no-new-privileges:true"]
    assert options["pids_limit"] == 128
    container.put_archive.assert_called_once()
    container.start.assert_called_once()
    container.remove.assert_called_once_with(force=True)
    assert not (tmp_path / "abc").exists()
    runner.close()


def test_timeout_kills_container(tmp_path: Path) -> None:
    container = Mock()
    container.wait.side_effect = [Timeout(), {"StatusCode": 137}]
    runner, _ = make_runner(tmp_path, container)
    record = RunRecord(run_id="timeout")

    runner._execute(record, RunRequest(image="tool:1", command=["sleep", "10"], timeout_seconds=1))

    assert record.status == RunStatus.TIMED_OUT
    container.kill.assert_called_once()
    runner.close()


def test_rejects_unsafe_paths_and_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        InputFile(path="../secret", content_base64="")
    with pytest.raises(ValidationError):
        RunRequest(image="tool:1", command=["run"], surprise=True)
    with pytest.raises(ValidationError, match="cannot be enabled in production"):
        Settings(environment="production", unsafe_dev_mode=True)
    with pytest.raises(ValidationError, match="requires network mode"):
        NetworkPolicy(allowed_domains=["api.example.com"])
    with pytest.raises(ValidationError, match="requires allowed_domains"):
        NetworkPolicy(mode=NetworkMode.ALLOWLIST)
    with pytest.raises(ValidationError, match="exact public hostname"):
        NetworkPolicy(mode=NetworkMode.ALLOWLIST, allowed_domains=["127.0.0.1"])


def test_allowlist_network_uses_isolated_job_and_hardened_proxy(tmp_path: Path) -> None:
    proxy = Mock()
    proxy.exec_run.return_value = Mock(exit_code=0)
    container = Mock()
    container.wait.return_value = {"StatusCode": 0}
    container.logs.side_effect = [b"done\n", b""]

    client = Mock()
    client.containers.create.side_effect = [proxy, container]
    client.volumes.create.return_value.name = "run-volume"
    network = Mock()
    network.name = "isolated-network"
    client.networks.create.return_value = network
    runner = SandboxRunner(Settings(staging_root=tmp_path), client)
    record = RunRecord(run_id="allowlist")
    request = RunRequest(
        image="python:3.11-slim",
        command=["python", "job.py"],
        inputs=[InputFile(path="job.py", content_base64=base64.b64encode(b"print(1)").decode())],
        network=NetworkPolicy(
            mode=NetworkMode.ALLOWLIST,
            allowed_domains=["api.example.com"],
        ),
    )

    runner._execute(record, request)

    assert record.status == RunStatus.SUCCEEDED
    network.connect.assert_called_once_with(proxy, aliases=["egress-proxy"])
    proxy_options = client.containers.create.call_args_list[0].kwargs
    assert proxy_options["network_mode"] == "bridge"
    assert proxy_options["read_only"] is True
    assert proxy_options["cap_drop"] == ["ALL"]
    assert 'api.example.com' in proxy_options["environment"]["CUTI_ALLOWED_DOMAINS"]
    job_options = client.containers.create.call_args_list[1].kwargs
    assert job_options["network"] == "isolated-network"
    assert "network_mode" not in job_options
    assert job_options["environment"]["HTTPS_PROXY"] == "http://egress-proxy:8080"
    proxy.remove.assert_called_once_with(force=True)
    network.remove.assert_called_once_with()
    runner.close()


def test_egress_proxy_source_is_valid_python() -> None:
    compile(proxy_script(), "<sandbox-egress-proxy>", "exec")


def test_egress_proxy_enforces_exact_domain_and_public_dns(monkeypatch) -> None:
    monkeypatch.setenv("CUTI_ALLOWED_DOMAINS", json.dumps(["api.example.com"]))
    source = proxy_script().rsplit('Server(("0.0.0.0", 8080)', 1)[0]
    namespace = {}
    exec(compile(source, "<sandbox-egress-proxy-test>", "exec"), namespace)
    proxy_socket = namespace["socket"]
    monkeypatch.setattr(
        proxy_socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (proxy_socket.AF_INET, proxy_socket.SOCK_STREAM, 6, "", ("10.0.0.5", 443))
        ],
    )

    with pytest.raises(PermissionError, match="not allowlisted"):
        namespace["allowed_target"]("sub.api.example.com", 443)
    with pytest.raises(PermissionError, match="public address"):
        namespace["allowed_target"]("api.example.com", 443)


def test_rejects_oversized_decoded_input(tmp_path: Path) -> None:
    container = Mock()
    runner, client = make_runner(tmp_path, container)
    runner.settings.max_input_bytes = 2
    record = RunRecord(run_id="large")
    request = RunRequest(
        image="tool:1",
        command=["run"],
        inputs=[InputFile(path="input.bin", content_base64=base64.b64encode(b"abc").decode())],
    )

    runner._execute(record, request)

    assert record.status == RunStatus.FAILED
    assert record.error == "input size limit exceeded"
    client.containers.create.assert_not_called()
    runner.close()


def test_unsafe_dev_mode_runs_local_process_without_docker(tmp_path: Path) -> None:
    client = Mock()
    runner = SandboxRunner(
        Settings(staging_root=tmp_path, unsafe_dev_mode=True),
        client,
    )
    runner._execute(
        RunRecord(run_id="unsafe"),
        RunRequest(
            image="tool:1",
            command=[
                sys.executable,
                "-c",
                "from pathlib import Path; "
                "Path('output/result.json').write_text('{\"ok\": true}')",
            ],
            artifacts=["output/result.json"],
        ),
    )
    assert client.containers.create.call_count == 0
    runner.close()


def test_unsafe_dev_mode_does_not_connect_to_docker(tmp_path: Path, monkeypatch) -> None:
    from_env = Mock(side_effect=AssertionError("Docker must not be contacted"))
    monkeypatch.setattr("app.runner.docker.from_env", from_env)

    runner = SandboxRunner(Settings(staging_root=tmp_path, unsafe_dev_mode=True))

    assert runner.client is None
    from_env.assert_not_called()
    runner.close()
