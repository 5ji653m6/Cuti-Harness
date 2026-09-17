"""Integration: Seedance 2.0 Fast Image-to-Video Turbo via WaveSpeed (1 call, consumes credits)."""
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


EXAMPLE_START = "https://static.wavespeed.ai/examples/7c92589b49414d90868acada962417d6/1776133918163434780_5AKT2blu.png"
EXAMPLE_END = "https://static.wavespeed.ai/examples/7c92589b49414d90868acada962417d6/1776133926649927474_K5fT3dlv.png"


@pytest.mark.asyncio
async def test_seedance_2_fast_turbo_smoke_wavespeed_api():
    if not os.getenv("WAVESPEED_API_KEY"):
        pytest.skip("WAVESPEED_API_KEY not set")
    svc = WaveSpeedService()
    if not svc.api_key:
        pytest.skip("WaveSpeed API key not configured")
    result = await svc.generate_seedance_2_fast_i2v_turbo(
        image=EXAMPLE_START,
        prompt="Slow push-in; warm light; subtle motion.",
        duration=4,
        resolution="720p",
        last_image=EXAMPLE_END,
        aspect_ratio="16:9",
    )
    assert result.success, result.message or result.error_msg
    assert result.video_url
    assert ".mp4" in result.video_url or "http" in result.video_url
