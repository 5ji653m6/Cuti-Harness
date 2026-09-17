from __future__ import annotations

from pydantic import BaseModel, Field


HIDDEN_FROM_PROMPT = frozenset({
    "media.audio_trim",
})

CAPABILITY_ALIASES = {
    "atomic-text": "atomic.text.generate",
    "atomic-image": "atomic.image.generate",
    "atomic-music": "atomic.music.generate",
    "atomic-video": "atomic.video.generate",
    "suggest-actions": "actions.suggest",
    "api-provider-bridge": "api.provider.generate",
    "media-concat": "media.concat",
    "media-extract-frame": "media.extract_frame",
    "media-transcribe": "media.transcribe",
    "subtitle-compose": "subtitle.compose",
    "media-subtitle-burn": "media.subtitle_burn",
    "media.subtitle.compose": "subtitle.compose",
    "media.subtitle.burn": "media.subtitle_burn",
    "media-hyperframes-caption": "media.hyperframes_caption",
    "media-hyperframes-render": "media.hyperframes_render",
    "ark-wavespeed-protocol-bridge": "api.ark_protocol.generate",
    "suno-generate": "suno.generate",
    "media-audio-cut": "media.audio_cut",
    "media-audio-analyze": "media.audio_analyze",
    "media-video-analyze": "media.video_analyze",
    "media.video.analyze": "media.video_analyze",
}


def canonical_capability_id(capability_id: str) -> str:
    return CAPABILITY_ALIASES.get(capability_id, capability_id)


class CapabilityInputs(BaseModel):
    required: list[str] = Field(default_factory=list)
    soft: list[str] = Field(default_factory=list)
    optional: list[str] = Field(default_factory=list)


class CapabilityManifest(BaseModel):
    id: str
    description: str
    executor: str
    target_agent: str | None = None
    service_target: str | None = None
    mode: str | None = None
    skill_name: str | None = None
    inputs: CapabilityInputs = Field(default_factory=CapabilityInputs)
    output_type: str
    terminal_events: list[str] = Field(default_factory=list)
    progress_events: list[str] = Field(default_factory=list)
    enabled: bool = True
    mcp_server: str | None = None
    mcp_tool: str | None = None
    trust_level: str = "trusted"
    bundle_path: str | None = None
    bundle_digest: str | None = None
    parameters_schema: dict = Field(default_factory=dict)
    output_schema: dict = Field(default_factory=dict)
    sandbox: dict | None = None


class CapabilityRegistry:
    def __init__(self, capabilities: list[CapabilityManifest] | None = None):
        initial = default_capabilities() if capabilities is None else capabilities
        self._items = {item.id: item for item in initial}
        self._aliases = dict(CAPABILITY_ALIASES)
        self._refresh_skill_aliases()

    def canonical_id(self, capability_id: str) -> str:
        return self._aliases.get(capability_id, capability_id)

    def get(self, capability_id: str, *, require_enabled: bool = True) -> CapabilityManifest:
        capability = self._items.get(self.canonical_id(capability_id))
        if not capability:
            raise LookupError(f"unknown capability: {capability_id}")
        if require_enabled and not capability.enabled:
            raise ValueError(f"capability is not enabled: {capability_id}")
        return capability

    def list(self, *, include_disabled: bool = False) -> list[CapabilityManifest]:
        return [item for item in self._items.values() if include_disabled or item.enabled]

    def register(self, capability: CapabilityManifest, *, overwrite: bool = False) -> None:
        if capability.id in self._items and not overwrite:
            raise ValueError(f"capability already registered: {capability.id}")
        self._items[capability.id] = capability
        if capability.skill_name:
            self._aliases[capability.skill_name] = capability.id

    def replace_all(self, capabilities: list[CapabilityManifest]) -> None:
        self._items = {item.id: item for item in capabilities}
        self._aliases = dict(CAPABILITY_ALIASES)
        self._refresh_skill_aliases()

    def _refresh_skill_aliases(self) -> None:
        for item in self._items.values():
            if item.skill_name:
                self._aliases[item.skill_name] = item.id

    def prompt_view(self) -> list[dict]:
        return [{
            "id": item.id,
            "accepted_aliases": [
                alias for alias, canonical in CAPABILITY_ALIASES.items()
                if canonical == item.id
            ],
            "description": item.description,
            "required_inputs": item.inputs.required,
            "optional_references": [*item.inputs.soft, *item.inputs.optional],
            "output": item.output_type,
            "executor": item.executor,
            "parameters_schema": item.parameters_schema,
            "trust_level": item.trust_level,
            "enabled": item.enabled,
        } for item in self.list(include_disabled=True)
          if item.enabled and item.id not in HIDDEN_FROM_PROMPT]


def default_terminal_events(output_type: str) -> list[str]:
    return {
        "text": ["story_agent_generated"],
        "image": ["image_agent_generated"],
        "music": ["music_agent_generated"],
        "video": ["video_agent_generated", "video_generated", "final_video_generated"],
        "action_suggestions": ["actions_suggested"],
        "transcript": ["transcript_generated"],
        "subtitle": ["subtitle_generated"],
        "research": ["research_generated"],
    }.get(output_type, [f"{output_type}_generated"])


def default_capabilities() -> list[CapabilityManifest]:
    """Load platform and provider manifests independently of Skills."""
    from app.capabilities.manifests.platform import platform_capabilities
    from app.integrations.providers.manifests import provider_capabilities

    return [
        *platform_capabilities(),
        *provider_capabilities(),
    ]
