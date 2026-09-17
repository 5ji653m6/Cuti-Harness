from __future__ import annotations

import os
import logging
import re
import tempfile
from pathlib import Path
from typing import Any

from openai import AsyncOpenAI

from app.config import settings as agent_settings
from app.chat.config import get_settings as get_chat_settings
from app.utils import media_service_client as msc


logger = logging.getLogger(__name__)


_TRANSCRIPTION_LANGUAGE_ALIASES = {
    "chinese": "zh",
    "mandarin": "zh",
    "中文": "zh",
    "普通话": "zh",
    "zho": "zh",
    "chi": "zh",
    "english": "en",
    "英文": "en",
    "英语": "en",
    "eng": "en",
}


def normalize_transcription_language(language: str | None) -> str | None:
    """Return the ISO-639-1 code accepted by OpenAI transcription APIs.

    UI and skills commonly provide BCP-47 values such as ``zh-CN`` or
    ``en_US``. OpenAI's ``language`` parameter only accepts a two-letter
    ISO-639-1 code. Unknown labels are omitted so transcription can detect the
    language automatically instead of failing the whole subtitle workflow.
    """
    value = str(language or "").strip().lower()
    if not value or value in {"auto", "detect", "automatic"}:
        return None
    value = _TRANSCRIPTION_LANGUAGE_ALIASES.get(value, value)
    base = re.split(r"[-_]", value, maxsplit=1)[0]
    if re.fullmatch(r"[a-z]{2}", base):
        return base
    logger.warning(
        "Ignoring unsupported transcription language %r; using auto detection",
        language,
    )
    return None


def _object_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        dumped = value.model_dump(mode="json")
        return dumped if isinstance(dumped, dict) else {}
    return {}


def align_segments_to_words(
    segments: list[dict[str, Any]],
    words: list[dict[str, Any]],
    *,
    tail_padding: float = 0.12,
) -> list[dict[str, Any]]:
    """Snap caption onset/offset to detected speech instead of coarse segment bounds."""
    if not words:
        return segments
    aligned: list[dict[str, Any]] = []
    for segment in segments:
        start = float(segment["start"])
        end = float(segment["end"])
        contained = [
            word for word in words
            if start <= (float(word["start"]) + float(word["end"])) / 2 <= end
        ]
        if contained:
            start = float(contained[0]["start"])
            end = float(contained[-1]["end"]) + tail_padding
        aligned.append({"start": start, "end": end, "text": segment["text"]})
    for index in range(len(aligned) - 1):
        next_start = float(aligned[index + 1]["start"])
        if aligned[index]["end"] >= next_start:
            aligned[index]["end"] = max(
                float(aligned[index]["start"]) + 0.05,
                next_start - 0.04,
            )
    return aligned


async def _download_limited(url: str, destination: Path, max_bytes: int) -> int:
    """Fetch via s3_utils.download_file, then enforce the transcription size cap.

    Same contract as Gemini audio: local copies disk, dest/prod uses S3 GetObject.
    """
    from app.utils.s3_utils import s3_utils

    destination.parent.mkdir(parents=True, exist_ok=True)
    ok = await s3_utils.download_file(url, str(destination))
    if not ok:
        raise RuntimeError(f"failed to fetch audio for transcription: {url}")
    written = destination.stat().st_size
    if written > max_bytes:
        destination.unlink(missing_ok=True)
        raise ValueError(
            f"extracted audio exceeds transcription limit ({written} > {max_bytes} bytes)"
        )
    return written


async def transcribe_video(
    video_url: str,
    *,
    run_id: str,
    language: str | None = None,
    model: str | None = None,
    prompt: str | None = None,
) -> dict[str, Any]:
    chat_settings = get_chat_settings()
    api_key = (
        agent_settings.OPENAI_API_KEY
        or chat_settings.DEEP_AGENT_V2_OPENAI_API_KEY
        or os.getenv("OPENAI_API_KEY", "")
    ).strip()
    if not api_key:
        raise RuntimeError(
            "media.transcribe requires OPENAI_API_KEY or DEEP_AGENT_V2_OPENAI_API_KEY"
        )
    selected_model = (model or agent_settings.SUBTITLE_TRANSCRIPTION_MODEL).strip()
    extracted = await msc.audio_extract(video_url, run_id=run_id, fmt="mp3")
    audio_url = str(extracted.get("result_url") or "").strip()
    if not audio_url:
        raise ValueError("the selected video has no transcribable audio stream")

    descriptor, temporary_name = tempfile.mkstemp(prefix="cuti-subtitle-", suffix=".mp3")
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        size = await _download_limited(
            audio_url,
            temporary,
            max(1, int(agent_settings.SUBTITLE_TRANSCRIPTION_MAX_BYTES)),
        )
        arguments: dict[str, Any] = {
            "model": selected_model,
            "response_format": "verbose_json",
        }
        normalized_language = normalize_transcription_language(language)
        if normalized_language:
            arguments["language"] = normalized_language
        if prompt:
            arguments["prompt"] = prompt
        if selected_model == "whisper-1":
            arguments["timestamp_granularities"] = ["word", "segment"]
        keys = [api_key]
        fallback_key = (
            agent_settings.OPENAI_API_KEY_FALLBACK
            or chat_settings.OPENAI_API_KEY_FALLBACK
            or os.getenv("OPENAI_API_KEY_FALLBACK", "")
        ).strip()
        if fallback_key and fallback_key != api_key:
            keys.append(fallback_key)
        response = None
        for index, selected_key in enumerate(keys):
            client = AsyncOpenAI(
                api_key=selected_key,
                base_url=chat_settings.DEEP_AGENT_V2_OPENAI_BASE_URL,
                timeout=300,
            )
            try:
                with temporary.open("rb") as audio_file:
                    response = await client.audio.transcriptions.create(
                        file=audio_file,
                        **arguments,
                    )
                validate_transcription(_object_dict(response))
                break
            except Exception as exc:
                if index + 1 >= len(keys):
                    raise
                logger.warning(
                    "OpenAI transcription primary call failed; retrying once with backup key (%s)",
                    type(exc).__name__,
                )
        if response is None:  # defensive; the loop either returns or raises
            raise RuntimeError("OpenAI transcription returned no response")
        raw = _object_dict(response)
        segments = [_object_dict(item) for item in raw.get("segments") or []]
        words = [_object_dict(item) for item in raw.get("words") or []]
        normalized_segments = [
            {
                "start": float(item.get("start") or 0),
                "end": float(item.get("end") or 0),
                "text": str(item.get("text") or "").strip(),
            }
            for item in segments
            if item.get("text") and float(item.get("end") or 0) > float(item.get("start") or 0)
        ]
        normalized_words = [
            {
                "start": float(item.get("start") or 0),
                "end": float(item.get("end") or 0),
                "word": str(item.get("word") or item.get("text") or "").strip(),
            }
            for item in words
            if item.get("word") or item.get("text")
        ]
        normalized_segments = align_segments_to_words(
            normalized_segments,
            normalized_words,
        )
        if not normalized_segments and raw.get("text"):
            duration = float(raw.get("duration") or 0)
            if duration > 0:
                normalized_segments = [{
                    "start": 0.0,
                    "end": duration,
                    "text": str(raw["text"]).strip(),
                }]
        if not normalized_segments:
            raise RuntimeError("transcription returned no timestamped segments")
        return {
            "title": "Video transcript",
            "summary": str(raw.get("text") or "").strip(),
            "text": str(raw.get("text") or "").strip(),
            "language": raw.get("language") or normalized_language or "unknown",
            "duration": raw.get("duration") or normalized_segments[-1]["end"],
            "segments": normalized_segments,
            "words": normalized_words,
            "timing_source": "word_timestamps" if normalized_words else "segment_timestamps",
            "provider": "openai",
            "model": selected_model,
            "source_video_url": video_url,
            "recognition_prompt": prompt,
            "timing_quality_checked": True,
            "extracted_audio_url": audio_url,
            "audio_bytes": size,
        }
    finally:
        temporary.unlink(missing_ok=True)


def validate_transcription(raw: dict[str, Any]) -> None:
    """Reject unsupported speech timing before it becomes a subtitle Artifact."""
    words = [_object_dict(item) for item in raw.get("words") or []]
    if len(words) >= 8:
        collapsed = sum(
            float(item.get("end") or 0) <= float(item.get("start") or 0)
            for item in words
        )
        if collapsed / len(words) > 0.5:
            raise ValueError(
                "Unreliable transcription: most word timestamps have zero duration. "
                "Re-transcribe with the known lyrics or source-audio context; "
                "do not burn this transcript into the video."
            )
