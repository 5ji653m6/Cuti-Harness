"""Integration: Seedance 2.0 Image-to-Video Turbo via WaveSpeed (1 call, consumes credits)."""
import os
from pathlib import Path

import pytest

from dotenv import load_dotenv

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parent.parent.parent
_env = os.getenv("ENVIRONMENT", "development").lower()
if _env == "production":
    load_dotenv(ROOT / ".env.production")
else:
    load_dotenv(ROOT / ".env.development")
load_dotenv(ROOT / ".env.local")

from app.llm.wavespeed_service import WaveSpeedService
from app.models.tool_enums import Resolution, ToolType
from app.services.tool_service import ToolService


EXAMPLE_START = "https://static.wavespeed.ai/examples/3f7e3b510d1e4a60aea09ec4573e1751/1775358390074410023_q9OY8irB.jpeg"


def test_seedance_2_i2v_turbo_cost_1080p_5s():
    cost = ToolService.calculate_cost(ToolType.SEEDANCE_2_I2V_TURBO, duration=5, resolution=Resolution.P1080)
    assert cost == pytest.approx(0.65)


@pytest.mark.asyncio
async def test_seedance_2_i2v_turbo_smoke_wavespeed_api():
    if not os.getenv("WAVESPEED_API_KEY"):
        pytest.skip("WAVESPEED_API_KEY not set")
    svc = WaveSpeedService()
    if not svc.api_key:
        pytest.skip("WaveSpeed API key not configured")
    result = await svc.generate_seedance_2_i2v_turbo(
        image=EXAMPLE_START,
        prompt="Slow push-in; warm light; subtle motion.",
        duration=5,
        resolution="720p",
        aspect_ratio="16:9",
    )
    assert result.success, result.message or result.error_msg
    assert result.video_url
    assert ".mp4" in result.video_url or "http" in result.video_url
