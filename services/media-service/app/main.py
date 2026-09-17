import asyncio
import logging
import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from prometheus_fastapi_instrumentator import Instrumentator
from prometheus_fastapi_instrumentator import routing as prometheus_routing

from app.config import get_settings
from app.api.router import api_router
from app.services.workspace_service import WorkspaceService

settings = get_settings()

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    stream=sys.stdout,
)
# Suppress noisy libraries
logging.getLogger("botocore").setLevel(logging.WARNING)
logging.getLogger("boto3").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("s3transfer").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


# FastAPI 0.116+ may keep included routers as a lazy ``_IncludedRouter``
# without a ``path`` attribute. Older prometheus-fastapi-instrumentator
# versions assume every entry in ``app.routes`` is a Starlette Route and
# otherwise fail every request before it reaches the endpoint. Keep metrics
# available, but fall back to the raw request path until the upstream package
# learns how to resolve FastAPI's lazy router representation.
_prometheus_get_route_name = prometheus_routing.get_route_name


def _compatible_prometheus_route_name(request):
    try:
        return _prometheus_get_route_name(request)
    except AttributeError:
        route = request.scope.get("route")
        return getattr(route, "path", None)


prometheus_routing.get_route_name = _compatible_prometheus_route_name


@asynccontextmanager
async def lifespan(app: FastAPI):
    workspace_svc = WorkspaceService(settings)
    app.state.workspace_service = workspace_svc

    cleanup_task = asyncio.create_task(workspace_svc.start_ttl_cleanup_loop())
    logger.info(
        "cuti-media-service started | env=%s concurrent_jobs=%d ffmpeg_threads=%d",
        settings.environment,
        settings.max_concurrent_jobs,
        settings.ffmpeg_threads,
    )
    yield
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass
    logger.info("cuti-media-service shutdown")


app = FastAPI(
    title="Cuti Media Service",
    description="Media processing microservice — FFmpeg, image, S3",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

Instrumentator().instrument(app).expose(app, endpoint="/metrics")

app.include_router(api_router, prefix="/api/v1")



@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.get("/readyz")
async def readyz():
    return {"status": "ready"}
