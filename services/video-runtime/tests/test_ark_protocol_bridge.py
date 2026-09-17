"""Tests for Ark↔WaveSpeed protocol bridge (no live provider calls)."""
from __future__ import annotations

import pytest

from app.integrations.providers.ark_protocol_bridge import (
    ark_create_body_to_profile,
    should_enable_ark_http_bridge,
    wavespeed_result_to_ark_status,
)


def test_ark_create_body_to_profile_extracts_multimodal_content():
    body = {
        "model": "doubao-seedance-2-0-260128",
        "duration": 8,
        "ratio": "16:9",
        "generate_audio": True,
        "content": [
            {"type": "text", "text": "小人喝咖啡"},
            {"type": "image_url", "image_url": {"url": "https://cdn.example/a.png"}},
            {"type": "video_url", "video_url": {"url": "https://cdn.example/b.mp4"}},
            {"type": "audio_url", "audio_url": {"url": "https://cdn.example/c.mp3"}},
        ],
    }
    profile = ark_create_body_to_profile(body)
    assert profile["prompt"] == "小人喝咖啡"
    assert profile["duration"] == 8
    assert profile["aspect_ratio"] == "16:9"
    assert profile["images"] == ["https://cdn.example/a.png"]
    assert profile["videos"] == ["https://cdn.example/b.mp4"]
    assert profile["audios"] == ["https://cdn.example/c.mp3"]


def test_wavespeed_result_to_ark_status_shape_for_seedance_cli():
    status = wavespeed_result_to_ark_status(
        task_id="cuti_bridge_abc",
        video_url="http://localhost/files/out.mp4",
        profile={"model": "doubao-seedance-2-0-260128", "duration": 5, "resolution": "1080p", "aspect_ratio": "16:9"},
        provider_used="wavespeed",
        raw_task_id="ws-1",
    )
    assert status["status"] == "succeeded"
    assert status["content"]["video_url"].endswith("/out.mp4")
    assert status["cuti_bridge"]["provider_used"] == "wavespeed"


def test_should_enable_bridge_for_seedance2_without_real_ark(monkeypatch):
    monkeypatch.delenv("ARK_API_KEY", raising=False)
    monkeypatch.setenv("WAVESPEED_API_KEY", "ws")
    assert should_enable_ark_http_bridge(
        skill_name="seedance2",
        script_path="scripts/seedance.py",
    )


def test_should_not_enable_bridge_when_real_ark_present(monkeypatch):
    monkeypatch.setenv("ARK_API_KEY", "real-ark-key")
    monkeypatch.setenv("WAVESPEED_API_KEY", "ws")
    assert not should_enable_ark_http_bridge(
        skill_name="seedance2",
        script_path="scripts/seedance.py",
    )


def test_protocol_bridge_skill_registers():
    from app.chat.v2.capability_loader import build_registry

    registry = build_registry(include_platform=True)
    cap = registry.get("api.ark_protocol.generate")
    assert cap.service_target == "ark_protocol_generate"
    assert cap.skill_name == "ark-wavespeed-protocol-bridge"


@pytest.mark.asyncio
async def test_create_and_get_ark_task_uses_mocked_wavespeed(monkeypatch):
    from app.integrations.providers import ark_protocol_bridge as bridge

    async def fake_generate(profile, fallbacks_json=None):
        assert profile["provider"] == "wavespeed"
        assert profile["prompt"] == "hello"
        return {
            "video_url": "http://localhost/files/v.mp4",
            "uri": "http://localhost/files/v.mp4",
            "provider_used": "wavespeed",
            "raw_task_id": "ws-99",
        }

    monkeypatch.setattr(
        "app.chat.v2.provider_bridge.generate_video",
        fake_generate,
    )
    created = await bridge.create_ark_task_via_wavespeed({
        "model": "doubao-seedance-2-0-260128",
        "duration": 5,
        "content": [{"type": "text", "text": "hello"}],
    })
    task_id = created["id"]
    assert created["status"] == "running"
    # Allow background task to finish.
    for _ in range(50):
        status = await bridge.get_ark_task(task_id)
        if status.get("status") == "succeeded":
            break
        await __import__("asyncio").sleep(0.02)
    assert status["status"] == "succeeded"
    assert status["content"]["video_url"].endswith("/v.mp4")
