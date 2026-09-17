from pathlib import Path

import pytest

from app.capabilities.models import CapabilityRegistry
from app.chat.v2.skill_catalog import SkillCatalog


def test_subtitle_capabilities_are_platform_tools():
    registry = CapabilityRegistry()

    transcribe = registry.get("media.transcribe")
    compose = registry.get("subtitle.compose")
    burn = registry.get("media.subtitle_burn")

    assert transcribe.output_type == "transcript"
    assert transcribe.inputs.required == ["video"]
    assert compose.output_type == "subtitle"
    assert compose.inputs.required == ["transcript"]
    assert burn.output_type == "video"
    assert set(burn.inputs.required) == {"video", "subtitle"}
    assert all(item.executor == "local.service" for item in (transcribe, compose, burn))


def test_subtitle_authoring_skill_is_instruction_only_and_discoverable():
    agent_root = Path(__file__).resolve().parents[1]
    catalog = SkillCatalog([
        agent_root / "skills" / "system",
        agent_root / "skills" / "builtin",
        agent_root / "skills" / "external",
    ])

    catalog.discover()
    skill = catalog.load("subtitle-authoring")

    assert skill.contract is None
    assert skill.metadata.trust_level == "trusted"
    assert "media.transcribe" in skill.instructions
    assert "references/quality-rules.md" in catalog.list_resources("subtitle-authoring")


@pytest.mark.asyncio
async def test_transcribe_video_normalizes_openai_timestamps(monkeypatch):
    from app.services import subtitle_transcription_service as service

    async def fake_extract(video_url, run_id, fmt):
        assert video_url == "https://example.test/video.mp4"
        assert fmt == "mp3"
        return {"result_url": "https://example.test/audio.mp3"}

    async def fake_download(url, destination, max_bytes):
        destination.write_bytes(b"audio")
        return 5

    class FakeTranscriptions:
        async def create(self, **kwargs):
            assert kwargs["model"] == "whisper-1"
            assert kwargs["prompt"] == "Hello world"
            assert kwargs["timestamp_granularities"] == ["word", "segment"]
            return {
                "text": "Hello world",
                "language": "en",
                "duration": 2.0,
                "segments": [{"start": 0, "end": 2.4, "text": "Hello world"}],
                "words": [
                    {"start": 0.35, "end": 0.8, "word": "Hello"},
                    {"start": 0.9, "end": 2, "word": "world"},
                ],
            }

    class FakeClient:
        def __init__(self, **kwargs):
            self.audio = type("Audio", (), {"transcriptions": FakeTranscriptions()})()

    monkeypatch.setattr(service.msc, "audio_extract", fake_extract)
    monkeypatch.setattr(service, "_download_limited", fake_download)
    monkeypatch.setattr(service, "AsyncOpenAI", FakeClient)
    monkeypatch.setattr(service.agent_settings, "OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(service.agent_settings, "SUBTITLE_TRANSCRIPTION_MODEL", "whisper-1")

    result = await service.transcribe_video(
        "https://example.test/video.mp4",
        run_id="subtitle-test",
        prompt="Hello world",
    )

    assert result["language"] == "en"
    assert result["segments"] == [{"start": 0.35, "end": 2.12, "text": "Hello world"}]
    assert len(result["words"]) == 2
    assert result["timing_source"] == "word_timestamps"
    assert result["audio_bytes"] == 5


def test_rejects_collapsed_hallucinated_word_timestamps():
    from app.services.subtitle_transcription_service import validate_transcription
    with pytest.raises(ValueError, match="Unreliable transcription"):
        validate_transcription({"words": [
            {"word": word, "start": 6.84, "end": 6.84}
            for word in "请不吝点赞订阅转发打赏"
        ]})


@pytest.mark.parametrize(
    ("provided", "expected"),
    [
        ("zh-CN", "zh"),
        ("zh_Hans", "zh"),
        ("Chinese", "zh"),
        ("Mandarin", "zh"),
        ("en-US", "en"),
        ("eng", "en"),
        ("auto", None),
        ("not-a-language", None),
    ],
)
def test_normalize_transcription_language(provided, expected):
    from app.services.subtitle_transcription_service import (
        normalize_transcription_language,
    )

    assert normalize_transcription_language(provided) == expected


@pytest.mark.asyncio
async def test_transcribe_video_sends_iso_639_1_language(monkeypatch):
    from app.services import subtitle_transcription_service as service

    async def fake_extract(video_url, run_id, fmt):
        return {"result_url": "https://example.test/audio.mp3"}

    async def fake_download(url, destination, max_bytes):
        destination.write_bytes(b"audio")
        return 5

    class FakeTranscriptions:
        async def create(self, **kwargs):
            assert kwargs["language"] == "zh"
            return {
                "text": "你好",
                "language": "zh",
                "duration": 1.0,
                "segments": [{"start": 0, "end": 1, "text": "你好"}],
                "words": [],
            }

    class FakeClient:
        def __init__(self, **kwargs):
            self.audio = type("Audio", (), {"transcriptions": FakeTranscriptions()})()

    monkeypatch.setattr(service.msc, "audio_extract", fake_extract)
    monkeypatch.setattr(service, "_download_limited", fake_download)
    monkeypatch.setattr(service, "AsyncOpenAI", FakeClient)
    monkeypatch.setattr(service.agent_settings, "OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(service.agent_settings, "SUBTITLE_TRANSCRIPTION_MODEL", "whisper-1")

    result = await service.transcribe_video(
        "https://example.test/video.mp4",
        run_id="subtitle-language-test",
        language="zh-CN",
    )

    assert result["language"] == "zh"


def test_subtitle_compose_defaults_to_audio_timing():
    registry = CapabilityRegistry()
    schema = registry.get("subtitle.compose").parameters_schema

    assert schema["properties"]["timing_mode"]["default"] == "audio"
