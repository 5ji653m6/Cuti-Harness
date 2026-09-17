import os
from contextlib import asynccontextmanager
from pathlib import Path

# This entrypoint is the self-hosted Video Runtime. Provider keys always come
# from the process environment; keep ACCOUNT_BACKEND=env for older env files.
os.environ.setdefault("ACCOUNT_BACKEND", "env")
# The standalone distribution is self-contained by default.  Requiring every
# developer to remember STORAGE_BACKEND=local made successfully generated
# artifacts point at /files while that route was never mounted.  Hosted/S3
# deployments still override these values explicitly.
os.environ.setdefault("STORAGE_BACKEND", "local")
os.environ.setdefault("LOCAL_STORAGE_DIR", "./data/uploads")
# Cuti's combined backend historically listened on 8000.  The extracted
# Video Runtime listens on 8001 in the documented self-hosted profile, so its
# local-storage URLs must point back to this service instead of the removed
# legacy backend. Deployments on another origin can still override the value.
os.environ.setdefault("PUBLIC_BASE_URL", "http://127.0.0.1:8001")
os.environ.setdefault("VIDEO_STAGED_PLANNING_ENABLED", "true")
os.environ.setdefault("VIDEO_CONTINUOUS_PLAN_PATCH_ENABLED", "true")

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .api import router, set_runtime
from .deepseek_bff import (
    router as deepseek_bff_router,
    set_deepseek_client,
    studio_router as deepseek_studio_bff_router,
)
from .deepseek_client import DeepSeekHarnessClient
from .checkpoint_coordinator import CheckpointCoordinator
from .session_context import router as session_context_router
from .local_repository import LocalJsonVideoProjectRepository
from .local_state_path import resolve_state_path
from .postgres_repository import PostgresVideoProjectRepository
from .plugins.registry import configured_plugin_roots
from .runtime import VideoBuildRuntime
from .security import CapabilityGrantSigner
from .skill_workflows import load_workflow_skills


@asynccontextmanager
async def lifespan(_app: FastAPI):
    repository = None
    deepseek = None
    database_url = os.getenv("VIDEO_RUNTIME_DATABASE_URL", "").strip()
    if database_url:
        repository = await PostgresVideoProjectRepository.connect(
            database_url, os.getenv("VIDEO_RUNTIME_DATABASE_SCHEMA", "cuti_video_runtime"),
        )
    elif os.getenv("VIDEO_RUNTIME_IN_MEMORY", "").strip().lower() not in {
        "1", "true", "yes",
    }:
        repository = LocalJsonVideoProjectRepository(
            resolve_state_path(),
        )
    build_runtime = VideoBuildRuntime(repository=repository)
    roots = configured_plugin_roots()
    if roots:
        await build_runtime.plugins.load_directories(roots)
        await load_workflow_skills(build_runtime.plugins, build_runtime.skills)
        if any(
            callable(getattr(item.implementation, "capability_handlers", None))
            for item in build_runtime.plugins.loaded
        ):
            secret = os.getenv("VIDEO_CAPABILITY_GRANT_SECRET", "").encode()
            if len(secret) < 32:
                raise RuntimeError(
                    "VIDEO_CAPABILITY_GRANT_SECRET must contain at least 32 bytes "
                    "when executable plugin handlers are loaded",
                )
            build_runtime.configure_plugin_execution(CapabilityGrantSigner(secret))
            await build_runtime.recover_active_builds()
    set_runtime(build_runtime)
    backend = os.getenv("VIDEO_AGENT_BACKEND", "deepseek").strip().lower()
    if backend != "deepseek":
        raise RuntimeError("VIDEO_AGENT_BACKEND only supports 'deepseek'")
    deepseek = DeepSeekHarnessClient(
        os.getenv("DEEPSEEK_HARNESS_URL", "http://127.0.0.1:3080"),
        authorization=os.getenv("DEEPSEEK_HARNESS_AUTHORIZATION") or None,
    )
    set_deepseek_client(deepseek)
    checkpoint_coordinator = CheckpointCoordinator(build_runtime, deepseek)
    checkpoint_coordinator.start()
    try:
        yield
    finally:
        await checkpoint_coordinator.close()
        await build_runtime.close()
        set_deepseek_client(None)
        if deepseek is not None:
            await deepseek.close()
        if repository is not None and callable(getattr(repository, "close", None)):
            await repository.close()


app = FastAPI(
    title="Cuti Video Runtime",
    description="Project-oriented incremental media build runtime.",
    version="0.1.0",
    lifespan=lifespan,
)
app.include_router(session_context_router)
app.include_router(router)

# The open-source profile does not require S3. The Cuti Media Service writes
# immutable outputs into this shared directory and the Runtime exposes them to
# providers, validators, Studio previews, and downloads through one stable URL.
if os.getenv("STORAGE_BACKEND", "").strip().lower() == "local":
    local_storage_dir = Path(
        os.getenv("LOCAL_STORAGE_DIR", "./data/uploads"),
    ).expanduser().resolve()
    local_storage_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/files", StaticFiles(directory=str(local_storage_dir)), name="video-files")

chat_app = FastAPI(title="DeepSeek compatibility BFF")
chat_app.include_router(deepseek_bff_router)
chat_app.include_router(deepseek_studio_bff_router)
app.mount("/chat-v1/service", chat_app)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "healthy"}
