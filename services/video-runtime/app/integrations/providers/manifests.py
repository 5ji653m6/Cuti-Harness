"""Capability descriptions for platform provider/protocol integrations."""

from app.capabilities.models import CapabilityInputs, CapabilityManifest, default_terminal_events


def provider_capabilities() -> list[CapabilityManifest]:
    return [
        CapabilityManifest(
            id="api.provider.generate",
            description=(
                "Generate video. Set model to the generator id "
                "(minimax-h3, doubao-seedance-2-0, seedance-2.5). "
                "provider is the HTTP backend and may be omitted."
            ),
            executor="local.service",
            service_target="api_provider_generate",
            skill_name="api-provider-bridge",
            inputs=CapabilityInputs(optional=["image", "video", "audio", "music", "audio_cut"]),
            output_type="video",
            terminal_events=default_terminal_events("video"),
            parameters_schema={
                "type": "object",
                "required": ["prompt", "model"],
                "properties": {
                    "prompt": {"type": "string", "minLength": 1},
                    "model": {
                        "type": "string",
                        "enum": [
                            "minimax-h3",
                            "h3",
                            "doubao-seedance-2-0",
                            "doubao-seedance-2-0-260128",
                            "seedance-2.5",
                            "seedance-2.0",
                        ],
                        "description": (
                            "Generator id. H3: minimax-h3 (also h3). "
                            "Seedance: doubao-seedance-2-0 or seedance-2.5."
                        ),
                    },
                    "provider": {
                        "type": "string",
                        "enum": ["wavespeed", "ark"],
                        "description": (
                            "HTTP backend. Optional. Enum: wavespeed, ark. "
                            "Generator ids belong in model."
                        ),
                    },
                    "duration": {"type": "integer"},
                    "resolution": {"type": "string"},
                    "aspect_ratio": {"type": "string"},
                    "generate_audio": {"type": "boolean"},
                    "images": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "References for this shot. Include sources that lock the "
                            "subject, plus setting sheets this shot uses."
                        ),
                    },
                    "videos": {"type": "array", "items": {"type": "string"}},
                    "audios": {"type": "array", "items": {"type": "string"}},
                },
                "additionalProperties": True,
            },
        ),
        CapabilityManifest(
            id="api.ark_protocol.generate",
            description="Translate Ark generation requests to the configured WaveSpeed provider.",
            executor="local.service",
            service_target="ark_protocol_generate",
            skill_name="ark-wavespeed-protocol-bridge",
            inputs=CapabilityInputs(optional=["image", "video", "audio", "music", "audio_cut"]),
            output_type="video",
            terminal_events=default_terminal_events("video"),
            parameters_schema={"type": "object", "required": ["body"], "properties": {"body": {"type": "object"}, "wait": {"type": "boolean"}, "poll_interval": {"type": "number"}}, "additionalProperties": False},
        ),
    ]
