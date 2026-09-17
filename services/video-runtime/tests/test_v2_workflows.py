"""Unit tests for selectable Skill workflows."""
from __future__ import annotations

from pathlib import Path

from app.chat.v2.skill_catalog import SkillCatalog
from app.chat.v2.workflows import (
    WORKFLOWS,
    active_workflow,
    capability_requires_workflow,
    configure_workflows,
    inject_workflow_parameters,
    is_workflow_skill,
    parse_explicit_skill_names,
)


LIVE_WORKFLOWS = (
    "mv",
    "seedance2",
    "short-drama-workflow",
    "cuti-product-workflow",
    "cuti-scenario-product-workflow",
)


def _project_skill_catalog() -> SkillCatalog:
    root = Path(__file__).resolve().parents[1]
    catalog = SkillCatalog([
        root / "skills" / "system",
        root / "skills" / "builtin",
        root / "skills" / "external",
    ])
    catalog.discover()
    return catalog


def test_workflow_registry_covers_user_facing_pipelines():
    catalog = _project_skill_catalog()
    configure_workflows(catalog)
    for name in LIVE_WORKFLOWS:
        assert is_workflow_skill(name), name
        assert catalog.has(name)
    assert not is_workflow_skill("generate-outline")
    assert not is_workflow_skill("workflow-keyframe-pipeline")
    assert not is_workflow_skill("workflow-short-drama")
    assert not is_workflow_skill("workflow-direct-video")


def test_parse_explicit_skill_names_accepts_unicode_boundaries():
    assert parse_explicit_skill_names("$cuti-product-workflow") == ["cuti-product-workflow"]
    assert parse_explicit_skill_names("$cuti-product-workflow 这个skill") == ["cuti-product-workflow"]
    assert parse_explicit_skill_names("$cuti-product-workflow，为产品生成广告") == ["cuti-product-workflow"]
    assert parse_explicit_skill_names("使用$cuti-product-workflow这个skill") == ["cuti-product-workflow"]
    assert parse_explicit_skill_names("使用/cuti-product-workflow生成广告") == ["cuti-product-workflow"]


def test_parse_explicit_skill_names_rejects_partial_ascii_tokens():
    assert parse_explicit_skill_names("prefix$cuti-product-workflow") == []
    assert parse_explicit_skill_names("$cuti-product-workflow_suffix") == []


def test_inject_workflow_parameters_stamps_activated_workflow():
    catalog = _project_skill_catalog()
    configure_workflows(catalog)
    spec = WORKFLOWS["mv"]
    merged = inject_workflow_parameters({"prompt": "x"}, spec)
    assert merged["activated_workflow"] == "mv"
    assert merged["prompt"] == "x"


def test_atomic_capabilities_require_a_workflow():
    assert capability_requires_workflow("atomic.video.generate") is True
    assert capability_requires_workflow("media.transcribe") is False
    assert capability_requires_workflow("media.video_analyze") is False
    assert capability_requires_workflow("actions.suggest") is False


def test_active_workflow_picks_first_installed_workflow():
    catalog = _project_skill_catalog()
    configure_workflows(catalog)
    spec = active_workflow(["language-zh", "mv", "suno-song"])
    assert spec is not None
    assert spec.skill_name == "mv"
