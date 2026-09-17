"""Integration: Alibaba HappyHorse 1.0 Image-to-Video — 计费单元测试。

完整 ffprobe 矩阵（conda env cuti-video-local）：

  conda run -n cuti-video-local python scripts/test_wavespeed_happyhorse_1_0_i2v_specs.py \\
    --images-json scripts/happyhorse_1_1_keyframes.json --durations 3 5 15 --parallel 3

  conda run -n cuti-video-local python scripts/test_wavespeed_happyhorse_1_0_i2v_specs.py --retry-failed --parallel 3

本文件仅跑计费（无需 API Key）：

  conda run -n cuti-video-local pytest tests/tools/test_happyhorse_1_0_i2v_integration.py -k cost -q
"""
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

from app.models.tool_enums import Resolution, ToolType
from app.services.tool_service import ToolService


def test_happyhorse_1_0_i2v_cost_720p_5s():
    cost = ToolService.calculate_cost(
        ToolType.HAPPYHORSE_1_0_I2V, duration=5, resolution=Resolution.P720
    )
    assert cost == pytest.approx(0.70)


def test_happyhorse_1_0_i2v_cost_1080p_5s():
    cost = ToolService.calculate_cost(
        ToolType.HAPPYHORSE_1_0_I2V, duration=5, resolution=Resolution.P1080
    )
    assert cost == pytest.approx(1.40)


def test_happyhorse_1_0_i2v_cost_720p_10s():
    cost = ToolService.calculate_cost(
        ToolType.HAPPYHORSE_1_0_I2V, duration=10, resolution=Resolution.P720
    )
    assert cost == pytest.approx(1.40)


def test_happyhorse_1_0_i2v_cost_480p_bills_as_720p():
    cost = ToolService.calculate_cost(
        ToolType.HAPPYHORSE_1_0_I2V, duration=5, resolution=Resolution.P480
    )
    assert cost == pytest.approx(0.70)
