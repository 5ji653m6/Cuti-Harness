from fastapi import APIRouter

from app.api.v1.video import router as video_router
from app.api.v1.audio import router as audio_router
from app.api.v1.image import router as image_router
from app.api.v1.pipeline import router as pipeline_router
from app.api.v1.subtitle import router as subtitle_router

api_router = APIRouter()
api_router.include_router(video_router)
api_router.include_router(audio_router)
api_router.include_router(image_router)
api_router.include_router(pipeline_router)
api_router.include_router(subtitle_router)
