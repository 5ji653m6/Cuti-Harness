from pathlib import Path

from app.capabilities.manifests.platform import platform_capabilities
from app.capabilities.models import default_capabilities
from app.chat.v2.skill_catalog import SkillCatalog
from app.integrations.providers.manifests import provider_capabilities


def test_platform_atomic_capabilities_are_not_skill_packages():
    platform = platform_capabilities()
    assert len(platform) == 18
    assert len({item.id for item in platform}) == 18

    root = Path(__file__).resolve().parents[1] / "skills" / "system"
    skill_names = {item.name for item in SkillCatalog([root]).discover()}
    capability_aliases = {item.skill_name for item in platform}
    assert skill_names.isdisjoint(capability_aliases)

    atomic = [item for item in platform if item.id.startswith("atomic.")]
    assert len(atomic) == 4
    assert all(item.executor == "atomic.direct" for item in atomic)
    assert all(item.target_agent is None for item in atomic)
    assert all(item.parameters_schema.get("required") == ["prompt"] for item in atomic)


def test_provider_capabilities_have_dedicated_sources():
    providers = provider_capabilities()
    assert {item.id for item in providers} == {
        "api.provider.generate",
        "api.ark_protocol.generate",
    }

    all_items = default_capabilities()
    assert len(all_items) == 20
    assert len({item.id for item in all_items}) == 20
    assert "video.pipeline.generate" not in {item.id for item in all_items}
    dest_ids = {
        "story.generate", "image.generate", "music.generate", "video.generate",
        "video_gen.generate", "video.edit", "outline.generate", "character.generate",
        "scene.generate", "shot.generate", "keyframe.generate", "shot.video.generate",
        "character.regenerate", "keyframe.regenerate", "shot.video.regenerate",
        "video.assemble",
    }
    assert dest_ids.isdisjoint({item.id for item in all_items})


def test_provider_generate_schema_rejects_vendor_backend_and_requires_model():
    import pytest
    from jsonschema import ValidationError
    from jsonschema.validators import validator_for

    schema = next(
        item.parameters_schema
        for item in provider_capabilities()
        if item.id == "api.provider.generate"
    )
    validator = validator_for(schema)(schema)
    validator.validate({"prompt": "a dancer", "model": "minimax-h3"})
    validator.validate({
        "prompt": "a dancer", "model": "minimax-h3", "provider": "wavespeed",
    })
    image = next(
        item.parameters_schema
        for item in platform_capabilities()
        if item.id == "atomic.image.generate"
    )
    assert "reference_from_steps" in image["properties"]
    with pytest.raises(ValidationError, match="minimax"):
        validator.validate({
            "prompt": "a dancer", "model": "minimax-h3", "provider": "minimax",
        })
    with pytest.raises(ValidationError):
        validator.validate({"prompt": "a dancer"})
