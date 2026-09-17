"""observability.build_ls_run_config / extract_context_metadata 单测。"""
from __future__ import annotations

from dataclasses import dataclass

from app.services.agent.utils.observability import (
    LS_TAGS_KEY,
    LSMeta,
    LSPhase,
    LSTag,
    build_ls_run_config,
    extract_context_metadata,
)


@dataclass
class _FakeVideoCtx:
    audio_url: str = "https://cdn.example.com/path/song_clip.mp3"
    duration: int = 5
    end_image_url: str | None = None
    character_ref_image_urls: list[str] | None = None


def test_extract_context_metadata_audio_and_duration():
    meta = extract_context_metadata(_FakeVideoCtx())
    assert meta[LSMeta.HAS_AUDIO.value] is True
    assert meta[LSMeta.AUDIO_URL_TAIL.value] == "song_clip.mp3"
    assert meta[LSMeta.DURATION.value] == 5


def test_build_config_metadata_tags_and_run_name():
    cfg = build_ls_run_config(
        log_context={
            LSMeta.PHASE.value: LSPhase.VIDEO_TOOL_EXEC.value,
            LSMeta.SHOT_NUMBER.value: 7,
            LSMeta.RUN_ID.value: "r1",
            LS_TAGS_KEY: [LSTag.VIDEO, LSTag.LIPSYNC],
        },
        invoke_context=_FakeVideoCtx(),
    )
    md = cfg["metadata"]
    assert md[LSMeta.SHOT_NUMBER.value] == 7
    assert md[LSMeta.RUN_ID.value] == "r1"
    assert md[LSMeta.HAS_AUDIO.value] is True
    # phase + 粗分类 tag 都在 tags，且 ls_tags 不进 metadata
    assert "video_tool_execution" in cfg["tags"]
    assert "video" in cfg["tags"] and "lipsync" in cfg["tags"]
    assert LS_TAGS_KEY not in md
    assert cfg["run_name"] == "video_tool_execution_shot_7"


def test_build_config_merges_base_config_without_clobber():
    cfg = build_ls_run_config(
        log_context={LSMeta.PHASE.value: LSPhase.MUSIC_GEN.value},
        base_config={"recursion_limit": 11, "tags": ["preexisting"]},
    )
    assert cfg["recursion_limit"] == 11
    assert "preexisting" in cfg["tags"]
    assert "music_generation" in cfg["tags"]


def test_build_config_returns_base_when_nothing_to_add():
    assert build_ls_run_config(None, None, base_config=None) is None
    assert build_ls_run_config({}, None, base_config={"recursion_limit": 5}) == {
        "recursion_limit": 5
    }
