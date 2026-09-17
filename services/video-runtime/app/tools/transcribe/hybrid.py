"""
Hybrid audio transcription: segmentation and text are fully delegated to Gemini; Suno data serves as prompt context and audit fields.

Execution flow (serial):
  1. Suno aligned-lyrics provides word-level timestamps (start/end for each character/word)
  2. Reassemble Suno words into lyric text by breath gaps + word-level MM:SS.mmm anchors, injected as `generated_lyrics` and
     `suno_alignment_context` into the Gemini prompt -> Gemini segments, texts,
     and labels emotion, tempo, sections, vocal_gender against the real lyrics
  3. Use Gemini's output as-is as the final result, applying only the 4 shared post-processing steps from gemini.py
     postprocess_transcription (fill_gaps -> split_section -> merge -> drop sections with no segment overlap)

Design contract ("Gemini is the sole authoritative output; Suno is context only"):
  - Segmentation + text + timestamps: all decided by Gemini; no "use Suno data to correct Gemini" post-processing
  - Suno data: only (a) provides timing/semantic context to Gemini via the prompt; (b) written into
    `additional_data` for downstream queries (`words` / `suno_section_hints` / `suno_vocal_gender_hint`
    / `suno_vocal_mask` / `suno_song_header` / `suno_raw_alignment`）

Historical baggage (removed): there used to be Step 2 endpoint recomputation / Step 4 vocal_presence correction / Step 4.5 micro-merge
  / Step 5 segment.text anchoring and other "two-source comparison correction" logic. Testing showed Suno itself has occasional errors
  (phantom repeats of the same line, boundary-word drift), and mechanical overriding would corrupt Gemini's correct lyrics. Conclusion: two-source
  correction is unworkable; delegate entirely to Gemini's (context-augmented) output, keeping Suno data as corroboration + diagnostic logs.

Graceful degradation (required in production): if any Suno step fails (upload 500 / aligned-lyrics timeout / network / copyright block)
  -> SunoReshaped is empty -> Gemini runs without generated_lyrics -> equivalent to Gemini-only output.

Entry point: `transcribe_audio_with_hybrid()`, whose signature is a superset of `transcribe_audio_with_gemini` (extra `clip_id`),
switchable by `DefaultValues.TRANSCRIPTION_METHOD` in `music_generation_service`.

Design basis (validated on 7 songs in scripts/transcribe_hybrid_prototype_smoke.py:
Chinese/English + vocal/instrumental + Suno generated/upload paths all pass).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import aiohttp

from ...models.video_state import AudioTranscription, AudioSegment, AudioWord, UserOption
from ...models.tool_enums import AudioSegmentGranularity, DefaultValues
from ...utils.time_format import format_sec_to_mmss
from .gemini import (
    transcribe_audio_with_gemini,
    postprocess_transcription,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Suno API call layer (aimusicapi.ai / sunoapi.com sonic namespace)
# ============================================================================

SUNO_BASE_URL = "https://api.sunoapi.com"
SUNO_NAMESPACE = "sonic"  # new Sonic API
SUNO_ALIGNED_LYRICS_MAX_WAIT_SEC = 180  # aligned-lyrics wait cap
SUNO_ALIGNED_LYRICS_POLL_SEC = 6        # poll interval
SUNO_UPLOAD_TIMEOUT_SEC = 60            # single upload HTTP timeout
SUNO_UPLOAD_MAX_ATTEMPTS = 3            # total upload attempts (first + 2 retries), retried only on 5xx / network errors
SUNO_UPLOAD_RETRY_BASE_SEC = 2.0        # exponential backoff base: 2s, 4s


def _suno_headers() -> dict:
    api_key = os.getenv("SUNO_API_KEY")
    if not api_key:
        raise RuntimeError("SUNO_API_KEY 未配置")
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


async def _suno_upload_for_clip_id(
    session: aiohttp.ClientSession,
    audio_url: str,
    *,
    base_url: str = SUNO_BASE_URL,
    namespace: str = SUNO_NAMESPACE,
    max_attempts: int = SUNO_UPLOAD_MAX_ATTEMPTS,
    retry_base_sec: float = SUNO_UPLOAD_RETRY_BASE_SEC,
) -> str:
    """POST /api/v1/sonic/upload, returns clip_id.

    Retries with exponential backoff on 5xx / network errors (3 attempts by default, 2s/4s); 4xx raises immediately without retry.
    Raises RuntimeError after all retries are exhausted, which the caller's try/except turns into graceful degradation.
    """
    endpoint = f"{base_url.rstrip('/')}/api/v1/{namespace}/upload"
    # When using local storage, replace localhost audio with a public URL, otherwise Suno cannot fetch it (object storage passes through automatically)
    from app.utils.media_egress import resolve_outbound_media_url
    audio_url = await resolve_outbound_media_url(audio_url)
    last_err: Optional[str] = None
    for attempt in range(1, max_attempts + 1):
        try:
            async with session.post(endpoint, json={"url": audio_url}, headers=_suno_headers()) as resp:
                text = await resp.text()
                status = resp.status
            if status >= 500:
                last_err = f"HTTP {status}: {text[:300]}"
                if attempt < max_attempts:
                    delay = retry_base_sec * (2 ** (attempt - 1))
                    logger.warning(
                        "🔁 [hybrid/suno] upload %s 第 %d/%d 次失败（5xx），%.1fs 后重试: %s",
                        endpoint, attempt, max_attempts, delay, last_err,
                    )
                    await asyncio.sleep(delay)
                    continue
                raise RuntimeError(f"Suno upload HTTP {status}: {text[:300]}")
            if status >= 400:
                raise RuntimeError(f"Suno upload HTTP {status}: {text[:300]}")
            data = json.loads(text) if text.strip() else {}
        except (aiohttp.ClientError, asyncio.TimeoutError) as net_err:
            last_err = repr(net_err)[:300]
            if attempt < max_attempts:
                delay = retry_base_sec * (2 ** (attempt - 1))
                logger.warning(
                    "🔁 [hybrid/suno] upload 网络错（第 %d/%d 次），%.1fs 后重试: %s",
                    attempt, max_attempts, delay, last_err,
                )
                await asyncio.sleep(delay)
                continue
            raise RuntimeError(f"Suno upload 网络错（已重试 {max_attempts} 次）: {last_err}")
        clip_id = data.get("clip_id") or (data.get("data") or {}).get("clip_id")
        if not clip_id:
            raise RuntimeError(f"Suno upload 未拿到 clip_id: {str(data)[:200]}")
        return clip_id
    raise RuntimeError(f"Suno upload 重试耗尽: {last_err}")


async def _suno_fetch_aligned_lyrics(
    session: aiohttp.ClientSession,
    clip_id: str,
    *,
    base_url: str = SUNO_BASE_URL,
    namespace: str = SUNO_NAMESPACE,
    max_wait_sec: int = SUNO_ALIGNED_LYRICS_MAX_WAIT_SEC,
    poll_interval_sec: int = SUNO_ALIGNED_LYRICS_POLL_SEC,
) -> dict:
    """POST /api/v1/sonic/aligned-lyrics, polls until alignment is available.

    Returns the full payload; the caller uses reshape_suno_alignment(payload) to extract clean words/mask/hints.
    Raises on timeout or 401/403/404; other 5xx/not-ready-yet keep polling until max_wait_sec.
    """
    endpoint = f"{base_url.rstrip('/')}/api/v1/{namespace}/aligned-lyrics"
    started = time.monotonic()
    last_err: Optional[str] = None
    while True:
        async with session.post(endpoint, json={"clip_id": clip_id}, headers=_suno_headers()) as resp:
            text = await resp.text()
            try:
                parsed = json.loads(text) if text.strip() else None
            except json.JSONDecodeError:
                parsed = None
            if resp.status == 200 and parsed is not None:
                code = parsed.get("code")
                alignment = (parsed.get("data") or {}).get("alignment")
                if code in (200, None) and alignment is not None:
                    return parsed
                last_err = parsed.get("message") or text[:200]
            elif resp.status in (401, 403, 404):
                raise RuntimeError(f"Suno aligned-lyrics HTTP {resp.status}: {text[:300]}")
            else:
                last_err = f"HTTP {resp.status}: {text[:200]}"

        if time.monotonic() - started >= max_wait_sec:
            raise TimeoutError(f"Suno aligned-lyrics 超时；最后错误：{last_err}")
        await asyncio.sleep(poll_interval_sec)


# ============================================================================
# Suno raw-alignment cleanup (reshape_suno_alignment)
# ============================================================================

# The 8 Structure Tags listed in the Suno docs (plus Refrain)
_STRUCTURE_TAG_NAMES = (
    "Verse", "Chorus", "Pre-Chorus", "Bridge", "Outro", "Intro", "Hook", "Break", "Refrain",
)
_SECTION_TAG_PATTERN = re.compile(
    r"\[(" + "|".join(re.escape(s) for s in _STRUCTURE_TAG_NAMES) + r")(?:\s*\d+)?\]",
    re.IGNORECASE,
)
# Paired square brackets within a single token ([piano stabs] / [male tenor vocals] / [Verse 1], etc.)
_ANY_BRACKET_PATTERN = re.compile(r"\[[^\]]*\]")
# vocal_gender hints: [male vocals] / [female tenor vocals], etc.
_GENDER_HINT_PATTERN = re.compile(r"\[(male|female)\b[^\]]*vocals?\]", re.IGNORECASE)


@dataclass
class SunoReshaped:
    """Product of cleaning Suno raw alignment. An empty object (defaults) means Suno provided no usable data,
    in which case merge_to_hybrid naturally degrades to Gemini-only output."""
    clean_words: List[AudioWord] = field(default_factory=list)
    section_hints: List[dict] = field(default_factory=list)        # [{type:"Verse 1", start: 0.239}, ...]
    vocal_gender_hint: Optional[str] = None                        # 'f' / 'm' / None
    vocal_mask: List[Tuple[float, float]] = field(default_factory=list)  # merged "has vocals" intervals
    song_header: str = ""                                          # full metadata text extracted from the first token
    raw: dict = field(default_factory=dict)                        # raw return, kept in additional_data for regression


def reshape_suno_alignment(raw_payload: dict, *, mask_gap_threshold: float = 0.3) -> SunoReshaped:
    """5-phase cleanup of Suno raw alignment (see the prototype + _hybrid_gemini_vs_hybrid_compare.md for regression evidence).

    Phase 1 - scan all [Section]/[gender vocals] tags on the **raw** raw_word
              (this must happen before splitting the header / stripping tags, otherwise [Intro]/[Verse 1]/[male tenor vocals] in the first token would be lost)
    Phase 2 - single-token handling:
              - first token: take the part before the last \n as song_header
              - use _ANY_BRACKET_PATTERN to strip **paired** [xxx] within a single token
              - trim \n + extra whitespace
    Phase 3 - **cross-token unpaired-bracket state machine**: Suno may split `[piano stabs]` into ` [piano`/` stabs`/`] X`
              which Phase 2's regex cannot match, handled by a bracket-depth state machine:
              - on a token with `[` but no `]` -> enter "swallow mode", keep the part before `[` in this token
              - in swallow mode: with `]` -> exit, keep the part after `]`; otherwise drop entirely
    Phase 4 - renumber ids into clean_words.
    Phase 5 - merge adjacent word [start, end] into vocal_mask using mask_gap_threshold.
    """
    out = SunoReshaped(raw=raw_payload)
    alignment = (raw_payload.get("data") or {}).get("alignment") or []
    if not alignment:
        return out

    # ===== Phase 1: scan section/gender tags on the raw raw_word (before splitting the header) =====
    for item in alignment:
        raw_w = str(item.get("word") or "")
        start = float(item.get("start_s") or 0.0)
        if not out.vocal_gender_hint:
            gm = _GENDER_HINT_PATTERN.search(raw_w)
            if gm:
                out.vocal_gender_hint = gm.group(1).lower()[0]  # 'm' / 'f'
        for sm in _SECTION_TAG_PATTERN.finditer(raw_w):
            tag = sm.group(0).strip("[]").strip()
            # dedup: merge same-name tags within one token or repeated tags at nearly the same time
            if not any(h["type"].lower() == tag.lower() and abs(h["start"] - start) < 0.5
                       for h in out.section_hints):
                out.section_hints.append({"type": tag, "start": start})

    # ===== Phase 2: single-token handling - split header / strip paired [xxx] / trim =====
    phase2: List[Tuple[str, float, float]] = []
    for i, item in enumerate(alignment):
        raw_word = str(item.get("word") or "")
        start = float(item.get("start_s") or 0.0)
        end = float(item.get("end_s") or start)

        word = raw_word
        if i == 0 and "\n" in word:
            head_part, _, tail_part = word.rpartition("\n")
            if head_part.strip():
                out.song_header = head_part
            word = tail_part

        word = _ANY_BRACKET_PATTERN.sub("", word)
        word = word.replace("\n", " ").strip()
        word = re.sub(r"\s+", " ", word)
        phase2.append((word, start, end))

    # ===== Phase 3: cross-token unpaired-bracket state machine =====
    phase3: List[Tuple[str, float, float]] = []
    in_bracket = False
    for w, s, e in phase2:
        has_open = "[" in w
        has_close = "]" in w
        if in_bracket:
            if has_close:
                tail = w.rpartition("]")[2].strip()
                in_bracket = False
                if "[" in tail:
                    head = tail.partition("[")[0].strip()
                    in_bracket = True
                    if head:
                        phase3.append((head, s, e))
                else:
                    if tail:
                        phase3.append((tail, s, e))
            else:
                continue
        else:
            if has_open and not has_close:
                head = w.partition("[")[0].strip()
                in_bracket = True
                if head:
                    phase3.append((head, s, e))
            elif has_close and not has_open:
                tail = w.rpartition("]")[2].strip()
                if tail:
                    phase3.append((tail, s, e))
            else:
                if w.strip():
                    phase3.append((w, s, e))

    # ===== Phase 4: renumber into clean_words =====
    for idx, (w, s, e) in enumerate(phase3):
        out.clean_words.append(AudioWord(id=idx, word=w, start=s, end=e))

    # ===== Phase 5: vocal_mask =====
    if out.clean_words:
        runs: List[Tuple[float, float]] = []
        cur_s = out.clean_words[0].start
        cur_e = out.clean_words[0].end
        for w in out.clean_words[1:]:
            if w.start - cur_e <= mask_gap_threshold:
                cur_e = max(cur_e, w.end)
            else:
                runs.append((cur_s, cur_e))
                cur_s, cur_e = w.start, w.end
        runs.append((cur_s, cur_e))
        out.vocal_mask = runs

    return out


# ============================================================================
# Gemini AudioTranscription + SunoReshaped -> merge (merge_to_hybrid)
# ============================================================================

def _merge_to_hybrid(
    gemini_tr: AudioTranscription,
    suno: SunoReshaped,
) -> AudioTranscription:
    """Gemini AudioTranscription is the sole authoritative output; Suno data serves only as:
      (a) prompt context fed to Gemini (done before calling Gemini, see transcribe_audio_with_hybrid)
      (b) additional_data audit fields (words/section_hints/vocal_mask/gender_hint) consumed downstream

    Historically this did "Step 2 endpoint recomputation / Step 4 vocal_presence correction / Step 4.5 micro-merge /
    Step 5 segment.text anchoring override" post-processing that "used Suno data to correct Gemini's output". But testing
    showed the Suno API itself has occasional errors (phantom repeats of the same line, boundary words drifting into the next segment), and mechanical override
    would corrupt Gemini's correct lyrics. The conclusion is that two-source comparison correction is unworkable -- **Gemini is authoritative**,
    and Suno is only a strong hint input during the prompt phase.

    This function now does only two things:
      Step 1: additional_data injection (Suno metadata + transcription_method tag)
      Step 3: reuse gemini.py postprocess_transcription_segments (consistent with the Gemini-only path)

    When Suno has no data (empty SunoReshaped), the Suno fields in additional_data are empty and the rest is unchanged.
    """
    hybrid = gemini_tr.model_copy(deep=True)

    # ============ Step 1: additional_data injection (Suno metadata as audit and downstream-consumption fields) ============
    extra = dict(hybrid.additional_data or {})
    extra["transcription_method"] = "hybrid"
    extra["words"] = [w.model_dump() for w in suno.clean_words]
    extra["suno_raw_alignment"] = suno.raw                  # keep for the record
    extra["suno_section_hints"] = suno.section_hints
    extra["suno_vocal_gender_hint"] = suno.vocal_gender_hint
    extra["suno_song_header"] = suno.song_header
    extra["suno_vocal_mask"] = [list(r) for r in suno.vocal_mask]
    hybrid.additional_data = extra

    # ============ Step 3: reuse gemini.py's 4-step post-processing (fully aligned with the Gemini path) ============
    actual_duration = float(extra.get("actual_duration_seconds") or hybrid.duration or 0.0)
    full_sections: List[dict] = list(extra.get("sections") or [])

    n0 = len(hybrid.segments)
    hybrid.segments, full_sections = postprocess_transcription(
        hybrid.segments,
        full_sections or None,
        total_duration=actual_duration,
        fill_gaps_enabled=actual_duration > 0,
    )
    if full_sections:
        extra["sections"] = full_sections
        hybrid.additional_data = extra
    n4 = len(hybrid.segments)

    # ============ Diagnostic log: differences between Gemini's in-segment text and Suno's in-segment char set (observe only, no modification) ============
    # Although Suno data is no longer used to override Gemini text, it is kept as corroboration for "whether Gemini dropped characters".
    # When Gemini text is missing >= 2 Suno in-segment CJK characters, log a warning to help later prompt tuning.
    if suno.clean_words:
        for seg in hybrid.segments:
            if not seg.vocal_presence or not (seg.text or "").strip():
                continue
            seg_words = [w for w in suno.clean_words if seg.start <= w.start < seg.end]
            if not seg_words:
                continue
            suno_cjk = {c for w in seg_words for c in (w.word or "")
                        if "\u4e00" <= c <= "\u9fff" or "\u3400" <= c <= "\u4dbf"}
            gemini_cjk = {c for c in (seg.text or "")
                          if "\u4e00" <= c <= "\u9fff" or "\u3400" <= c <= "\u4dbf"}
            missing_in_gemini = suno_cjk - gemini_cjk
            if len(missing_in_gemini) >= 2:
                logger.warning(
                    "⚠️  [hybrid/diag] seg %s [%.3f,%.3f] Gemini 可能漏字 %s（不修改，仅观测）: gemini=%r",
                    getattr(seg, "id", "?"), seg.start, seg.end,
                    sorted(missing_in_gemini), (seg.text or "")[:80],
                )

    if n0 != n4:
        logger.info(
            "🔧 [hybrid] 后处理 segments 数量变化: in=%d → postprocess=%d",
            n0, n4,
        )

    return hybrid


# ============================================================================
# Main entry: transcribe_audio_with_hybrid
# ============================================================================

async def _run_suno_path(
    audio_url: str,
    clip_id: Optional[str],
    *,
    mask_gap_threshold: float = 0.3,
) -> SunoReshaped:
    """Suno path: decide whether to upload based on whether a clip_id already exists.

    Any error (upload 500 / aligned-lyrics timeout / network) returns an empty SunoReshaped,
    letting _merge_to_hybrid naturally degrade to Gemini-only -- the only correct product behavior
    when a trending song gets blocked by Suno's copyright controls in the user-upload scenario.
    """
    timeout = aiohttp.ClientTimeout(total=300, connect=30)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            cid = clip_id
            if not cid:
                logger.info("⬆️  [hybrid/suno] upload %s", audio_url[:120])
                t0 = time.monotonic()
                try:
                    cid = await _suno_upload_for_clip_id(session, audio_url)
                    logger.info("✅ [hybrid/suno] upload OK clip_id=%s (%.2fs)",
                                cid, time.monotonic() - t0)
                except Exception as e:
                    logger.warning("⚠️  [hybrid/suno] upload 失败，降级到纯 Gemini: %s",
                                   repr(e)[:200])
                    return SunoReshaped()
            else:
                logger.info("ℹ️  [hybrid/suno] 复用 clip_id=%s", cid)
            logger.info("🎤 [hybrid/suno] aligned-lyrics...")
            t0 = time.monotonic()
            payload = await _suno_fetch_aligned_lyrics(session, cid)
            n_tokens = len((payload.get("data") or {}).get("alignment") or [])
            logger.info("✅ [hybrid/suno] aligned-lyrics %d raw token (%.2fs)",
                        n_tokens, time.monotonic() - t0)
        reshaped = reshape_suno_alignment(payload, mask_gap_threshold=mask_gap_threshold)
        logger.info("✅ [hybrid/suno] reshape: %d raw → %d clean words; section_hints=%d; gender=%s",
                    n_tokens, len(reshaped.clean_words),
                    len(reshaped.section_hints), reshaped.vocal_gender_hint or "-")
        return reshaped
    except Exception as e:
        logger.warning("⚠️  [hybrid/suno] aligned-lyrics/reshape 失败，降级到纯 Gemini: %s",
                       repr(e)[:200])
        return SunoReshaped()


# ============================================================================
# Mureka recognize-song (WaveSpeed namespace) -- an alignment provider on par with Suno aligned-lyrics
# ============================================================================

WAVESPEED_BASE_URL = "https://api.wavespeed.ai/api/v3"
MUREKA_RECOGNIZE_MODEL = "mureka-ai/mureka-v7.6/recognize-song"
MUREKA_MAX_WAIT_SEC = 180          # recognize-song result wait cap
MUREKA_POLL_SEC = 2                # poll interval
MUREKA_SUBMIT_TIMEOUT_SEC = 60     # single submit HTTP timeout


def _wavespeed_headers() -> dict:
    api_key = os.getenv("WAVESPEED_API_KEY")
    if not api_key:
        raise RuntimeError("WAVESPEED_API_KEY 未配置")
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


async def _mureka_submit(
    session: aiohttp.ClientSession,
    audio_url: str,
    *,
    base_url: str = WAVESPEED_BASE_URL,
    model: str = MUREKA_RECOGNIZE_MODEL,
) -> str:
    """POST /{model}, submits a recognition task, returns a WaveSpeed task id. 4xx/5xx raise immediately for upstream degradation."""
    endpoint = f"{base_url.rstrip('/')}/{model}"
    # When using local storage, replace localhost audio with a public URL, otherwise Mureka (WaveSpeed) cannot fetch it (object storage passes through automatically)
    from app.utils.media_egress import resolve_outbound_media_url
    audio_url = await resolve_outbound_media_url(audio_url)
    async with session.post(endpoint, json={"audio": audio_url}, headers=_wavespeed_headers()) as resp:
        text = await resp.text()
        status = resp.status
    if status >= 400:
        raise RuntimeError(f"Mureka recognize-song 提交 HTTP {status}: {text[:300]}")
    data = json.loads(text) if text.strip() else {}
    task_id = (data.get("data") or {}).get("id") or data.get("id")
    if not task_id:
        raise RuntimeError(f"Mureka recognize-song 未拿到 task id: {str(data)[:200]}")
    return task_id


async def _mureka_fetch_output(session: aiohttp.ClientSession, output) -> dict:
    """outputs[0] may be a JSON file URL or inline JSON (dict / str); parse uniformly to a dict."""
    if isinstance(output, dict):
        return output
    s = str(output).strip()
    if s.startswith("{"):
        return json.loads(s)
    async with session.get(output) as resp:
        resp.raise_for_status()
        text = await resp.text()
    return json.loads(text)


async def _mureka_poll_result(
    session: aiohttp.ClientSession,
    task_id: str,
    *,
    base_url: str = WAVESPEED_BASE_URL,
    max_wait_sec: int = MUREKA_MAX_WAIT_SEC,
    poll_interval_sec: int = MUREKA_POLL_SEC,
) -> dict:
    """GET /predictions/{task_id}/result, polls until completed and takes the recognition JSON from outputs[0].

    completed -> parse outputs[0] and return; failed/401/403/404 raise; others keep polling until max_wait_sec.
    """
    endpoint = f"{base_url.rstrip('/')}/predictions/{task_id}/result"
    started = time.monotonic()
    last_err: Optional[str] = None
    while True:
        async with session.get(endpoint, headers=_wavespeed_headers()) as resp:
            text = await resp.text()
            try:
                parsed = json.loads(text) if text.strip() else None
            except json.JSONDecodeError:
                parsed = None
            if resp.status == 200 and parsed is not None:
                data = parsed.get("data") or {}
                status = data.get("status")
                if status == "completed":
                    outputs = data.get("outputs") or []
                    if not outputs:
                        raise RuntimeError("Mureka recognize-song 完成但无 outputs")
                    return await _mureka_fetch_output(session, outputs[0])
                if status == "failed":
                    raise RuntimeError(f"Mureka recognize-song 失败: {data.get('error')}")
                last_err = f"status={status}"
            elif resp.status in (401, 403, 404):
                raise RuntimeError(f"Mureka recognize-song HTTP {resp.status}: {text[:300]}")
            else:
                last_err = f"HTTP {resp.status}: {text[:200]}"

        if time.monotonic() - started >= max_wait_sec:
            raise TimeoutError(f"Mureka recognize-song 超时；最后错误：{last_err}")
        await asyncio.sleep(poll_interval_sec)


def reshape_mureka_recognition(raw_payload: dict, *, mask_gap_threshold: float = 0.3) -> SunoReshaped:
    """Clean Mureka recognize-song output into a SunoReshaped isomorphic to Suno's, so downstream prompt assembly/merge needs no changes.

    Mureka output (milliseconds): lyrics_sections[].lines[].words[] = {start, end, text}
      - flatten all words, ms->seconds, trim text (Mureka occasionally has trailing whitespace/noise tokens like "X "/"Y ")
      - vocal_mask uses the same algorithm as Suno (merge adjacent words with gap <= mask_gap_threshold)
      - Mureka provides no song-structure tags / vocal gender -> section_hints / vocal_gender_hint left empty (does not affect the main flow)
    Returns an empty SunoReshaped on empty payload / no words, letting hybrid naturally degrade to Gemini-only.
    """
    out = SunoReshaped(raw=raw_payload)
    sections = raw_payload.get("lyrics_sections") or []
    idx = 0
    for sec in sections:
        for line in (sec.get("lines") or []):
            for w in (line.get("words") or []):
                text = str(w.get("text") or "").strip()
                if not text:
                    continue
                start = float(w.get("start") or 0) / 1000.0
                raw_end = w.get("end")
                end = float(raw_end) / 1000.0 if raw_end is not None else start
                if end < start:
                    end = start
                out.clean_words.append(AudioWord(id=idx, word=text, start=start, end=end))
                idx += 1

    if out.clean_words:
        runs: List[Tuple[float, float]] = []
        cur_s = out.clean_words[0].start
        cur_e = out.clean_words[0].end
        for w in out.clean_words[1:]:
            if w.start - cur_e <= mask_gap_threshold:
                cur_e = max(cur_e, w.end)
            else:
                runs.append((cur_s, cur_e))
                cur_s, cur_e = w.start, w.end
        runs.append((cur_s, cur_e))
        out.vocal_mask = runs

    return out


async def _run_mureka_path(
    audio_url: str,
    *,
    mask_gap_threshold: float = 0.3,
) -> SunoReshaped:
    """Mureka path: submit -> poll -> reshape. No upload step (audio_url is passed directly).

    Any error (submit 4xx/5xx / poll timeout / network) returns an empty SunoReshaped,
    letting transcribe_audio_with_hybrid naturally degrade to Gemini-only (the same graceful-degradation contract as the Suno path).
    """
    timeout = aiohttp.ClientTimeout(total=300, connect=30)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            logger.info("🎤 [hybrid/mureka] recognize-song submit %s", audio_url[:120])
            t0 = time.monotonic()
            task_id = await _mureka_submit(session, audio_url)
            logger.info("✅ [hybrid/mureka] submit OK task_id=%s (%.2fs)",
                        task_id, time.monotonic() - t0)
            t0 = time.monotonic()
            payload = await _mureka_poll_result(session, task_id)
            logger.info("✅ [hybrid/mureka] recognize-song 完成 (%.2fs)", time.monotonic() - t0)
        reshaped = reshape_mureka_recognition(payload, mask_gap_threshold=mask_gap_threshold)
        logger.info("✅ [hybrid/mureka] reshape: %d clean words", len(reshaped.clean_words))
        return reshaped
    except Exception as e:
        logger.warning("⚠️  [hybrid/mureka] recognize-song 失败，降级到纯 Gemini: %s",
                       repr(e)[:200])
        return SunoReshaped()


def _word_has_ascii_letter(w: str) -> bool:
    """Whether a word contains an ASCII letter (used to decide whether to insert a space when concatenating adjacent words)."""
    return any(c.isascii() and c.isalpha() for c in w)


def _seconds_to_mmss(sec: float) -> str:
    """Convert to MM:SS.mmm, consistent with the prompt output-format contract, so Gemini does not face both seconds and MM:SS.

    Internally reuses the global `format_sec_to_mmss`, keeping display consistent across hybrid / database_utils /
    main_character_design / smart_clip.
    """
    return format_sec_to_mmss(sec)


_SUNO_LONG_SILENCE_SEC = 0.6  # a gap >= 0.6s between words is treated as a breath/pause, explicitly marked in the word list


def _build_suno_alignment_context(
    suno: SunoReshaped,
    *,
    granularity: Optional[AudioSegmentGranularity] = None,
) -> Optional[str]:
    """Assemble Suno alignment **facts only** for Gemini (no craft guidance essays).

    Data blocks:
      1. section_hints (type + start MM:SS.mmm)
      2. vocal_gender_hint (f|m)
      3. word list with timestamps; gaps ≥ 0.6s as `(silence X.XXXs)` lines

    Craft (how to use words / silence for phrase|sentence|beat) lives in
    ``prompts/media/audio-transcription-director`` — Suno word-alignment mode.

    Returns None when Suno has no clean_words (hybrid falls back to lyrics-only).
    ``granularity`` kept for call-site compat; unused (skill reads facts.granularity).
    """
    _ = granularity
    if not suno.clean_words:
        return None

    parts: List[str] = ["# suno_alignment_facts", ""]

    if suno.section_hints:
        parts.append("## section_hints")
        for h in suno.section_hints:
            parts.append(f"- type={h['type']} start={_seconds_to_mmss(float(h['start']))}")
        parts.append("")

    if suno.vocal_gender_hint in ("f", "m"):
        parts.append(f"## vocal_gender_hint")
        parts.append(f"- {suno.vocal_gender_hint}")
        parts.append("")

    parts.append("## words")
    parts.append(f"# silence_gap_threshold_sec={_SUNO_LONG_SILENCE_SEC}")
    words = suno.clean_words
    prev_end = words[0].start
    for w in words:
        gap = w.start - prev_end
        if gap >= _SUNO_LONG_SILENCE_SEC:
            parts.append(f"  (silence {gap:.3f}s)")
        start = _seconds_to_mmss(w.start)
        end = _seconds_to_mmss(w.end)
        parts.append(f"- [{start} - {end}] {w.word}")
        prev_end = w.end
    parts.append("")

    return "\n".join(parts)


def _assemble_lyrics_from_suno_words(
    words: List[AudioWord],
    *,
    line_break_gap_sec: float = 0.6,
) -> str:
    """Reassemble the clean words from Suno aligned-lyrics into lyric text in time order,
    for use in Gemini's prompt `generated_lyrics` field.

    Line-break strategy: a gap > line_break_gap_sec (default 600ms) between adjacent words ends a line and inserts a break.
    This is an empirical value from observing Suno's actual output -- for both Chinese and English lyrics, a "line break" almost always corresponds to a clear breath pause.

    Inter-word spacing strategy (decided per pair, no longer a global switch):
      - if the current or previous word contains an ASCII letter (English/syllable) -> insert a space: "Ha"+"X" -> "Ha X"
      - if both words are pure CJK / punctuation -> no space: "A"+"B" -> "AB"

    This way mixed CN/EN songs (Suno splits Chinese by character and English by syllable) reassemble closest to normal lyric form,
    so Gemini sees "Ha ah ah follow the beat" instead of "Ha ah ah f o l l o w", giving more accurate segment semantics.
    """
    if not words:
        return ""

    lines: List[List[str]] = [[]]
    prev_end = words[0].start
    for w in words:
        if w.start - prev_end > line_break_gap_sec and lines[-1]:
            lines.append([])
        lines[-1].append(w.word)
        prev_end = w.end

    def _join_line(tokens: List[str]) -> str:
        if not tokens:
            return ""
        out = tokens[0]
        for tok in tokens[1:]:
            need_space = _word_has_ascii_letter(tok) or _word_has_ascii_letter(out[-1] if out else "")
            out += (" " + tok) if need_space else tok
        return out

    return "\n".join(_join_line(line) for line in lines if line)


def _build_alignment_fallback_transcription(
    audio_url: str,
    filename: Optional[str],
    alignment: SunoReshaped,
    *,
    generated_lyrics: Optional[str],
    alignment_provider: str,
    granularity: AudioSegmentGranularity,
    split_gap_sec: float = 0.8,
    max_segment_sec: float = 10.0,
) -> Optional[AudioTranscription]:
    """When Gemini is unavailable, build a minimal usable transcription from the existing word-level alignment.

    This fallback only keeps the main flow going; it does not try to replace Gemini's song-structure, emotion, and visual analysis.
    Segmentation prefers clear pauses and caps single-segment length so lipsync downstream never receives over-long segments.
    """
    words = sorted(alignment.clean_words, key=lambda item: (item.start, item.end))
    if not words:
        return None

    groups: List[List[AudioWord]] = []
    current: List[AudioWord] = []
    for word in words:
        if current:
            gap = float(word.start) - float(current[-1].end)
            current_duration = float(current[-1].end) - float(current[0].start)
            if gap >= split_gap_sec or current_duration >= max_segment_sec:
                groups.append(current)
                current = []
        current.append(word)
    if current:
        groups.append(current)

    segments: List[AudioSegment] = []
    for group in groups:
        start = max(0.0, float(group[0].start))
        end = max(start, float(group[-1].end))
        text = _assemble_lyrics_from_suno_words(group, line_break_gap_sec=split_gap_sec).replace("\n", " ").strip()
        segments.append(
            AudioSegment(
                id=len(segments),
                start=start,
                end=end,
                duration=end - start,
                text=text,
                emotion=None,
                tempo=None,
                vocal_presence=bool(text),
                vocal_gender=alignment.vocal_gender_hint,
            )
        )

    duration = max(float(words[-1].end), max((segment.end for segment in segments), default=0.0))
    if duration <= 0 or not segments:
        return None

    assembled_text = (generated_lyrics or _assemble_lyrics_from_suno_words(words)).strip()
    ascii_letters = sum(1 for char in assembled_text if char.isascii() and char.isalpha())
    cjk_chars = sum(1 for char in assembled_text if "\u3400" <= char <= "\u9fff")
    language = "en" if ascii_letters >= cjk_chars else "zh"
    additional_data = {
        "transcription_method": "hybrid_alignment_fallback",
        "transcription_outcome": "fallback_alignment_only",
        "alignment_provider": alignment_provider,
        "audio_segment_granularity": granularity.value,
        "actual_duration_seconds": duration,
        "words": [word.model_dump() for word in words],
        "suno_raw_alignment": alignment.raw,
        "suno_section_hints": alignment.section_hints,
        "suno_vocal_gender_hint": alignment.vocal_gender_hint,
        "suno_song_header": alignment.song_header,
        "suno_vocal_mask": [list(item) for item in alignment.vocal_mask],
        "sections": [],
        "fallback_reason": "gemini_unavailable",
    }
    return AudioTranscription(
        task="transcribe",
        language=language,
        duration=duration,
        text=assembled_text,
        segments=segments,
        audio_url=audio_url,
        filename=filename,
        is_instrumental=False,
        additional_data=additional_data,
    )


async def transcribe_audio_with_hybrid(
    audio_url: str,
    *,
    clip_id: Optional[str] = None,
    user_option: Optional[UserOption] = None,
    fill_gaps: bool = True,
    user_input: Optional[str] = None,
    filename: Optional[str] = None,
    generated_lyrics: Optional[str] = None,
    granularity: Optional[AudioSegmentGranularity] = None,
    music_intent: Optional[str] = None,
    music_workflow_mode: Optional[str] = None,
    language_contract: Optional[dict] = None,
) -> Optional[AudioTranscription]:
    """Hybrid transcription entry (a superset signature fully compatible with `transcribe_audio_with_gemini`).

    Execution mode: **Suno first -> Gemini transcribes with Suno lyrics -> merge** (serial).
      1. First run Suno aligned-lyrics to get word-level timestamps + section_hints + vocal_gender_hint
      2. Reassemble Suno words into lyric text by breath gaps (`_assemble_lyrics_from_suno_words`),
         injected as `generated_lyrics` into Gemini's prompt -- so Gemini "transcribes while looking at the real lyrics",
         making segment semantics/sections/vocal_gender labels fit the lyric structure better (measured: vocal_gender doubled / segments +39%)
      3. Merge: recompute each segment's start/end + vocal_presence from the "in-segment Suno word set", with a fallback when gender is missing,
         running gemini.py's 4-step post-processing to guarantee the full-coverage contract; **timing follows Suno, segmentation follows Gemini**

    Auto graceful degradation on Suno failure: Suno upload/aligned-lyrics failure -> empty SunoReshaped ->
    Gemini runs without lyrics (behaving like Gemini-only), transparent to downstream.

    Routing:
      - clip_id provided (Suno generated path): fetch aligned-lyrics directly, no upload, latency ~ 87s
      - clip_id=None (user upload path): first Suno upload to get clip_id, then fetch aligned-lyrics, latency ~ 127s

    The return schema is **identical** to `transcribe_audio_with_gemini`. Downstream code consuming AudioTranscription
    needs no changes at all.
    """
    # the alignment provider is switched by DefaultValues.ALIGNMENT_PROVIDER (only effective for hybrid):
    # - "suno":   Suno upload + aligned-lyrics (historical default)
    # - "mureka": Mureka V7.6 recognize-song (WaveSpeed, no upload; no song-structure/gender hint)
    # both return SunoReshaped; downstream generated_lyrics + alignment_context injection is identical.
    alignment_provider = (DefaultValues.ALIGNMENT_PROVIDER or "suno").lower()
    logger.info(
        "🎬 [hybrid] ===== 开始 hybrid 转录（串行：%s→Gemini）===== | audio_url=%s | clip_id=%s | filename=%s",
        alignment_provider, audio_url[:120], clip_id or "(none)", filename or "-",
    )
    t0 = time.monotonic()

    # ===== Step 1: alignment provider path, get word-level timestamps (Suno also includes section_hints + gender_hint) =====
    if alignment_provider == "mureka":
        suno_result = await _run_mureka_path(audio_url)
    else:
        suno_result = await _run_suno_path(audio_url, clip_id)

    # ===== Step 2: build the two Suno reference materials for Gemini =====
    # 2a) generated_lyrics: the traditional lyric text (compatible with callers that already have lyrics, e.g. the Suno generate path)
    # 2b) suno_alignment_context: Suno's "alignment truth", with word-level timestamped line-broken lyrics + section_hints + gender_hint
    # -- key constraint: "one lyric line must fall within one segment", so Gemini does not split "down/come on" into two
    gemini_generated_lyrics = generated_lyrics
    lyrics_source = "user_provided" if generated_lyrics else None
    if not gemini_generated_lyrics and suno_result.clean_words:
        gemini_generated_lyrics = _assemble_lyrics_from_suno_words(suno_result.clean_words)
        lyrics_source = f"{alignment_provider}_aligned_lyrics"

    # granularity is resolved by the caller (music_generation_service) from TRANSCRIPTION_METHOD_CONFIG and passed in explicitly;
    # falls back to DefaultValues when not passed (same source as gemini._resolve_granularity).
    _granularity = AudioSegmentGranularity.from_value(
        granularity if granularity is not None else DefaultValues.AUDIO_SEGMENT_GRANULARITY
    )
    suno_alignment_context = _build_suno_alignment_context(suno_result, granularity=_granularity)

    if gemini_generated_lyrics:
        n_lines = gemini_generated_lyrics.count("\n") + 1
        n_chars = len(gemini_generated_lyrics)
        logger.info(
            "🎵 [hybrid] Gemini 将使用 generated_lyrics 做参考转录 | source=%s | lines=%d | chars=%d | preview=%r",
            lyrics_source, n_lines, n_chars,
            (gemini_generated_lyrics[:80] + "...") if n_chars > 80 else gemini_generated_lyrics,
        )
    else:
        logger.info(
            "ℹ️  [hybrid] Suno 未提供歌词（失败/纯音乐），Gemini 不带参考歌词跑（等同纯 Gemini 行为）"
        )
    if suno_alignment_context:
        logger.info(
            "🧭 [hybrid] 已附加 Suno 对齐真相上下文给 Gemini prompt | chars=%d | section_hints=%d | gender_hint=%s",
            len(suno_alignment_context),
            len(suno_result.section_hints),
            suno_result.vocal_gender_hint or "-",
        )

    # ===== Step 3: Gemini path, consuming Suno lyrics + alignment truth =====
    t_g = time.monotonic()
    gemini_result = await transcribe_audio_with_gemini(
        audio_url,
        user_option=user_option,
        fill_gaps=fill_gaps,
        user_input=user_input,
        filename=filename,
        generated_lyrics=gemini_generated_lyrics,
        suno_alignment_context=suno_alignment_context,
        granularity=_granularity,
        music_intent=music_intent,
        music_workflow_mode=music_workflow_mode,
        language_contract=language_contract,
    )
    logger.info(
        "⏱️  [hybrid] 串行耗时 总=%.2fs；其中 Gemini=%.2fs；Suno words=%d",
        time.monotonic() - t0, time.monotonic() - t_g, len(suno_result.clean_words),
    )

    if not gemini_result:
        fallback = _build_alignment_fallback_transcription(
            audio_url,
            filename,
            suno_result,
            generated_lyrics=gemini_generated_lyrics,
            alignment_provider=alignment_provider,
            granularity=_granularity,
        )
        if fallback:
            logger.warning(
                "⚠️  [hybrid] Gemini 返回 None，使用 %s 对齐数据降级继续 | segments=%d words=%d",
                alignment_provider,
                len(fallback.segments),
                len(suno_result.clean_words),
            )
            return fallback
        logger.error("❌ [hybrid] Gemini 返回 None 且无可用对齐数据，hybrid 无法继续")
        return None

    # ===== Step 4: merge -- recompute endpoints from the in-segment Suno word set + vocal_presence + 4-step post-processing =====
    merged = _merge_to_hybrid(gemini_result, suno_result)

    suno_used = bool(suno_result.clean_words) or bool(suno_result.vocal_mask)
    outcome = "hybrid(suno→gemini, lyrics_fed)" if suno_used else "fallback_pure_gemini(suno_unavailable)"
    logger.info(
        "🎬 [hybrid] ===== hybrid 转录完成 ===== | "
        "outcome=%s | segments=%d | words=%d | sections=%d | total_elapsed=%.2fs",
        outcome,
        len(merged.segments),
        len((merged.additional_data or {}).get("words") or []),
        len((merged.additional_data or {}).get("sections") or []),
        time.monotonic() - t0,
    )
    # tag additional_data with method / result for downstream audit / data tracing
    merged.additional_data = dict(merged.additional_data or {})
    merged.additional_data["transcription_method"] = "hybrid"
    merged.additional_data["alignment_provider"] = alignment_provider
    merged.additional_data["transcription_outcome"] = outcome
    merged.additional_data["audio_segment_granularity"] = _granularity.value
    return merged
