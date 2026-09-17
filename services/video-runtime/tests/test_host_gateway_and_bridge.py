"""Tests for host gateway + provider bridge resolution (no live network)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.chat.v2.host_gateway import HostGateway, HostGatewayError, host_allowed
from app.chat.v2.provider_bridge import (
    ProviderGenerateError,
    _classify_wavespeed_failure,
    _model_family,
    normalize_video_profile,
    resolve_provider,
)
from app.chat.v2.skill_catalog import SkillCatalog
from app.chat.v2.capability_loader import build_registry


def test_host_allowed_exact_and_subdomain():
    assert host_allowed("api.wavespeed.ai", ["api.wavespeed.ai"])
    assert host_allowed("cdn.api.wavespeed.ai", ["api.wavespeed.ai"]) is False
    assert host_allowed("evil.com", ["api.wavespeed.ai"]) is False
    assert host_allowed("localhost", ["api.wavespeed.ai"]) is False


@pytest.mark.asyncio
async def test_http_request_rejects_non_allowlisted_host():
    gateway = HostGateway()
    with pytest.raises(HostGatewayError, match="allowlist"):
        await gateway.dispatch(
            "http.request",
            {"url": "https://evil.example/x", "method": "GET"},
            allowed_capabilities=["http.request"],
            allowed_domains=["api.wavespeed.ai"],
        )


@pytest.mark.asyncio
async def test_media_concat_passthrough_single_url():
    gateway = HostGateway()
    result = await gateway.media_concat({
        "video_urls": ["http://localhost:19004/files/a.mp4"],
    })
    assert result["assembly_mode"] == "passthrough"
    assert result["uri"].endswith("/a.mp4")


@pytest.mark.asyncio
async def test_media_concat_forwards_continuation_transition(monkeypatch):
    calls = {}

    async def _fake_concat(video_urls, run_id, normalize=True, transition_duration=0.0):
        calls.update({
            "video_urls": video_urls,
            "normalize": normalize,
            "transition_duration": transition_duration,
        })
        return {"result_url": "http://localhost/files/out.mp4", "duration": 1.875}

    monkeypatch.setattr("app.utils.media_service_client.video_concat", _fake_concat)
    result = await HostGateway().media_concat({
        "video_urls": [
            "http://localhost/files/a.mp4",
            "http://localhost/files/b.mp4",
        ],
        "transition_duration": 0.125,
    })

    assert calls["transition_duration"] == 0.125
    assert result["transition_duration"] == 0.125


@pytest.mark.asyncio
async def test_media_extract_frame_supports_true_last_frame(monkeypatch):
    async def _fake_extract(video_url, timestamp, run_id, image_format="jpeg", position="timestamp"):
        assert timestamp is None
        assert position == "last"
        return {
            "result_url": "http://localhost/files/last.png",
            "timestamp": 15.0,
            "format": "png",
        }

    monkeypatch.setattr("app.utils.media_service_client.video_extract_frame", _fake_extract)
    result = await HostGateway().media_extract_frame({
        "video_url": "http://localhost/files/a.mp4",
        "position": "last",
        "format": "png",
    })

    assert result["timestamp"] == 15.0
    assert result["position"] == "last"
    assert result["title"] == "Frame @ 15.00s"


def test_resolve_provider_ark_when_key_present(monkeypatch):
    monkeypatch.setenv("ARK_API_KEY", "ark")
    monkeypatch.delenv("WAVESPEED_API_KEY", raising=False)
    assert resolve_provider("ark") == "ark"


def test_resolve_provider_falls_back_to_wavespeed(monkeypatch):
    monkeypatch.delenv("ARK_API_KEY", raising=False)
    monkeypatch.setenv("WAVESPEED_API_KEY", "ws")
    assert resolve_provider("ark") == "wavespeed"


def test_resolve_provider_auto_selects_available_wavespeed(monkeypatch):
    monkeypatch.delenv("ARK_API_KEY", raising=False)
    monkeypatch.setenv("WAVESPEED_API_KEY", "wavespeed-key")

    assert resolve_provider("auto") == "wavespeed"


def test_resolve_provider_maps_legacy_pollo_seedance_to_wavespeed(monkeypatch):
    monkeypatch.delenv("ARK_API_KEY", raising=False)
    monkeypatch.setenv("WAVESPEED_API_KEY", "wavespeed-key")
    assert resolve_provider("pollo_seedance") == "wavespeed"
    assert resolve_provider("pollo_seedance", fallbacks_json="{}") == "wavespeed"


def test_resolve_provider_maps_seedance_shorthand_to_wavespeed(monkeypatch):
    monkeypatch.delenv("ARK_API_KEY", raising=False)
    monkeypatch.setenv("WAVESPEED_API_KEY", "w")
    assert resolve_provider("seedance") == "wavespeed"
    # A deployment-specific fallback map must not erase this invariant.
    assert resolve_provider("seedance", fallbacks_json="{}") == "wavespeed"


@pytest.mark.asyncio
async def test_generate_video_ignores_vendor_provider_when_model_is_h3(monkeypatch):
    from app.chat.v2 import provider_bridge as bridge

    captured = {}

    async def _fake_wavespeed(profile, _callback=None):
        captured.update(profile)
        return {"uri": "https://cdn/h3.mp4", "model_family": "minimax_h3"}

    monkeypatch.delenv("ARK_API_KEY", raising=False)
    monkeypatch.setenv("WAVESPEED_API_KEY", "wavespeed-key")
    monkeypatch.setattr(bridge, "_wavespeed_generate", _fake_wavespeed)
    result = await bridge.generate_video({
        "provider": "minimax",
        "model": "minimax-h3",
        "prompt": "a dancer",
        "duration": 8,
    })
    assert captured["model"] == "minimax-h3"
    assert result["model_family"] == "minimax_h3"


def test_create_time_insufficient_credits_requires_user_action():
    error = _classify_wavespeed_failure(
        'Seedance task create failed: 400, {"message":"Insufficient credits"}',
        provider="wavespeed",
        model="doubao-seedance-2-0-260128",
    )
    assert error.category == "insufficient_credits"
    assert error.retryable is False
    assert error.remote_task_id is None


def test_resolve_provider_raises_without_keys(monkeypatch):
    monkeypatch.delenv("ARK_API_KEY", raising=False)
    monkeypatch.delenv("WAVESPEED_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="no API key"):
        resolve_provider("ark")


def test_model_family_routes_seedance_15_20_and_25():
    assert _model_family("doubao-seedance-2-0-260128") == "seedance_2"
    assert _model_family("seedance-2.5") == "seedance_2_5"
    assert _model_family("bytedance/seedance-2.5/text-to-video") == "seedance_2_5"
    assert _model_family("doubao-seedance-1-5-pro-251215") == "seedance_1_5"
    assert _model_family("seedance-v1.5-pro") == "seedance_1_5"
    assert _model_family("") == "seedance_2"
    assert _model_family("wavespeed") == "seedance_2"


def test_model_family_routes_minimax_h3():
    assert _model_family("minimax-h3") == "minimax_h3"
    assert _model_family("h3") == "minimax_h3"
    assert _model_family("minimax/h3/reference-to-video") == "minimax_h3"
    assert _model_family("wavespeed-ai/minimax-h3/reference-to-video") == "minimax_h3"


def test_model_identifier_in_provider_slot_is_normalized_without_version_loss():
    profile = normalize_video_profile({"provider": "seedance-2.5", "prompt": "commercial"})
    assert profile["provider"] == "wavespeed"
    assert profile["model"] == "seedance-2.5"
    assert profile["requested_provider"] == "seedance-2.5"


def test_duration_seconds_is_normalized_to_provider_duration():
    profile = normalize_video_profile({
        "provider": "wavespeed",
        "prompt": "fifteen second scene",
        "duration_seconds": 15,
    })
    assert profile["duration"] == 15


def test_generic_reference_is_not_promoted_by_i2v_mode_alone():
    profile = normalize_video_profile({
        "provider": "seedance-2.5",
        "prompt": "Use @image1 as the character identity reference.",
        "generation_mode": "i2v",
        "images": ["https://cdn/character.png"],
    })

    assert profile["generation_mode"] == "t2v"
    assert profile["images"] == ["https://cdn/character.png"]
    assert "start_image_url" not in profile


@pytest.mark.parametrize(
    ("prompt", "slot"),
    [
        ("以@图片2作为首帧，保持人物动作连续。", "https://cdn/tail.png"),
        ("Use @image 2 as the first frame and continue the action.", "https://cdn/tail.png"),
        ("首帧使用@图片2，然后缓慢推镜。", "https://cdn/tail.png"),
    ],
)
def test_explicit_prompt_first_frame_slot_becomes_start_image(prompt, slot):
    profile = normalize_video_profile({
        "provider": "seedance-2.5",
        "prompt": prompt,
        "images": ["https://cdn/character.png", "https://cdn/tail.png"],
    })

    assert profile["generation_mode"] == "i2v"
    assert profile["start_image_url"] == slot


@pytest.mark.parametrize("prompt", [
    "参考图锁定身份服装车辆道具空间而非首帧：@图片1部长保镖，@图片2控制室。",
    "不要将@图片1作为首帧，只作人物参考。",
    "Do not use @image1 as the first frame; use identity references only.",
    "Not the first frame: @image1 is an identity reference.",
])
def test_negated_frame_assignment_keeps_all_identity_references(prompt):
    profile = normalize_video_profile({
        "model": "seedance-2.5", "generation_mode": "t2v", "prompt": prompt,
        "images": ["https://cdn/character.png", "https://cdn/scene.png"],
    })
    assert "start_image_url" not in profile
    assert profile["generation_mode"] == "t2v"
    assert len(profile["images"]) == 2


def test_conflicting_duration_selectors_are_rejected():
    with pytest.raises(ValueError, match="conflicting video duration selectors"):
        normalize_video_profile({"duration": 5, "duration_seconds": 15})


@pytest.mark.asyncio
async def test_generated_video_duration_probe_accepts_small_container_drift(monkeypatch):
    from app.llm import wavespeed_service

    async def _video_info(_url):
        return {"duration": 15.08}

    monkeypatch.setattr(wavespeed_service.msc, "video_info", _video_info)
    actual = await wavespeed_service._validate_generated_video_duration(
        "http://media/video.mp4", 15,
    )
    assert actual == pytest.approx(15.08)


@pytest.mark.asyncio
async def test_generated_video_duration_probe_rejects_wrong_length(monkeypatch):
    from app.llm import wavespeed_service

    async def _video_info(_url):
        return {"duration": 5.085}

    monkeypatch.setattr(wavespeed_service.msc, "video_info", _video_info)
    with pytest.raises(
        wavespeed_service.WaveSpeedFinalException,
        match=r"requested=15\.000s, actual=5\.085s",
    ):
        await wavespeed_service._validate_generated_video_duration(
            "http://media/video.mp4", 15,
        )


def test_conflicting_provider_model_selectors_are_rejected():
    with pytest.raises(ValueError, match="conflicting video model selectors"):
        normalize_video_profile({"provider": "seedance-2.5", "model": "seedance-2.0"})


@pytest.mark.asyncio
async def test_generate_video_routes_provider_slot_seedance_25_to_25_handler(monkeypatch):
    from app.chat.v2 import provider_bridge as bridge

    captured = {}

    async def _fake_wavespeed(profile, _callback=None):
        captured.update(profile)
        return {"uri": "https://cdn/seedance-25.mp4", "model_family": _model_family(profile["model"])}

    monkeypatch.setattr(bridge, "resolve_provider", lambda *_args, **_kwargs: "wavespeed")
    monkeypatch.setattr(bridge, "_wavespeed_generate", _fake_wavespeed)
    result = await bridge.generate_video({"provider": "seedance-2.5", "prompt": "commercial"})

    assert captured["provider"] == "wavespeed"
    assert captured["model"] == "seedance-2.5"
    assert result["model_family"] == "seedance_2_5"


@pytest.mark.asyncio
async def test_wavespeed_generate_dispatches_minimax_h3(monkeypatch):
    from app.chat.v2 import provider_bridge as bridge

    calls = {}

    async def _fake_resolve(urls):
        return list(urls)

    class _Svc:
        @staticmethod
        def normalize_h3_resolution(resolution):
            return "2k" if str(resolution).lower() in {"2k", "1080p"} else "768p"

        async def create_minimax_h3_r2v_task(self, **kwargs):
            calls["create"] = kwargs
            return "task-h3"

        async def create_seedance_2_t2v_task(self, **kwargs):
            raise AssertionError("H3 must not fall through to Seedance T2V")

        async def create_seedance_2_i2v_task(self, **kwargs):
            raise AssertionError("H3 must not use Seedance I2V lock-frame")

        async def poll_seedance_video_task_until_complete(self, *args, **kwargs):
            calls["poll"] = (args, kwargs)
            return SimpleNamespace(
                video_url="http://cdn/h3.mp4",
                model_dump=lambda: {"video_url": "http://cdn/h3.mp4"},
            )

    monkeypatch.setattr(bridge, "_resolve_media_urls", _fake_resolve)
    monkeypatch.setattr(
        "app.llm.wavespeed_service.get_wavespeed_service",
        lambda: _Svc(),
    )
    out = await bridge._wavespeed_generate({
        "prompt": "a dancer on the drop",
        "model": "minimax-h3",
        "images": ["http://localhost/files/cast.png"],
        "audios": ["http://localhost/files/seg.mp3"],
        "duration": 8,
        "resolution": "1080p",
        "aspect_ratio": "9:16",
        "generate_audio": False,
    })
    assert out["video_url"].endswith("/h3.mp4")
    assert out["model_family"] == "minimax_h3"
    assert calls["create"]["reference_images"] == ["http://localhost/files/cast.png"]
    assert calls["create"]["reference_audios"] == ["http://localhost/files/seg.mp3"]
    assert "create_seedance" not in calls


def test_model_family_rejects_unknown_seedance_label():
    with pytest.raises(ValueError, match="unsupported Seedance model"):
        _model_family("doubao-seedance-3-0-experimental")


def test_classify_pending_timeout_is_retryable():
    err = _classify_wavespeed_failure(
        "provider_pending_timeout: Seedance 2.0 T2V still processing "
        "after poll limit; remote_task_id=8d05ad155d7e4e408908a1259b5bac06; "
        "retryable=true",
        provider="wavespeed",
        model="doubao-seedance-2-0-260128",
    )
    assert isinstance(err, ProviderGenerateError)
    assert err.category == "provider_pending_timeout"
    assert err.retryable is True
    assert err.remote_task_id == "8d05ad155d7e4e408908a1259b5bac06"


@pytest.mark.asyncio
async def test_wavespeed_generate_dispatches_seedance_15(monkeypatch):
    from app.chat.v2 import provider_bridge as bridge
    from types import SimpleNamespace

    calls = {}

    async def _fake_resolve(urls):
        return list(urls)

    class _Svc:
        async def create_seedance_v1_5_video_task(self, *args, **kwargs):
            calls["v15"] = (args, kwargs)
            return "t-15"

        async def poll_seedance_video_task_until_complete(self, *args, **kwargs):
            return SimpleNamespace(
                video_url="http://cdn/out.mp4",
                task_id="t-15",
                model_dump=lambda: {"video_url": "http://cdn/out.mp4"},
            )

        async def generate_seedance_2_t2v(self, **kwargs):
            calls["t2v"] = kwargs
            raise AssertionError("must not call seedance 2 for 1.5 profile")

        async def generate_seedance_2_i2v(self, **kwargs):
            calls["i2v"] = kwargs
            raise AssertionError("must not call i2v for 1.5 profile")

    monkeypatch.setattr(bridge, "_resolve_media_urls", _fake_resolve)
    monkeypatch.setattr(
        "app.llm.wavespeed_service.get_wavespeed_service",
        lambda: _Svc(),
    )
    out = await bridge._wavespeed_generate({
        "prompt": "continue from tail frame",
        "model": "doubao-seedance-1-5-pro-251215",
        "images": ["http://localhost/files/a.png"],
        "duration": 8,
        "resolution": "720p",
    })
    assert out["video_url"].endswith("/out.mp4")
    assert out["model_family"] == "seedance_1_5"
    assert "v15" in calls
    assert calls["v15"][0][0].endswith("/a.png")


@pytest.mark.asyncio
async def test_wavespeed_generate_dispatches_seedance_25_multi_reference_t2v(monkeypatch):
    from app.chat.v2 import provider_bridge as bridge

    calls = {}

    async def _fake_resolve(urls):
        return list(urls)

    class _Svc:
        async def create_seedance_2_5_t2v_task(self, **kwargs):
            calls["create"] = kwargs
            return "task-25"

        async def create_seedance_2_5_i2v_task(self, **kwargs):
            raise AssertionError("reference images must not force i2v mode")

        async def poll_seedance_video_task_until_complete(self, *args, **kwargs):
            calls["poll"] = (args, kwargs)
            return SimpleNamespace(
                video_url="http://cdn/seedance-25.mp4",
                model_dump=lambda: {"video_url": "http://cdn/seedance-25.mp4"},
            )

    monkeypatch.setattr(bridge, "_resolve_media_urls", _fake_resolve)
    monkeypatch.setattr(
        "app.llm.wavespeed_service.get_wavespeed_service", lambda: _Svc(),
    )
    out = await bridge._wavespeed_generate({
        "prompt": "product commercial",
        "model": "seedance-2.5",
        "generation_mode": "i2v",
        "images": ["https://cdn/a.png", "https://cdn/b.png"],
        "duration": 30,
        "resolution": "1080p",
        "generate_audio": True,
    })

    assert out["model_family"] == "seedance_2_5"
    assert calls["create"]["duration"] == 30
    assert calls["create"]["reference_images"] == [
        "https://cdn/a.png", "https://cdn/b.png",
    ]
    assert out["generation_mode"] == "t2v"
    assert out["start_image_url"] is None


@pytest.mark.asyncio
async def test_wavespeed_generate_uses_explicit_start_frame_for_seedance_25_i2v(monkeypatch):
    from app.chat.v2 import provider_bridge as bridge

    calls = {}

    async def _fake_resolve(urls):
        return list(urls)

    class _Svc:
        async def create_seedance_2_5_i2v_task(self, **kwargs):
            calls["create"] = kwargs
            return "task-25-i2v"

        async def create_seedance_2_5_t2v_task(self, **kwargs):
            raise AssertionError("an explicit start frame must force i2v")

        async def poll_seedance_video_task_until_complete(self, *args, **kwargs):
            calls["poll"] = (args, kwargs)
            return SimpleNamespace(
                video_url="http://cdn/continued.mp4",
                model_dump=lambda: {"video_url": "http://cdn/continued.mp4"},
            )

    monkeypatch.setattr(bridge, "_resolve_media_urls", _fake_resolve)
    monkeypatch.setattr(
        "app.llm.wavespeed_service.get_wavespeed_service", lambda: _Svc(),
    )
    out = await bridge._wavespeed_generate({
        "prompt": "continue the unresolved action",
        "model": "seedance-2.5",
        "start_image_url": "https://cdn/tail.png",
        "images": ["https://cdn/tail.png"],
        "duration": 15,
        "resolution": "1080p",
    })

    assert calls["create"]["image"] == "https://cdn/tail.png"
    assert calls["create"]["last_image"] is None
    assert out["generation_mode"] == "i2v"
    assert out["start_image_url"] == "https://cdn/tail.png"
    assert out["reference_image_count"] == 0


@pytest.mark.asyncio
async def test_wavespeed_generate_only_uses_explicit_end_frame(monkeypatch):
    from app.chat.v2 import provider_bridge as bridge

    calls = {}

    async def _fake_resolve(urls):
        return list(urls)

    class _Svc:
        async def create_seedance_2_5_i2v_task(self, **kwargs):
            calls["create"] = kwargs
            return "task-25-frames"

        async def poll_seedance_video_task_until_complete(self, *args, **kwargs):
            return SimpleNamespace(
                video_url="http://cdn/frames.mp4",
                model_dump=lambda: {"video_url": "http://cdn/frames.mp4"},
            )

    monkeypatch.setattr(bridge, "_resolve_media_urls", _fake_resolve)
    monkeypatch.setattr(
        "app.llm.wavespeed_service.get_wavespeed_service", lambda: _Svc(),
    )
    await bridge._wavespeed_generate({
        "prompt": "move between two approved frames",
        "model": "seedance-2.5",
        "start_image_url": "https://cdn/start.png",
        "end_image_url": "https://cdn/end.png",
        "images": [],
    })

    assert calls["create"]["image"] == "https://cdn/start.png"
    assert calls["create"]["last_image"] == "https://cdn/end.png"


@pytest.mark.asyncio
@pytest.mark.parametrize("model", ["seedance-2.0", "seedance-2.5"])
async def test_wavespeed_rejects_silently_dropping_identity_references(monkeypatch, model):
    from app.chat.v2 import provider_bridge as bridge
    from unittest.mock import AsyncMock

    service = SimpleNamespace(
        create_seedance_2_i2v_task=AsyncMock(),
        create_seedance_2_5_i2v_task=AsyncMock(),
        poll_seedance_video_task_until_complete=AsyncMock(return_value=SimpleNamespace(
            video_url="https://cdn/existing.mp4",
        )),
    )
    monkeypatch.setattr(bridge, "_resolve_media_urls", AsyncMock(side_effect=lambda urls: urls))
    monkeypatch.setattr("app.llm.wavespeed_service.get_wavespeed_service", lambda: service)
    profile = {
        "model": model, "prompt": "Continue from the tail, retaining the original cast",
        "start_image_url": "https://cdn/tail.png",
        "images": ["https://cdn/identity.png", "https://cdn/scene.png"],
    }
    with pytest.raises(ValueError, match="unsupported_start_frame_with_references"):
        await bridge._wavespeed_generate(profile)
    service.create_seedance_2_i2v_task.assert_not_called()
    service.create_seedance_2_5_i2v_task.assert_not_called()
    # Already-submitted legacy jobs must still reconcile without a new charge.
    await bridge._wavespeed_generate({**profile, "remote_operation_id": "already-submitted"})
    service.poll_seedance_video_task_until_complete.assert_awaited_once()
    service.create_seedance_2_i2v_task.assert_not_called()
    service.create_seedance_2_5_i2v_task.assert_not_called()


def test_system_skills_register_provider_and_media_concat():
    registry = build_registry(include_platform=True)
    assert registry.get("api.provider.generate").service_target == "api_provider_generate"
    assert registry.get("media.concat").service_target == "media_concat"
    assert registry.get("media.audio_trim").service_target == "media_audio_trim"
    assert registry.get("media.audio_analyze").service_target == "media_audio_analyze"
    assert registry.get("media.video_analyze").service_target == "media_video_analyze"
    assert registry.get("media.video_analyze").output_type == "videomap"
    assert registry.get("media.audio_cut").service_target == "media_audio_cut"
    assert registry.get("media.mix_audio").service_target == "media_mix_audio"


def test_mv_skill_is_instruction_only_workflow():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "skills" / "external"
    catalog = SkillCatalog([root])
    catalog.discover()
    skill = catalog.load("mv")
    assert skill.contract is None
    assert "media.audio_analyze" in skill.instructions
    assert "media.hyperframes_caption" in skill.instructions
    assert (root / "mv" / "reference.md").is_file()


def test_seedance2_skill_remains_instruction_only_without_sandbox_bundle():
    from pathlib import Path

    root = (
        Path(__file__).resolve().parents[1]
        / "skills"
        / "external"
    )
    if not (root / "seedance2" / "SKILL.md").is_file():
        pytest.skip("seedance2 Skill is not installed in this checkout")
    catalog = SkillCatalog([root])
    catalog.discover()
    skill = catalog.load("seedance2")
    assert skill.contract is None
    assert not (root / "seedance2" / "run" / "__main__.py").exists()
    assert "scripts/seedance.py" in skill.instructions
