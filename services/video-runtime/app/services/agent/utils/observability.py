"""
LangSmith observability: centralized management of tags / metadata / phases.

Why needed: key generation parameters for video / keyframe / character etc. (shot number, audio_url, duration, etc.)
go through the runtime context (``agent.ainvoke(context=...)``) and do not enter the LangSmith trace inputs,
so they are neither visible in the UI nor filterable by shot/phase.

Here we define three enum groups + one ``build_ls_run_config()`` to attach this info as metadata / tags to
"the run newly created by this invoke" (propagated via RunnableConfig, rather than modifying the current run). This way each
call carries its own shot_number etc. without overwriting one another, and it can be viewed and filtered directly in LangSmith.

How to extend (keep it generic and simple):
- new phase -> add an item to ``LSPhase``;
- new filterable field -> add an item to ``LSMeta``;
- new coarse category -> add an item to ``LSTag``.
Callers only need to use these enums' ``.value`` as keys in ``log_context``, without worrying about injection details.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Mapping, Optional


class LSPhase(str, Enum):
    """LLM / tool-call phase. Written into ``metadata['phase']`` and also used as a tag."""

    VIDEO_TOOL_EXEC = "video_tool_execution"
    VIDEO_PROMPT_GEN = "video_prompt_generation"
    VIDEO_PROMPT_EVAL = "video_prompt_eval_fix"
    KEYFRAME_TOOL_EXEC = "keyframe_tool_execution"
    KEYFRAME_PROMPT_GEN = "keyframe_batch_prompts"
    KEYFRAME_PROMPT_EVAL = "keyframe_prompt_eval_fix"
    CHARACTER_IMAGE = "main_character_image"
    CHARACTER_IMAGE_MATCH = "main_character_image_matching"
    MUSIC_GEN = "music_generation"
    OUTLINE_GEN = "outline_generation"
    SCENE_GEN = "scene_generation"
    REGENERATE_VIDEO = "regenerate_video"
    REGENERATE_KEYFRAME = "regenerate_keyframe"
    REGENERATE_CHARACTER = "regenerate_character"


class LSTag(str, Enum):
    """Coarse category tag (fixed enum, for easy tags filtering in the LangSmith UI)."""

    VIDEO = "video"
    KEYFRAME = "keyframe"
    CHARACTER = "character"
    MUSIC = "music"
    OUTLINE = "outline"
    SCENE = "scene"
    LIPSYNC = "lipsync"
    REGENERATE = "regenerate"


class LSMeta(str, Enum):
    """Filterable metadata key (uniform naming, to avoid scattered ad-hoc strings)."""

    PHASE = "phase"
    SHOT_NUMBER = "shot_number"
    BATCH_INDEX = "batch_index"
    RUN_ID = "run_id"
    THREAD_ID = "thread_id"
    CONVERSATION_ID = "conversation_id"
    GENERATION_MODE = "generation_mode"
    VIDEO_TOOL = "video_generation_tool"
    HAS_AUDIO = "has_audio"
    AUDIO_URL_TAIL = "audio_url_tail"
    HAS_END_IMAGE = "has_end_image"
    REF_IMAGE_COUNT = "ref_image_count"
    DURATION = "duration"


# the key used in log_context to carry extra coarse-category tags (list[LSTag|str]); its value is not written into metadata.
LS_TAGS_KEY = "ls_tags"


def _is_scalar(v: Any) -> bool:
    return isinstance(v, (bool, int, float, str))


def extract_context_metadata(context: Any) -> dict[str, Any]:
    """Extract observability fields from create_agent's context (``VideoGenerationContext`` / ``ImageGenerationContext``, etc.).
    These parameters go through the runtime context and are not in the trace inputs, so they must be extracted actively.
    Only lightweight scalars are taken; for URLs only the trailing filename segment is kept, to avoid oversized metadata.
    """
    if context is None:
        return {}
    meta: dict[str, Any] = {}
    audio_url = getattr(context, "audio_url", None)
    if audio_url:
        meta[LSMeta.HAS_AUDIO.value] = True
        meta[LSMeta.AUDIO_URL_TAIL.value] = str(audio_url).split("/")[-1][:80]
    duration = getattr(context, "duration", None)
    if duration is not None:
        meta[LSMeta.DURATION.value] = duration
    if getattr(context, "end_image_url", None):
        meta[LSMeta.HAS_END_IMAGE.value] = True
    ref_urls = getattr(context, "reference_image_urls", None) or getattr(
        context, "character_ref_image_urls", None
    )
    if ref_urls:
        meta[LSMeta.REF_IMAGE_COUNT.value] = len(ref_urls)
    return meta


def build_ls_run_config(
    log_context: Mapping[str, Any] | None = None,
    invoke_context: Any | None = None,
    base_config: Mapping[str, Any] | None = None,
) -> Optional[dict]:
    """Combine ``log_context`` + ``invoke_context`` into RunnableConfig metadata / tags and
    attach them to "the run newly created by this ainvoke" (as opposed to modifying the current run via ``get_current_run_tree``,
    which in concurrent scenarios would write different shots' fields onto the same parent run and overwrite each other).

    - scalars in ``log_context`` go into metadata one by one; ``phase`` is also used as a tag.
    - items in ``log_context[LS_TAGS_KEY]`` (list) are used as extra coarse-category tags, not into metadata.
    - ``invoke_context`` is augmented via ``extract_context_metadata`` with runtime params like audio / duration.
    - when ``shot_number`` is present, ``run_name=f'{phase}_shot_{n}'`` is set automatically, to help distinguish in the UI.
    - merges rather than overwrites ``base_config`` (keeping caller-set recursion_limit / callbacks, etc.).

    Returns the merged dict; if there is nothing to add, returns a copy of ``base_config`` or ``None``.
    """
    meta: dict[str, Any] = {}
    if log_context:
        for k, v in log_context.items():
            if k == LS_TAGS_KEY:
                continue
            if v is not None and _is_scalar(v):
                meta[str(k)] = v
    meta.update(extract_context_metadata(invoke_context))

    extra_tags: list[str] = []
    if log_context:
        for t in log_context.get(LS_TAGS_KEY) or []:
            tv = t.value if isinstance(t, Enum) else str(t)
            if tv:
                extra_tags.append(tv)

    if not meta and not extra_tags:
        return dict(base_config) if base_config else None

    cfg: dict[str, Any] = dict(base_config or {})

    if meta:
        merged_meta = dict(cfg.get("metadata") or {})
        merged_meta.update(meta)
        cfg["metadata"] = merged_meta

    tags = list(cfg.get("tags") or [])
    phase = meta.get(LSMeta.PHASE.value)
    if phase:
        phase = str(phase)
        if phase not in tags:
            tags.append(phase)
    for tv in extra_tags:
        if tv not in tags:
            tags.append(tv)
    if tags:
        cfg["tags"] = tags

    if "run_name" not in cfg and phase:
        sn = meta.get(LSMeta.SHOT_NUMBER.value)
        cfg["run_name"] = f"{phase}_shot_{sn}" if sn is not None else phase

    return cfg
