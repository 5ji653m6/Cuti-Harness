from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, status

from app.config import Settings
from app.models import CreateRunResponse, RunEnvelope, RunRequest
from app.runner import SandboxRunner


def create_app(injected_runner: SandboxRunner | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        runner = injected_runner or SandboxRunner(Settings())
        app.state.runner = runner
        try:
            yield
        finally:
            runner.close()

    app = FastAPI(
        title="CUTI Sandbox Worker",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )

    def authorize(request: Request) -> None:
        settings = getattr(request.app.state.runner, "settings", None)
        token = getattr(settings, "internal_token", "") if settings else ""
        if token and request.headers.get("Authorization") != f"Bearer {token}":
            raise HTTPException(status_code=401, detail="invalid internal token")

    @app.get("/healthz")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post(
        "/v1/runs",
        response_model=CreateRunResponse,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def create_run(payload: RunRequest, request: Request) -> RunEnvelope:
        authorize(request)
        try:
            return request.app.state.runner.submit(payload)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/v1/runs/{run_id}", response_model=RunEnvelope)
    def get_run(run_id: str, request: Request) -> RunEnvelope:
        authorize(request)
        result = request.app.state.runner.get(run_id)
        if result is None:
            raise HTTPException(status_code=404, detail="run not found")
        return result

    @app.post("/v1/runs/{run_id}/cancel", response_model=RunEnvelope)
    def cancel_run(run_id: str, request: Request) -> RunEnvelope:
        authorize(request)
        result = request.app.state.runner.cancel(run_id)
        if result is None:
            raise HTTPException(status_code=404, detail="run not found")
        return result

    return app


app = create_app()

