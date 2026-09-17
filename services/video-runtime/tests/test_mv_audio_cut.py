"""media.audio_cut trims a chosen window into master + ≤15s clips."""
from __future__ import annotations

import pytest

from app.chat.v2.host_gateway import HostGateway, HostGatewayError


@pytest.fixture
def trims(monkeypatch) -> list[dict]:
    calls: list[dict] = []

    async def _fake_trim(audio_url, start, duration, run_id, **kwargs):
        calls.append({"start": start, "duration": duration})
        return {"result_url": f"http://localhost/files/clip_{len(calls)}.mp3"}

    monkeypatch.setattr("app.utils.media_service_client.audio_trim", _fake_trim)
    return calls


@pytest.mark.asyncio
async def test_cuts_master_and_every_segment(trims):
    result = await HostGateway().media_audio_cut({
        "audio_url": "http://localhost/files/song.mp3",
        "start_sec": 32.46,
        "duration": 30.0,
        "segments": [
            {"start_sec": 32.46, "duration": 15},
            {"start_sec": 47.46, "duration": 15},
        ],
        "transcription": {
            "segments": [
                {"start": 32.46, "end": 36.86, "text": "倒数三秒灯光熄灭"},
                {"start": 38.20, "end": 42.36, "text": "让心跳过这座城"},
                {"start": 48.76, "end": 58.34, "text": "霓虹不灭我不退让"},
            ]
        },
    })

    assert [(item["start"], item["duration"]) for item in trims] == [
        (32.46, 30.0),
        (32.46, 15.0),
        (47.46, 15.0),
    ]
    assert result["master"]["audio_url"] == "http://localhost/files/clip_1.mp3"
    assert [item["audio_url"] for item in result["segments"]] == [
        "http://localhost/files/clip_2.mp3",
        "http://localhost/files/clip_3.mp3",
    ]
    assert [item["duration_sec"] for item in result["segments"]] == [15.0, 15.0]
    assert "clip_durations" not in result
    assert result["uri"] == result["master"]["audio_url"]
    assert result["segments"][0]["lyrics"] == ["倒数三秒灯光熄灭", "让心跳过这座城"]
    assert result["segments"][1]["lyrics"] == ["霓虹不灭我不退让"]


@pytest.mark.asyncio
async def test_uses_smart_clip_recommended_when_start_omitted(trims):
    result = await HostGateway().media_audio_cut({
        "audio_url": "http://localhost/files/song.mp3",
        "analysis": {
            "smart_clip": {
                "recommended": {"start_sec": 32.46, "end_sec": 62.46},
            },
            "segments": [
                {"start_sec": 32.46, "end_sec": 36.86, "text": "倒数三秒灯光熄灭"},
            ],
        },
        "segments": [
            {"start_sec": 32.46, "duration": 15},
            {"start_sec": 47.46, "duration": 15},
        ],
    })
    assert trims[0] == {"start": 32.46, "duration": 30.0}
    assert result["master"]["lyrics"] == ["倒数三秒灯光熄灭"]


@pytest.mark.asyncio
async def test_never_starts_the_master_at_zero_when_the_window_does_not(trims):
    await HostGateway().media_audio_cut({
        "audio_url": "http://localhost/files/song.mp3",
        "start_sec": 32.46,
        "duration": 30.0,
        "segments": [
            {"start_sec": 32.46, "duration": 15},
            {"start_sec": 47.46, "duration": 15},
        ],
    })
    assert all(item["start"] != 0.0 for item in trims)


@pytest.mark.asyncio
async def test_rejects_missing_window(trims):
    with pytest.raises(HostGatewayError, match="start_sec and duration"):
        await HostGateway().media_audio_cut({
            "audio_url": "http://localhost/files/song.mp3",
        })


@pytest.mark.asyncio
async def test_does_not_transcribe_or_pick_a_window(monkeypatch, trims):
    async def _boom(*_a, **_k):
        raise AssertionError("media.audio_cut must not transcribe")

    monkeypatch.setattr(
        "app.services.agent.video.smart_clip_flow.transcribe_audio_for_analysis",
        _boom,
    )
    monkeypatch.setattr(
        "app.services.agent.video.smart_clip_flow.run_smart_clip_analysis",
        _boom,
    )
    await HostGateway().media_audio_cut({
        "audio_url": "http://localhost/files/song.mp3",
        "start_sec": 32.46,
        "duration": 30.0,
        "segments": [
            {"start_sec": 32.46, "duration": 15},
            {"start_sec": 47.46, "duration": 15},
        ],
    })
    assert trims[0] == {"start": 32.46, "duration": 30.0}


@pytest.mark.asyncio
async def test_rejects_long_window_without_segments(trims):
    with pytest.raises(HostGatewayError, match="requires segments"):
        await HostGateway().media_audio_cut({
            "audio_url": "http://localhost/files/song.mp3",
            "start_sec": 113.0,
            "duration": 30.0,
        })
    assert trims == []


@pytest.mark.asyncio
async def test_uses_director_segments(trims):
    result = await HostGateway().media_audio_cut({
        "audio_url": "http://localhost/files/song.mp3",
        "start_sec": 113.0,
        "duration": 30.0,
        "segments": [
            {"start_sec": 113.0, "duration": 8},
            {"start_sec": 121.0, "duration": 15},
            {"start_sec": 136.0, "duration": 7},
        ],
        "transcription": {
            "segments": [
                {"start": 113.0, "end": 120.0, "text": "不必等云开"},
                {"start": 122.0, "end": 134.0, "text": "墨痕成山"},
                {"start": 137.0, "end": 142.0, "text": "归途在不在"},
            ]
        },
    })
    assert [(item["start"], item["duration"]) for item in trims] == [
        (113.0, 30.0),
        (113.0, 8.0),
        (121.0, 15.0),
        (136.0, 7.0),
    ]
    assert [item["duration_sec"] for item in result["segments"]] == [8.0, 15.0, 7.0]
    assert result["segments"][0]["lyrics"] == ["不必等云开"]
    assert result["segments"][2]["lyrics"] == ["归途在不在"]
