"""Platform-owned atomic capability descriptions.

These are execution contracts, not Skills: they contain no prompt methodology,
creative knowledge, or workflow fragments.
"""

from __future__ import annotations

from app.capabilities.models import CapabilityInputs, CapabilityManifest, default_terminal_events


def _manifest(
    capability_id: str,
    description: str,
    executor: str,
    output_type: str,
    *,
    alias: str,
    target_agent: str | None = None,
    service_target: str | None = None,
    mode: str | None = None,
    required: list[str] | None = None,
    optional: list[str] | None = None,
    parameters_schema: dict | None = None,
) -> CapabilityManifest:
    return CapabilityManifest(
        id=capability_id,
        description=description,
        executor=executor,
        target_agent=target_agent,
        service_target=service_target,
        mode=mode,
        # Kept only as a backwards-compatible command alias. It no longer
        # means that the capability is loaded from a Skill package.
        skill_name=alias,
        inputs=CapabilityInputs(required=required or [], optional=optional or []),
        output_type=output_type,
        terminal_events=default_terminal_events(output_type),
        parameters_schema=parameters_schema or {},
        trust_level="trusted",
    )


def platform_capabilities() -> list[CapabilityManifest]:
    """Return platform-owned atomic execution capabilities."""
    return [
        _manifest(
            "runtime.artifact.persist",
            "Persist Agent-authored structured or textual planning content as a durable project Artifact without invoking another model.",
            "local.service",
            "document",
            alias="runtime-artifact-persist",
            parameters_schema={
                "type": "object",
                "required": ["content"],
                "properties": {
                    "content": {},
                    "title": {"type": "string"},
                },
                "additionalProperties": True,
            },
        ),
        _manifest("atomic.text.generate", "Generate one text artifact directly from the final prompt. Media model IDs are never used for this language-model call.", "atomic.direct", "text", alias="atomic-text", optional=["text", "image"], parameters_schema={"type": "object", "required": ["prompt"], "properties": {"prompt": {"type": "string", "minLength": 1}, "llm_model": {"type": "string", "description": "Optional OpenAI language-model override"}, "model": {"type": "string", "description": "Legacy text-model override; media model IDs are ignored"}, "artifact_title": {"type": "string"}}, "additionalProperties": True}),
        _manifest("atomic.image.generate", "Generate one image directly from the final prompt and explicit references.", "atomic.direct", "image", alias="atomic-image", optional=["text", "image"], parameters_schema={"type": "object", "required": ["prompt"], "properties": {"prompt": {"type": "string", "minLength": 1}, "model": {"type": "string"}, "resolution": {"type": "string", "enum": ["480p", "720p", "1080p"]}, "aspect_ratio": {"type": "string", "enum": ["16:9", "9:16", "1:1"]}, "images": {"type": "array", "items": {"type": "string"}, "description": "Image URIs or ArtifactVersion ids sent into the model. depends_on only schedules; it does not attach pixels."}, "reference_from_steps": {"type": "array", "items": {"type": "string"}, "description": "Plan step ids whose image artifacts are sent into the model as references."}, "artifact_title": {"type": "string"}}, "additionalProperties": True}),
        _manifest(
            "atomic.music.generate",
            "Generate one music artifact directly from the final prompt.",
            "atomic.direct",
            "music",
            alias="atomic-music",
            parameters_schema={
                "type": "object",
                "required": ["prompt"],
                "properties": {
                    "prompt": {
                        "type": "string",
                        "minLength": 1,
                        "description": (
                            "A music description when auto_lyrics=true or both lyric flags are "
                            "false; complete structured lyrics with [Verse]/[Chorus] sections "
                            "only when has_lyrics=true."
                        ),
                    },
                    "has_lyrics": {
                        "type": "boolean",
                        "description": (
                            "True only when prompt already contains complete structured lyrics. "
                            "Never combine with auto_lyrics."
                        ),
                    },
                    "auto_lyrics": {
                        "type": "boolean",
                        "description": (
                            "True when the provider should write lyrics from a music description. "
                            "Requires has_lyrics=false."
                        ),
                    },
                    "target_duration": {"type": "integer", "minimum": 10, "maximum": 360},
                    "tags": {"type": "string"},
                    "vocal_gender": {"type": "string", "enum": ["f", "m"]},
                    "mv": {"type": "string"},
                    "artifact_title": {"type": "string"},
                },
                "allOf": [{
                    "not": {
                        "required": ["has_lyrics", "auto_lyrics"],
                        "properties": {
                            "has_lyrics": {"const": True},
                            "auto_lyrics": {"const": True},
                        },
                    },
                }],
                "additionalProperties": True,
            },
        ),
        _manifest("atomic.video.generate", "Generate one video directly from the final prompt and explicit references. Use start_image_url for a strict opening frame; generic images remain identity/style references.", "atomic.direct", "video", alias="atomic-video", optional=["image", "music", "video"], parameters_schema={"type": "object", "required": ["prompt"], "properties": {"prompt": {"type": "string", "minLength": 1}, "provider": {"type": "string"}, "model": {"type": "string"}, "generation_mode": {"type": "string", "enum": ["t2v", "i2v", "image_to_video", "image-to-video"]}, "duration": {"type": "integer"}, "resolution": {"type": "string"}, "aspect_ratio": {"type": "string"}, "generate_audio": {"type": "boolean"}, "start_image_url": {"type": "string", "description": "Strict first-frame input for image-to-video generation"}, "end_image_url": {"type": "string", "description": "Optional strict last-frame input; never inferred from generic references"}, "images": {"type": "array", "items": {"type": "string"}}, "videos": {"type": "array", "items": {"type": "string"}}, "audios": {"type": "array", "items": {"type": "string"}}, "artifact_title": {"type": "string"}}, "additionalProperties": True}),
        _manifest(
            "suno.generate",
            "Generate one Suno track with native API fields (lyrics/prompt, tags, custom_mode, make_instrumental, mv, vocal_gender, title). Default is a sung song, not instrumental. Does not go through the music agent.",
            "local.service",
            "music",
            alias="suno-generate",
            service_target="suno_generate",
            optional=["text"],
            parameters_schema={
                "type": "object",
                "properties": {
                    "custom_mode": {
                        "type": "boolean",
                        "default": False,
                        "description": (
                            "False = simple mode (prompt is a description, lyrics "
                            "auto-generated). True = custom mode (prompt is exact "
                            "lyrics, tags/title required)."
                        ),
                    },
                    "make_instrumental": {
                        "type": "boolean",
                        "default": False,
                        "description": (
                            "True for instrumental only (no vocals), false for vocals."
                        ),
                    },
                    "prompt": {
                        "type": "string",
                        "maxLength": 3000,
                        "description": (
                            "In simple mode: a description of desired music. The "
                            "vendor rejects this field at 400 characters or more "
                            "(HTTP 400 validation_error on gpt_description_prompt), "
                            "so keep it to 399 or fewer. In custom mode: the exact "
                            "lyrics to sing (max 3000 chars)."
                        ),
                    },
                    "tags": {
                        "type": "string",
                        "description": (
                            "Style Box in custom mode (max 200 chars): sung voice "
                            "first, then mood, genre, instruments, tempo."
                        ),
                    },
                    "title": {
                        "type": "string",
                        "maxLength": 80,
                        "description": (
                            "Song title. Used in custom mode only (max 80 chars)."
                        ),
                    },
                    "mv": {
                        "type": "string",
                        "default": "chirp-v5-5",
                        "description": (
                            "Suno model version. V4 = 4min max, V4_5/V5 = 8min max."
                        ),
                    },
                    "vocal_gender": {
                        "type": "string",
                        "enum": ["f", "m"],
                        "description": (
                            "The same sung voice as tags, as f or m. chirp-v4-5+."
                        ),
                    },
                    "duration": {
                        "type": "integer",
                        "minimum": 10,
                        "maximum": 360,
                        "description": (
                            "Optional target song length in seconds. The track lands "
                            "close to the request, not exactly on it, so still open a "
                            "window with media.audio_analyze / media.audio_cut."
                        ),
                    },
                },
                # The 400-character cap only applies to simple mode, where prompt
                # becomes the vendor's gpt_description_prompt. In custom mode the
                # same field carries the lyrics and stays long.
                "if": {"not": {"properties": {"custom_mode": {"const": True}}}},
                "then": {"properties": {"prompt": {"maxLength": 399}}},
                "additionalProperties": True,
            },
        ),
        _manifest("actions.suggest", "Produce structured recommended next actions.", "local.structured", "action_suggestions", alias="suggest-actions", service_target="action_suggestions"),
        _manifest(
            "media.concat",
            "Concatenate an ordered list of videos. Set transition_duration for a short cross-fade between continuation clips.",
            "local.service",
            "video",
            alias="media-concat",
            service_target="media_concat",
            required=["video"],
            parameters_schema={
                "type": "object",
                "anyOf": [
                    {"required": ["video_urls"]},
                    {"required": ["video_steps"]},
                ],
                "properties": {
                    "video_urls": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                    "video_steps": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                    "normalize": {"type": "boolean"},
                    "transition_duration": {"type": "number", "minimum": 0, "maximum": 1, "default": 0},
                    "run_id": {"type": "string"},
                },
                "additionalProperties": False,
            },
        ),
        _manifest("media.extract_frame", "Extract a still frame from a video. Use position=last for continuation generation; it resolves the true final decoded video frame.", "local.service", "image", alias="media-extract-frame", service_target="media_extract_frame", required=["video"], parameters_schema={"type": "object", "properties": {"timestamp": {"type": "number", "minimum": 0}, "position": {"type": "string", "enum": ["timestamp", "last"], "default": "timestamp"}, "video_url": {"type": "string"}, "source_video_step": {"type": "string"}, "format": {"type": "string", "enum": ["jpeg", "png"], "default": "jpeg"}, "run_id": {"type": "string"}}, "additionalProperties": False}),
        _manifest(
            "media.audio_trim",
            "Trim an audio URL to [start, start+duration). Optional fade_in_sec/fade_out_sec use trim-with-fade. Required for Seedance MV reference clips (total audio ≤15s).",
            "local.service",
            "music",
            alias="media-audio-trim",
            service_target="media_audio_trim",
            optional=["music"],
            parameters_schema={
                "type": "object",
                "anyOf": [
                    {"required": ["audio_url", "duration"]},
                    {"required": ["audio_step"]},
                ],
                "properties": {
                    "audio_url": {"type": "string"},
                    "audio_step": {"type": "string"},
                    "analysis_step": {"type": "string"},
                    "start": {"type": "number", "minimum": 0, "default": 0},
                    "start_sec": {"type": "number", "minimum": 0},
                    "duration": {"type": "number", "exclusiveMinimum": 0},
                    "duration_sec": {"type": "number", "exclusiveMinimum": 0},
                    "fade_in_sec": {"type": "number", "minimum": 0},
                    "fade_out_sec": {"type": "number", "minimum": 0},
                    "run_id": {"type": "string"},
                },
                "additionalProperties": False,
            },
        ),
        _manifest(
            "media.audio_analyze",
            "Listen to a music track with the v1 hybrid/Gemini transcription, then (when target_duration_sec is set) run v1 smart_clip to recommend a window. Returns sections, timed lyrics, mood, and smart_clip.recommended. Typed as audiomap so it does not shadow the music slot. Does not cut files.",
            "local.service",
            "audiomap",
            alias="media-audio-analyze",
            service_target="media_audio_analyze",
            optional=["music"],
            parameters_schema={
                "type": "object",
                "anyOf": [
                    {"required": ["audio_url"]},
                    {"required": ["audio_step"]},
                ],
                "properties": {
                    "audio_url": {"type": "string"},
                    "audio_step": {"type": "string"},
                    "target_duration_sec": {"type": "number", "exclusiveMinimum": 0},
                    "clip_id": {"type": "string", "description": "Suno clip_id so hybrid can skip upload."},
                    "generated_lyrics": {"type": "string"},
                    "filename": {"type": "string"},
                    "user_input": {"type": "string"},
                    "transcription": {"type": "object", "description": "Reuse an existing v1 transcript."},
                    "run_id": {"type": "string"},
                },
                "additionalProperties": False,
            },
        ),
        _manifest(
            "media.video_analyze",
            "Watch a source video with Gemini and return a structured videomap (summary, theme, characters, timed storyboard, production, visual elements). The planning model cannot see video pixels. Does not generate or edit video.",
            "local.service",
            "videomap",
            alias="media-video-analyze",
            service_target="media_video_analyze",
            optional=["video"],
            parameters_schema={
                "type": "object",
                "anyOf": [
                    {"required": ["video_url"]},
                    {"required": ["video_step"]},
                    {"required": ["source_video_step"]},
                ],
                "properties": {
                    "video_url": {"type": "string"},
                    "video_step": {"type": "string"},
                    "source_video_step": {"type": "string"},
                    "question": {
                        "type": "string",
                        "description": "Optional follow-up. First analysis can omit this.",
                    },
                    "filename": {"type": "string"},
                    "user_input": {"type": "string"},
                    "run_id": {"type": "string"},
                },
                "additionalProperties": False,
            },
        ),
        _manifest(
            "media.audio_cut",
            "Trim [start_sec, start_sec+duration) into a master clip. Optional segments[] are the reference clips for generate (start_sec + duration each, ≤15s). Omit segments only when the master window is already ≤15s (one clip). Longer windows require segments. Pass start_sec and duration, or pin the audiomap artifact and omit them to use smart_clip.recommended. Typed as audio_cut so it does not shadow music or audiomap. Does not transcribe or pick a window.",
            "local.service",
            "audio_cut",
            alias="media-audio-cut",
            service_target="media_audio_cut",
            optional=["music", "audiomap"],
            parameters_schema={
                "type": "object",
                "properties": {
                    "audio_url": {"type": "string"},
                    "audio_step": {"type": "string"},
                    "analysis_step": {"type": "string"},
                    "start_sec": {"type": "number", "minimum": 0},
                    "start": {"type": "number", "minimum": 0},
                    "duration": {"type": "number", "exclusiveMinimum": 0},
                    "duration_sec": {"type": "number", "exclusiveMinimum": 0},
                    "max_segment_sec": {"type": "number", "minimum": 1, "maximum": 15, "default": 15},
                    "segments": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "start_sec": {"type": "number", "minimum": 0},
                                "start": {"type": "number", "minimum": 0},
                                "duration": {"type": "number", "exclusiveMinimum": 0},
                                "duration_sec": {"type": "number", "exclusiveMinimum": 0},
                            },
                        },
                        "description": "Director-chosen reference clips. Required when the master window is over 15s.",
                    },
                    "analysis": {"type": "object", "description": "media.audio_analyze artifact; used for lyrics and as the default window."},
                    "audiomap": {"type": "object"},
                    "transcription": {"type": "object"},
                    "run_id": {"type": "string"},
                },
                "additionalProperties": False,
            },
        ),
        _manifest(
            "media.mix_audio",
            "Mix a master audio track onto a video. mode=replace (default, MV) swaps in the track; mode=overlay ducks/mixes with in-clip audio.",
            "local.service",
            "video",
            alias="media-mix-audio",
            service_target="media_mix_audio",
            required=["video"],
            optional=["music", "audio_cut"],
            parameters_schema={
                "type": "object",
                "anyOf": [
                    {"required": ["video_url", "audio_url"]},
                    {"required": ["video_step", "audio_step"]},
                ],
                "properties": {
                    "video_url": {"type": "string"},
                    "audio_url": {"type": "string"},
                    "music_url": {"type": "string"},
                    "video_step": {"type": "string"},
                    "audio_step": {"type": "string"},
                    "mode": {"type": "string", "enum": ["replace", "overlay"], "default": "replace"},
                    "audio_volume": {"type": "number", "minimum": 0, "maximum": 2, "default": 0.35},
                    "loop_audio": {"type": "boolean", "default": False},
                    "run_id": {"type": "string"},
                },
                "additionalProperties": False,
            },
        ),
        _manifest(
            "media.transcribe",
            "Transcribe the selected video's audio into a persisted timestamped transcript. Use as the first subtitle stage.",
            "local.service",
            "transcript",
            alias="media-transcribe",
            service_target="media_transcribe",
            required=["video"],
            parameters_schema={
                "type": "object",
                "properties": {
                    "video_url": {"type": "string"},
                    "video_step": {"type": "string"},
                    "language": {"type": "string"},
                    "model": {"type": "string"},
                    "prompt": {"type": "string", "description": "Known lyrics or names to guide audio recognition; never a substitute for listening."},
                    "run_id": {"type": "string"},
                },
                "additionalProperties": False,
            },
        ),
        _manifest(
            "subtitle.compose",
            "Create and validate a durable SRT, VTT, or ASS subtitle artifact from a timestamped transcript.",
            "local.service",
            "subtitle",
            alias="subtitle-compose",
            service_target="subtitle_compose",
            required=["transcript"],
            parameters_schema={
                "type": "object",
                "properties": {
                    "cues": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "required": ["start", "end", "text"],
                            "properties": {
                                "start": {"type": "number", "minimum": 0},
                                "end": {"type": "number", "exclusiveMinimum": 0},
                                "text": {"type": "string", "minLength": 1},
                            },
                            "additionalProperties": False,
                        },
                    },
                    "transcription_step": {"type": "string"},
                    "format": {"type": "string", "enum": ["srt", "vtt", "ass"]},
                    "timing_mode": {
                        "type": "string",
                        "enum": ["audio", "manual"],
                        "default": "audio",
                    },
                    "max_lines": {"type": "integer", "minimum": 1, "maximum": 3},
                    "max_chars_per_line": {"type": "integer", "minimum": 4, "maximum": 100},
                    "max_cps": {"type": "number", "exclusiveMinimum": 0, "maximum": 100},
                    "run_id": {"type": "string"},
                },
                "additionalProperties": False,
            },
        ),
        _manifest(
            "media.subtitle_burn",
            "Burn a selected subtitle artifact into a selected video and persist a new captioned MP4.",
            "local.service",
            "video",
            alias="media-subtitle-burn",
            service_target="media_subtitle_burn",
            required=["video", "subtitle"],
            parameters_schema={
                "type": "object",
                "properties": {
                    "video_url": {"type": "string"},
                    "subtitle_url": {"type": "string"},
                    "video_step": {"type": "string"},
                    "subtitle_step": {"type": "string"},
                    "style_preset": {
                        "type": "string",
                        "enum": ["short-video-bold", "clean", "minimal"],
                        "default": "clean",
                    },
                    "position": {
                        "type": "string",
                        "enum": ["bottom-safe", "bottom", "center", "top"],
                        "default": "bottom-safe",
                    },
                    "font_name": {"type": "string", "maxLength": 80},
                    "run_id": {"type": "string"},
                },
                "additionalProperties": False,
            },
        ),
        _manifest(
            "media.hyperframes_caption",
            "Render HyperFrames captions from Agent-authored HTML over a selected video.",
            "local.service",
            "video",
            alias="media-hyperframes-caption",
            service_target="media_hyperframes_caption",
            required=["video"],
            optional=["transcript"],
            parameters_schema={
                "type": "object",
                "properties": {
                    "video_url": {"type": "string"},
                    "video_step": {"type": "string"},
                    "transcription_step": {"type": "string"},
                    "caption_html": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 500000,
                        "description": "HyperFrames HTML for the caption layer.",
                    },
                    "composition_html": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 500000,
                        "description": "Optional full host index.html. Source footage is staged as assets/source.mp4.",
                    },
                    "run_id": {"type": "string"},
                },
                "anyOf": [
                    {"required": ["caption_html"]},
                    {"required": ["composition_html"]},
                ],
                "additionalProperties": False,
            },
        ),
        _manifest(
            "media.hyperframes_render",
            "Render a complete deterministic MP4 from self-contained HyperFrames HTML. "
            "This capability is opt-in and does not call a video-generation provider.",
            "local.service",
            "final_video",
            alias="media-hyperframes-render",
            service_target="media_hyperframes_render",
            parameters_schema={
                "type": "object",
                "required": ["composition_html", "duration"],
                "properties": {
                    "composition_html": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 500000,
                        "description": (
                            "Complete self-contained HyperFrames HTML. Use only local inline "
                            "CSS/SVG and assets/gsap.min.js; remote URLs and browser network APIs "
                            "are rejected."
                        ),
                    },
                    "width": {"type": "integer", "minimum": 320, "maximum": 4096, "default": 1920},
                    "height": {"type": "integer", "minimum": 320, "maximum": 4096, "default": 1080},
                    "duration": {"type": "number", "exclusiveMinimum": 0, "maximum": 300},
                    "fps": {"type": "integer", "minimum": 12, "maximum": 60, "default": 30},
                    "title": {"type": "string", "maxLength": 200},
                },
                "additionalProperties": False,
            },
        ),
    ]
