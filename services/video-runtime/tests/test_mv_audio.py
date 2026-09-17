"""Unit tests for MV audio planning + host media.audio_* capabilities."""
from __future__ import annotations

import time
from unittest.mock import AsyncMock, patch

import pytest

from app.chat.v2.host_gateway import HostGateway, HostGatewayError
from app.video_runtime.builtin_plugins.media_core import MediaCorePlugin
from app.video_runtime.security import CapabilityExecutionEnvelope, CapabilityGrant
from app.chat.v2.mv_audio import (
    MAX_CLIP_SEC,
    parse_cut_segments,
    reference_clips_for_cut,
    transcription_public_view,
)
from app.chat.v2.capability_loader import build_registry


def test_transcription_public_view_keeps_vocal_gender():
    view = transcription_public_view(
        {
            "segments": [
                {"start": 0.0, "end": 4.0, "text": "hello", "vocal_gender": "m"},
                {"start": 4.0, "end": 8.0, "text": "world", "vocal_gender": "f"},
                {"start": 8.0, "end": 12.0, "text": "skip", "vocal_gender": "x"},
            ],
        },
        audio_url="http://localhost/files/song.mp3",
        audio_duration_sec=30.0,
    )
    assert view["segments"][0]["vocal_gender"] == "m"
    assert view["segments"][1]["vocal_gender"] == "f"
    assert "vocal_gender" not in view["segments"][2]


def test_short_window_is_one_clip_when_segments_omitted():
    segs = reference_clips_for_cut(0.0, 12.0)
    assert len(segs) == 1
    assert segs[0]["duration_sec"] == pytest.approx(12.0)
    assert segs[0]["start_sec"] == 0.0


def test_long_window_requires_director_segments():
    with pytest.raises(ValueError, match="requires segments"):
        reference_clips_for_cut(45.0, 30.0)


def test_director_segments_are_used_as_given():
    segs = reference_clips_for_cut(
        45.0,
        30.0,
        segments=[
            {"start_sec": 45.0, "duration": 10},
            {"start_sec": 55.0, "duration": 15},
            {"start_sec": 70.0, "duration": 5},
        ],
    )
    assert [s["duration_sec"] for s in segs] == [10.0, 15.0, 5.0]
    assert segs[0]["start_sec"] == pytest.approx(45.0)
    assert segs[-1]["end_sec"] == pytest.approx(75.0)
    assert all(s["duration_sec"] <= MAX_CLIP_SEC + 1e-6 for s in segs)


def test_parse_cut_segments_keeps_director_cuts():
    segs = parse_cut_segments(
        [
            {"start_sec": 113.0, "duration": 8},
            {"start_sec": 121.0, "duration": 15},
            {"start": 136.0, "duration_sec": 7},
        ]
    )
    assert [s["duration_sec"] for s in segs] == [8.0, 15.0, 7.0]
    assert segs[0]["start_sec"] == pytest.approx(113.0)
    assert segs[1]["end_sec"] == pytest.approx(136.0)
    assert segs[2]["end_sec"] == pytest.approx(143.0)


def test_parse_cut_segments_none_means_caller_decides():
    assert parse_cut_segments(None) is None
    assert parse_cut_segments([]) == []


def test_parse_cut_segments_rejects_overlong_clip():
    with pytest.raises(ValueError, match="<= 15"):
        parse_cut_segments([{"start_sec": 0, "duration": 16}])


def test_platform_registers_mv_media_capabilities():
    registry = build_registry(include_platform=True)
    assert registry.get("media.audio_analyze").service_target == "media_audio_analyze"
    assert registry.get("media.audio_analyze").output_type == "audiomap"
    assert registry.get("media.video_analyze").service_target == "media_video_analyze"
    assert registry.get("media.video_analyze").output_type == "videomap"
    assert registry.get("media.audio_cut").service_target == "media_audio_cut"
    assert registry.get("media.audio_cut").output_type == "audio_cut"
    assert registry.get("media.mix_audio").service_target == "media_mix_audio"
    assert registry.get("media.audio_trim").service_target == "media_audio_trim"


@pytest.mark.asyncio
async def test_media_audio_cut_trims_the_window(monkeypatch):
    calls = []

    async def _fake_trim(audio_url, start, duration, run_id):
        calls.append({"start": start, "duration": duration})
        return {"result_url": f"http://localhost/files/clip_{len(calls)}.mp3"}

    monkeypatch.setattr("app.utils.media_service_client.audio_trim", _fake_trim)
    result = await HostGateway().media_audio_cut({
        "audio_url": "http://localhost/files/song.mp3",
        "start_sec": 10.0,
        "duration": 15.0,
    })
    assert calls[0] == {"start": 10.0, "duration": 15.0}
    assert result["uri"].endswith("clip_1.mp3")
    assert result["master"]["start_sec"] == 10.0


@pytest.mark.asyncio
async def test_media_audio_analyze_uses_v1_transcript_and_smart_clip(monkeypatch):
    async def _fake_info(audio_url):
        return {"duration": 180.0}

    async def _explode(*args, **kwargs):
        raise AssertionError("must not call v1 transcribe when a transcript was supplied")

    async def _smart_clip(audio_url, target_duration_sec, transcription, audio_duration_sec=None):
        from types import SimpleNamespace

        assert target_duration_sec == 30.0
        return SimpleNamespace(
            method="ai_reuse_transcription",
            fallback_used=False,
            recommended=SimpleNamespace(
                start_sec=100.0,
                end_sec=130.0,
                target_duration_sec=30.0,
                actual_duration_sec=30.0,
                fade_in_sec=0.5,
                fade_out_sec=1.0,
                duration_error_sec=0.0,
                reasoning="chorus",
                model_dump=lambda: {
                    "start_sec": 100.0,
                    "end_sec": 130.0,
                    "target_duration_sec": 30.0,
                    "actual_duration_sec": 30.0,
                    "reasoning": "chorus",
                },
            ),
        )

    monkeypatch.setattr("app.utils.media_service_client.audio_info", _fake_info)
    monkeypatch.setattr(
        "app.services.agent.video.smart_clip_flow.transcribe_audio_for_analysis",
        _explode,
    )
    monkeypatch.setattr(
        "app.services.agent.video.smart_clip_flow.run_smart_clip_analysis",
        _smart_clip,
    )

    segments = [
        {"start": 10.0, "end": 14.0, "text": "夜色沉进旧窗台"},
        {"start": 100.0, "end": 105.0, "text": "就这样奔向天亮"},
        {"start": 140.0, "end": 145.0, "text": "就这样奔向天亮"},
    ]
    result = await HostGateway().media_audio_analyze({
        "audio_url": "http://localhost/files/song.mp3",
        "target_duration_sec": 30.0,
        "transcription": {
            "duration": 180.0,
            "text": "夜色沉进旧窗台 就这样奔向天亮",
            "segments": segments,
            "sections": [
                {
                    "section_type": "Chorus",
                    "start_time": 100.0,
                    "end_time": 111.0,
                    "section_emotion": "hopeful",
                }
            ],
            "global_bpm": 128,
            "genre": "synthwave",
        },
    })

    assert result["sections"][0]["section_type"] == "Chorus"
    assert result["global_bpm"] == 128
    assert result["smart_clip"]["recommended"]["start_sec"] == 100.0
    assert "master" not in result
    assert result["segments"][0]["text"] == "夜色沉进旧窗台"


@pytest.mark.asyncio
async def test_media_audio_analyze_requires_url():
    with pytest.raises(HostGatewayError, match="audio_url"):
        await HostGateway().media_audio_analyze({})


@pytest.mark.asyncio
async def test_media_audio_analyze_still_transcribes_if_agent_sends_transcribe_false(monkeypatch):
    calls = []

    async def _fake_info(audio_url):
        return {"duration": 180.0}

    async def _fake_transcribe(*args, **kwargs):
        calls.append(True)
        return {
            "duration": 180.0,
            "text": "ok",
            "segments": [{"start": 0.0, "end": 2.0, "text": "ok"}],
        }

    monkeypatch.setattr("app.utils.media_service_client.audio_info", _fake_info)
    monkeypatch.setattr(
        "app.services.agent.video.smart_clip_flow.transcribe_audio_for_analysis",
        _fake_transcribe,
    )
    result = await HostGateway().media_audio_analyze({
        "audio_url": "http://localhost/files/song.mp3",
        "transcribe": False,
    })
    assert calls == [True]
    assert result["segments"][0]["text"] == "ok"


@pytest.mark.asyncio
async def test_media_audio_analyze_forwards_language_contract(monkeypatch):
    captured = {}

    async def _fake_info(audio_url):
        return {"duration": 16.0}

    async def _fake_transcribe(*args, **kwargs):
        captured.update(kwargs)
        return {
            "duration": 16.0,
            "text": "油灯晃",
            "segments": [{"start": 0.0, "end": 2.0, "text": "油灯晃"}],
            "genre": "暗黑流行",
            "global_emotion": "紧张",
        }

    monkeypatch.setattr("app.utils.media_service_client.audio_info", _fake_info)
    monkeypatch.setattr(
        "app.services.agent.video.smart_clip_flow.transcribe_audio_for_analysis",
        _fake_transcribe,
    )
    await HostGateway().media_audio_analyze({
        "audio_url": "http://localhost/files/song.mp3",
        "language_contract": {
            "ui_locale": "en-US",
            "content_language": "zh-CN",
            "spoken_language": "zh-CN",
            "subtitle_language": "zh-CN",
            "provider_prompt_language": "auto",
        },
    })
    assert captured["language_contract"]["content_language"] == "zh-CN"
    assert captured["language_contract"]["ui_locale"] == "en-US"


@pytest.mark.asyncio
async def test_media_core_forwards_plan_language_contract_to_audio_analyze():
    grant = CapabilityGrant(
        project_id="project-1",
        session_id="session-1",
        user_id="user-1",
        plugin_id="cuti.media-core",
        capability="media.audio_analyze",
        allowed_capabilities=["media.audio_analyze"],
        max_cost_usd=1,
        timeout_seconds=30,
        idempotency_key="key-audio-analyze",
        audit_id="audit-1",
        nonce="nonce-1",
        expires_at=int(time.time()) + 60,
    )
    envelope = CapabilityExecutionEnvelope(grant)
    gateway = AsyncMock(return_value={
        "summary": "暗黑流行",
        "duration": 16.0,
        "title": "MV audiomap",
    })
    plugin = MediaCorePlugin()
    with patch("app.chat.v2.host_gateway.HostGateway.media_audio_analyze", gateway):
        artifact = await plugin.capability_handlers()["media.audio_analyze"](
            envelope,
            {
                "build": {"id": "build-1"},
                "step": {
                    "step_id": "audio-analysis",
                    "capability": "media.audio_analyze",
                    "output_artifact_id": "audiomap-1",
                    "output_artifact_type": "audiomap",
                    "language_contract": {
                        "ui_locale": "en-US",
                        "content_language": "zh-CN",
                        "spoken_language": "zh-CN",
                        "subtitle_language": "zh-CN",
                        "provider_prompt_language": "auto",
                    },
                    "parameters": {"audio_url": "https://cdn.example/a.mp3"},
                },
                "completed_artifacts": {},
            },
        )
    gateway.assert_awaited_once()
    forwarded = gateway.await_args.args[-1]
    assert forwarded["language_contract"]["content_language"] == "zh-CN"
    assert forwarded["language_contract"]["ui_locale"] == "en-US"
    assert artifact.type == "audiomap"


@pytest.mark.asyncio
async def test_media_mix_audio_replace_uses_add_audio(monkeypatch):
    calls = {}

    async def _fake_add(video_url, audio_segments, run_id):
        calls["video_url"] = video_url
        calls["audio_segments"] = audio_segments
        return {"result_url": "http://localhost/files/final.mp4"}

    monkeypatch.setattr("app.utils.media_service_client.video_add_audio", _fake_add)
    result = await HostGateway().media_mix_audio({
        "video_url": "http://localhost/files/silent.mp4",
        "audio_url": "http://localhost/files/master.mp3",
        "mode": "replace",
    })
    assert calls["audio_segments"][0]["audio_url"].endswith("master.mp3")
    assert result["mode"] == "replace"
    assert result["assembly_mode"] == "host_media_mix_replace"


@pytest.mark.asyncio
async def test_media_mix_audio_overlay(monkeypatch):
    calls = {}

    async def _fake_mix(video_url, audio_url, run_id, video_volume=0.3, audio_volume=1.0, loop_audio=False):
        calls.update({
            "audio_volume": audio_volume,
            "loop_audio": loop_audio,
        })
        return {"result_url": "http://localhost/files/mixed.mp4"}

    monkeypatch.setattr("app.utils.media_service_client.video_mix_audio", _fake_mix)
    result = await HostGateway().media_mix_audio({
        "video_url": "http://localhost/files/v.mp4",
        "audio_url": "http://localhost/files/a.mp3",
        "mode": "overlay",
        "audio_volume": 0.4,
        "loop_audio": True,
    })
    assert calls["audio_volume"] == 0.4
    assert calls["loop_audio"] is True
    assert result["mode"] == "overlay"
