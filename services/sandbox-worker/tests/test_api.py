from fastapi.testclient import TestClient

from app.main import create_app
from app.models import RunEnvelope, RunStatus


class FakeRunner:
    def __init__(self) -> None:
        self.result = RunEnvelope(run_id="run-1", status=RunStatus.QUEUED)
        self.closed = False

    def submit(self, payload: object) -> RunEnvelope:
        return self.result

    def get(self, run_id: str) -> RunEnvelope | None:
        return self.result if run_id == self.result.run_id else None

    def cancel(self, run_id: str) -> RunEnvelope | None:
        if run_id != self.result.run_id:
            return None
        self.result = self.result.model_copy(update={"status": RunStatus.CANCELLED})
        return self.result

    def close(self) -> None:
        self.closed = True


def test_run_lifecycle_endpoints_return_strict_envelopes() -> None:
    runner = FakeRunner()
    with TestClient(create_app(runner)) as client:
        created = client.post("/v1/runs", json={"image": "tool:1", "command": ["run"]})
        assert created.status_code == 202
        assert created.json() == {"run_id": "run-1", "status": "queued"}

        fetched = client.get("/v1/runs/run-1")
        assert fetched.status_code == 200
        assert fetched.json()["artifacts"] == []

        cancelled = client.post("/v1/runs/run-1/cancel")
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "cancelled"

        assert client.get("/v1/runs/missing").status_code == 404
    assert runner.closed


def test_request_schema_forbids_extra_fields() -> None:
    with TestClient(create_app(FakeRunner())) as client:
        response = client.post(
            "/v1/runs",
            json={"image": "tool:1", "command": ["run"], "privileged": True},
        )
    assert response.status_code == 422

