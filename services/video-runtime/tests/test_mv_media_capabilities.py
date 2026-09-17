"""Broad case coverage for mv media capabilities (analyze/cut/mix)."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.capabilities.models import CapabilityRegistry
from app.chat.v2.capability_loader import build_registry
from app.chat.v2.host_gateway import HostGateway, HostGatewayError
from app.chat.v2.models import ArtifactVersion
from app.chat.v2.mv_audio import (
    reference_clips_for_cut,
)
from app.chat.v2.skill_catalog import SkillCatalog
from app.chat.v2.workflows import (
    WORKFLOWS,
    capability_requires_workflow,
    configure_workflows,
    inject_workflow_parameters,
    is_workflow_skill,
)


def _music(uri: str = "http://localhost/files/song.mp3") -> ArtifactVersion:
    return ArtifactVersion(
        id=str(uuid4()),
        artifact_id=str(uuid4()),
        project_id="p",
        type="music",
        version=1,
        produced_by_task_id="t-music",
        title="song",
        summary="",
        uri=uri,
        metadata={},
    )


def _video(uri: str = "http://localhost/files/clip.mp4") -> ArtifactVersion:
    return ArtifactVersion(
        id=str(uuid4()),
        artifact_id=str(uuid4()),
        project_id="p",
        type="video",
        version=1,
        produced_by_task_id="t-video",
        title="clip",
        summary="",
        uri=uri,
        metadata={},
    )


def _fake_transcription(**overrides) -> dict:
    payload = {
        "duration": 180.0,
        "text": "倒数三秒灯光熄灭",
        "segments": [
            {"start": 32.46, "end": 36.86, "text": "倒数三秒灯光熄灭"},
            {"start": 38.20, "end": 42.36, "text": "让心跳过这座城"},
        ],
        "sections": [
            {
                "section_type": "Chorus",
                "start_time": 33.5,
                "end_time": 59.5,
                "section_emotion": "defiant",
            }
        ],
        "global_bpm": 128,
        "genre": "synthwave",
        "global_emotion": "defiant",
    }
    payload.update(overrides)
    return payload


def _patch_v1_listen(
    monkeypatch,
    *,
    transcription: dict | None = None,
    smart_clip_start: float = 32.46,
    smart_clip_raises: bool = False,
):
    transcribe_calls: list[dict] = []
    smart_calls: list[float] = []

    async def _transcribe(audio_url, **kwargs):
        transcribe_calls.append({"audio_url": audio_url, **kwargs})
        return transcription or _fake_transcription()

    async def _smart(audio_url, target, transcription, audio_duration_sec=None):
        smart_calls.append(float(target))
        if smart_clip_raises:
            raise RuntimeError("gemini down")
        from types import SimpleNamespace

        end = smart_clip_start + float(target)
        return SimpleNamespace(
            method="ai_reuse_transcription",
            fallback_used=False,
            recommended=SimpleNamespace(
                start_sec=smart_clip_start,
                end_sec=end,
                target_duration_sec=target,
                actual_duration_sec=target,
                model_dump=lambda: {
                    "start_sec": smart_clip_start,
                    "end_sec": end,
                    "target_duration_sec": target,
                    "actual_duration_sec": target,
                    "reasoning": "chorus",
                },
            ),
        )

    monkeypatch.setattr(
        "app.services.agent.video.smart_clip_flow.transcribe_audio_for_analysis",
        _transcribe,
    )
    monkeypatch.setattr(
        "app.services.agent.video.smart_clip_flow.run_smart_clip_analysis",
        _smart,
    )
    return transcribe_calls, smart_calls


# ─── director clips, no even-split ───────────────────────────────────────────


def test_short_window_without_segments_is_one_clip():
    segs = reference_clips_for_cut(0.0, 12.0)
    assert len(segs) == 1
    assert segs[0]["start_sec"] == pytest.approx(0.0)
    assert segs[0]["duration_sec"] == pytest.approx(12.0)


def test_long_window_without_segments_is_rejected():
    with pytest.raises(ValueError, match="requires segments"):
        reference_clips_for_cut(0.0, 30.0)
    with pytest.raises(ValueError, match="requires segments"):
        reference_clips_for_cut(0.0, 15.001)


def test_reference_clips_reject_bad_bounds():
    with pytest.raises(ValueError):
        reference_clips_for_cut(0.0, 0.0)
    with pytest.raises(ValueError):
        reference_clips_for_cut(0.0, -1.0)
    with pytest.raises(ValueError):
        reference_clips_for_cut(0.0, 10.0, max_segment_sec=0.0)


# ─── host gateway: analyze ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_analyze_calls_v1_transcribe_and_smart_clip(monkeypatch):
    async def _info(_url):
        return {"duration": 162.0}

    monkeypatch.setattr("app.utils.media_service_client.audio_info", _info)
    transcribe_calls, smart_calls = _patch_v1_listen(monkeypatch)
    result = await HostGateway().media_audio_analyze({
        "audio_url": "http://localhost/files/song.mp3",
        "target_duration_sec": 30.0,
        "clip_id": "clip-from-artifact",
    })
    assert transcribe_calls[0]["suno_clip_id"] == "clip-from-artifact"
    assert smart_calls == [30.0]
    assert result["sections"][0]["section_type"] == "Chorus"
    assert result["global_bpm"] == 128
    assert result["smart_clip"]["recommended"]["start_sec"] == pytest.approx(32.46)
    assert "master" not in result


@pytest.mark.asyncio
async def test_analyze_does_not_invent_clip_id_from_the_url(monkeypatch):
    async def _info(_url):
        return {"duration": 162.0}

    monkeypatch.setattr("app.utils.media_service_client.audio_info", _info)
    transcribe_calls, _ = _patch_v1_listen(monkeypatch)
    await HostGateway().media_audio_analyze({
        "audio_url": (
            "http://localhost/files/"
            "suno_task_clip_0_aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee.mp3"
        ),
        "target_duration_sec": 30.0,
    })
    assert transcribe_calls[0]["suno_clip_id"] is None


@pytest.mark.asyncio
async def test_analyze_skips_smart_clip_without_target(monkeypatch):
    async def _info(_url):
        return {"duration": 162.0}

    monkeypatch.setattr("app.utils.media_service_client.audio_info", _info)
    _, smart_calls = _patch_v1_listen(monkeypatch)
    result = await HostGateway().media_audio_analyze({
        "audio_url": "http://localhost/files/song.mp3",
        "transcription": _fake_transcription(),
    })
    assert smart_calls == []
    assert result["smart_clip"] is None
    assert result["segments"][0]["text"] == "倒数三秒灯光熄灭"


@pytest.mark.asyncio
async def test_analyze_zero_duration_rejected(monkeypatch):
    async def _info(_url):
        return {"duration": 0}

    monkeypatch.setattr("app.utils.media_service_client.audio_info", _info)
    with pytest.raises(HostGatewayError, match="duration"):
        await HostGateway().media_audio_analyze({
            "audio_url": "http://localhost/files/a.mp3",
        })


@pytest.mark.asyncio
async def test_analyze_smart_clip_failure_raises(monkeypatch):
    async def _info(_url):
        return {"duration": 120.0}

    monkeypatch.setattr("app.utils.media_service_client.audio_info", _info)
    _patch_v1_listen(monkeypatch, smart_clip_raises=True)
    with pytest.raises(HostGatewayError, match="smart_clip failed"):
        await HostGateway().media_audio_analyze({
            "audio_url": "http://localhost/files/a.mp3",
            "target_duration_sec": 30.0,
            "transcription": _fake_transcription(),
        })


@pytest.mark.asyncio
async def test_analyze_dispatch_requires_grant(monkeypatch):
    async def _info(_url):
        return {"duration": 10.0}

    monkeypatch.setattr("app.utils.media_service_client.audio_info", _info)
    _patch_v1_listen(monkeypatch)
    with pytest.raises(HostGatewayError, match="not granted"):
        await HostGateway().dispatch(
            "media.audio_analyze",
            {"audio_url": "http://localhost/files/a.mp3"},
            allowed_capabilities=["media.concat"],
        )
    ok = await HostGateway().dispatch(
        "media.audio_analyze",
        {"audio_url": "http://localhost/files/a.mp3"},
        allowed_capabilities=["media.audio_analyze"],
    )
    assert ok["genre"] == "synthwave"


# ─── host gateway: cut ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cut_rejects_missing_window():
    with pytest.raises(HostGatewayError, match="start_sec and duration"):
        await HostGateway().media_audio_cut({
            "audio_url": "http://localhost/files/a.mp3",
        })


@pytest.mark.asyncio
async def test_cut_rejects_negative_start():
    with pytest.raises(HostGatewayError, match="start_sec"):
        await HostGateway().media_audio_cut({
            "audio_url": "http://localhost/files/a.mp3",
            "start_sec": -1,
            "duration": 5,
        })


@pytest.mark.asyncio
async def test_cut_rejects_zero_duration():
    with pytest.raises(HostGatewayError, match="duration"):
        await HostGateway().media_audio_cut({
            "audio_url": "http://localhost/files/a.mp3",
            "start_sec": 0,
            "duration": 0,
        })


@pytest.mark.asyncio
async def test_cut_empty_result_url(monkeypatch):
    async def _trim(*_a, **_k):
        return {"result_url": None}

    monkeypatch.setattr("app.utils.media_service_client.audio_trim", _trim)
    with pytest.raises(HostGatewayError, match="no result_url"):
        await HostGateway().media_audio_cut({
            "audio_url": "http://localhost/files/a.mp3",
            "start_sec": 0,
            "duration": 10,
        })


@pytest.mark.asyncio
async def test_cut_dispatch_alias_uri(monkeypatch):
    calls = {}

    async def _trim(audio_url, start, duration, run_id):
        calls["audio_url"] = audio_url
        return {"result_url": "http://localhost/files/out.mp3"}

    monkeypatch.setattr("app.utils.media_service_client.audio_trim", _trim)
    result = await HostGateway().dispatch(
        "media.audio_cut",
        {"uri": "http://localhost/files/in.mp3", "duration": 8, "start_sec": 2},
        allowed_capabilities=["media.audio_cut"],
    )
    assert calls["audio_url"].endswith("in.mp3")
    assert result["master"]["duration_sec"] == pytest.approx(8.0)
    assert result["uri"].endswith("out.mp3")


# ─── host gateway: mix ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_mix_default_mode_is_replace(monkeypatch):
    called = {"add": 0, "mix": 0}

    async def _add(*_a, **_k):
        called["add"] += 1
        return {"result_url": "http://localhost/files/r.mp4"}

    async def _mix(*_a, **_k):
        called["mix"] += 1
        return {"result_url": "http://localhost/files/m.mp4"}

    monkeypatch.setattr("app.utils.media_service_client.video_add_audio", _add)
    monkeypatch.setattr("app.utils.media_service_client.video_mix_audio", _mix)
    result = await HostGateway().media_mix_audio({
        "video_url": "http://localhost/files/v.mp4",
        "music_url": "http://localhost/files/a.mp3",
    })
    assert called == {"add": 1, "mix": 0}
    assert result["mode"] == "replace"


@pytest.mark.asyncio
async def test_mix_rejects_bad_mode():
    with pytest.raises(HostGatewayError, match="mode"):
        await HostGateway().media_mix_audio({
            "video_url": "http://localhost/files/v.mp4",
            "audio_url": "http://localhost/files/a.mp3",
            "mode": "duck",
        })


@pytest.mark.asyncio
async def test_mix_requires_both_urls():
    with pytest.raises(HostGatewayError, match="video_url"):
        await HostGateway().media_mix_audio({"audio_url": "http://x/a.mp3"})
    with pytest.raises(HostGatewayError, match="audio_url"):
        await HostGateway().media_mix_audio({"video_url": "http://x/v.mp4"})


async def test_executor_analyze_cut_mix_pipeline(monkeypatch):
    """Simulate MV spine: analyze → one cut → mix master."""
    async def _info(_url):
        return {"duration": 162.0}

    trims: list[tuple[float, float]] = []

    async def _trim(audio_url, start, duration, run_id):
        trims.append((start, duration))
        return {"result_url": f"http://localhost/files/seg-{len(trims)}.mp3"}

    async def _add(video_url, audio_segments, run_id):
        return {"result_url": "http://localhost/files/mv-final.mp4"}

    monkeypatch.setattr("app.utils.media_service_client.audio_info", _info)
    monkeypatch.setattr("app.utils.media_service_client.audio_trim", _trim)
    monkeypatch.setattr("app.utils.media_service_client.video_add_audio", _add)
    _patch_v1_listen(monkeypatch)

    gw = HostGateway()
    analysis = await gw.media_audio_analyze({
        "audio_url": "http://localhost/files/song.mp3",
        "target_duration_sec": 30.0,
    })
    assert "master" not in analysis
    cut = await gw.media_audio_cut({
        "audio_url": analysis["audio_url"],
        "analysis": analysis,
        "start_sec": analysis["smart_clip"]["recommended"]["start_sec"],
        "duration": 30.0,
        "segments": [
            {"start_sec": analysis["smart_clip"]["recommended"]["start_sec"], "duration": 15},
            {"start_sec": analysis["smart_clip"]["recommended"]["start_sec"] + 15, "duration": 15},
        ],
    })
    assert cut["segment_count"] == 2
    assert cut["master"]["start_sec"] == pytest.approx(32.46)
    assert all(start != 0.0 for start, _ in trims)

    final = await gw.media_mix_audio({
        "video_url": "http://localhost/files/concat.mp4",
        "audio_url": cut["uri"],
        "mode": "replace",
    })
    assert final["uri"].endswith("mv-final.mp4")
    assert len(trims) == cut["segment_count"] + 1
    assert sum(d for _, d in trims[1:]) == pytest.approx(30.0)


# ─── skill / workflow / registry ─────────────────────────────────────────────


def test_mv_skill_files_and_workflow_contract():
    root = Path(__file__).resolve().parents[1] / "skills" / "external" / "mv"
    assert (root / "SKILL.md").is_file()
    assert (root / "reference.md").is_file()

    catalog = SkillCatalog([root.parent])
    catalog.discover()
    skill = catalog.load("mv")
    text = skill.instructions
    for token in (
        "media.audio_analyze",
        "media.audio_cut",
        "media.mix_audio",
        "media.concat",
        "hyperframes-captions",
        "caption_html",
        "media.hyperframes_caption",
        "subtitle-authoring",
        "subtitle.compose",
        "media.subtitle_burn",
        "Never",
        "minimax-h3",
        "suno.generate",
        "h3",
        "创意标准",
        "reference.md",
        "doubao-seedance-2-0",
    ):
        assert token in text
    # The song step hands lyrics + Style Box to $suno-song, which opens Bitwize.
    assert "video_skill_load(\"suno-song\")" in text
    # duration lands near the ask, so the window stays a judgement on the real
    # length: cut from 0 when it is close, smart_clip.recommended when it is not.
    assert "audio_duration_sec" in text
    assert "smart_clip.recommended" in text
    # Cast locks what is visible once; sung voice follows that lock.
    assert "## 班子" in text
    assert "身份" in text
    assert "https" in text
    assert "产物 id" in text
    assert "depends_on" in text
    assert "唱的人" in text
    assert "vocal_gender" in text
    assert "tags" in text
    assert "segments" in text
    assert "整数秒" in text
    assert "clip_durations" not in text
    assert "strip_audio" not in text
    assert "不传" in text and "audios" in text

    configure_workflows(
        SkillCatalog([
            Path(__file__).resolve().parents[1] / "skills" / "system",
            Path(__file__).resolve().parents[1] / "skills" / "builtin",
            Path(__file__).resolve().parents[1] / "skills" / "external",
        ]),
        None,
    )
    assert is_workflow_skill("mv")
    seedance2 = Path(__file__).resolve().parents[1] / "skills" / "external" / "seedance2" / "SKILL.md"
    if seedance2.is_file():
        assert is_workflow_skill("seedance2")
    spec = WORKFLOWS["mv"]
    assert set(spec.pipeline) <= set(spec.allowed_capabilities or ())
    # MV 不走短剧 text.generate（配乐用 suno.generate；分镜写进 generate prompt）。
    assert "atomic.text.generate" not in spec.pipeline
    assert "atomic.text.generate" not in (spec.allowed_capabilities or ())
    assert "suno.generate" in spec.pipeline
    assert "suno.generate" in (spec.allowed_capabilities or ())
    assert "atomic.music.generate" not in spec.pipeline
    assert "atomic.music.generate" not in (spec.allowed_capabilities or ())
    assert "open_montage.tool.invoke" not in (spec.allowed_capabilities or ())
    assert "media.extract_frame" in (spec.allowed_capabilities or ())
    assert "api.ark_protocol.generate" in (spec.allowed_capabilities or ())
    for cap in (
        "media.audio_analyze",
        "media.audio_cut",
        "media.mix_audio",
        "media.transcribe",
        "media.hyperframes_caption",
        "api.provider.generate",
    ):
        assert cap in spec.pipeline
    assert spec.pipeline[0] == "suno.generate"
    params = inject_workflow_parameters({}, spec)
    assert params["workflow_mode"] == "mv"
    assert "content_category" not in params
    skill_text = Path(__file__).resolve().parents[1] / "skills/external/mv/SKILL.md"
    description = skill_text.read_text(encoding="utf-8").split("---", 2)[1]
    assert "content_category" not in skill_text.read_text(encoding="utf-8")
    assert "research" + ".generate" not in description
    assert "media.audio_cut" in description
    assert "media.hyperframes_caption" in description
    assert spec.skill_dependencies == ()


def test_mv_capabilities_are_workflow_free_and_registered():
    registry = build_registry(include_platform=True)
    for cap_id in ("media.audio_analyze", "media.video_analyze", "media.audio_cut", "media.mix_audio"):
        manifest = registry.get(cap_id)
        assert manifest.executor == "local.service"
        assert not capability_requires_workflow(cap_id)
        assert manifest.parameters_schema.get("type") == "object"


def test_seedance2_untouched_by_mv_skill():
    root = Path(__file__).resolve().parents[1] / "skills" / "external" / "seedance2"
    skill = root / "SKILL.md"
    if not skill.is_file():
        pytest.skip("seedance2 Skill is not installed on this checkout")
    text = skill.read_text(encoding="utf-8")
    assert "media.audio_analyze" not in text
    assert "seedance-mv" not in text


def test_h3_skill_is_instruction_helper():
    root = Path(__file__).resolve().parents[1] / "skills" / "external" / "h3"
    catalog = SkillCatalog([root.parent])
    catalog.discover()
    skill = catalog.load("h3")
    assert skill.contract is None
    assert not is_workflow_skill("h3")
    text = skill.instructions
    for token in ("minimax-h3", "api.provider.generate"):
        assert token in text
    assert "images" in text and "audios" in text


def test_hyperframes_captions_skill_is_instruction_helper():
    catalog = SkillCatalog([Path(__file__).resolve().parents[1] / "skills" / "builtin"])
    catalog.discover()
    skill = catalog.load("hyperframes-captions")
    assert skill.contract is None
    assert not is_workflow_skill("hyperframes-captions")
    text = skill.instructions
    assert "media.hyperframes_caption" in text
    assert "时间戳" in text
    assert "caption_html" in text
    assert "caption-pill-karaoke" not in text
    assert "registry" not in text.lower()
    for name in (
        "hyperframes-core",
        "hyperframes-cli",
        "hyperframes-registry",
        "hyperframes-media",
        "hyperframes-creative",
        "hyperframes-animation",
        "gsap-core",
        "gsap-timeline",
        "media-use",
    ):
        loaded = catalog.load(name)
        assert loaded.contract is None
        assert not is_workflow_skill(name)
    assert "references/captions/authoring.md" in catalog.list_resources("hyperframes-media")


def test_hyperframes_caption_schema_requires_authored_html():
    from jsonschema.exceptions import ValidationError
    from jsonschema.validators import validator_for

    registry = build_registry(include_platform=True)
    schema = registry.get("media.hyperframes_caption").parameters_schema
    assert "style" not in schema["properties"]
    assert "accent_color" not in schema["properties"]
    assert "position" not in schema["properties"]
    assert "caption_html" in schema["properties"]
    assert "composition_html" in schema["properties"]
    assert "video_step" in schema["properties"]
    assert "video_url" in schema["properties"]
    validator = validator_for(schema)(schema)
    validator.validate({
        "video_url": "https://cdn.example/v.mp4",
        "caption_html": "<!doctype html><html></html>",
    })
    validator.validate({
        "video_step": "mixed-video",
        "composition_html": "<!doctype html><html></html>",
    })
    with pytest.raises(ValidationError):
        validator.validate({
            "video_url": "https://cdn.example/v.mp4",
            "transcription_step": "transcript",
        })
    with pytest.raises(ValidationError):
        validator.validate({
            "video_url": "https://cdn.example/v.mp4",
            "caption_html": "<!doctype html><html></html>",
            "style": "caption-pill-karaoke",
        })


def test_concat_and_mix_schemas_accept_dest_urls_or_step_ids():
    registry = build_registry(include_platform=True)
    from jsonschema.validators import validator_for

    concat = registry.get("media.concat").parameters_schema
    mix = registry.get("media.mix_audio").parameters_schema
    validator_for(concat)(concat).validate({
        "video_urls": ["https://cdn.example/a.mp4", "https://cdn.example/b.mp4"],
        "transition_duration": 0,
    })
    validator_for(concat)(concat).validate({
        "video_steps": ["shot-1-video", "shot-2-video"],
        "normalize": True,
    })
    validator_for(mix)(mix).validate({
        "video_url": "https://cdn.example/v.mp4",
        "audio_url": "https://cdn.example/a.mp3",
        "mode": "replace",
    })
    validator_for(mix)(mix).validate({
        "video_step": "assembled-video",
        "audio_step": "music-cut",
        "mode": "replace",
    })
