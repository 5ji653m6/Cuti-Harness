from __future__ import annotations

import hashlib
import logging

from .models import (
    CAPABILITY_ALIASES,
    CapabilityInputs,
    CapabilityManifest,
    CapabilityRegistry,
    default_capabilities,
    default_terminal_events,
)
from app.chat.v2.skill_catalog import SUPPORTED_EXECUTORS, LoadedSkill, SkillCatalog

logger = logging.getLogger(__name__)


def _payload_digest(skill: LoadedSkill) -> str:
    digest = hashlib.sha256()
    root = skill.metadata.path.parent
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if (
            not path.is_file()
            or relative == "SKILL.md"
            or relative.startswith(".cuti-")
        ):
            continue
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def capability_id_for_skill(skill: LoadedSkill) -> str:
    if skill.contract is None:
        raise ValueError(f"instruction-only skill has no capability: {skill.metadata.name}")
    if skill.contract.capability_id:
        return skill.contract.capability_id
    return CAPABILITY_ALIASES.get(skill.metadata.name, skill.metadata.name.replace("-", "."))


def manifest_from_skill(skill: LoadedSkill) -> CapabilityManifest:
    contract = skill.contract
    if contract is None:
        raise ValueError(f"instruction-only skill has no capability: {skill.metadata.name}")
    capability_id = capability_id_for_skill(skill)
    required = list(contract.required_inputs)
    optional = [item for item in contract.accepts if item not in required]
    enabled = (
        contract.executor in SUPPORTED_EXECUTORS
        and skill.metadata.enabled
    )
    if not enabled:
        logger.warning(
            "Skill %s uses unsupported executor %s; registering disabled",
            skill.metadata.name, contract.executor,
        )
    target_agent = None
    service_target = None
    mcp_server = contract.mcp_server
    mcp_tool = contract.mcp_tool
    if contract.executor == "local.service":
        service_target = contract.target
    elif contract.executor == "mcp.call":
        mcp_server = mcp_server or contract.target
        mcp_tool = mcp_tool or contract.produces
    elif contract.executor == "local.structured":
        service_target = contract.target
    return CapabilityManifest(
        id=capability_id,
        description=skill.metadata.description,
        executor=contract.executor,
        target_agent=target_agent,
        service_target=service_target,
        mode=contract.mode,
        skill_name=skill.metadata.name,
        inputs=CapabilityInputs(required=required, optional=optional),
        output_type=contract.produces,
        terminal_events=default_terminal_events(contract.produces),
        enabled=enabled,
        mcp_server=mcp_server,
        mcp_tool=mcp_tool,
        trust_level=skill.metadata.trust_level,
        bundle_path=str(skill.metadata.path.parent),
        bundle_digest=_payload_digest(skill),
        parameters_schema=contract.parameters_schema,
        output_schema=contract.output_schema,
        sandbox=contract.sandbox.model_dump(mode="json") if contract.sandbox else None,
    )


def build_registry(
    catalog: SkillCatalog | None = None,
    *,
    extra: list[CapabilityManifest] | None = None,
    include_platform: bool | None = None,
) -> CapabilityRegistry:
    """Build from platform manifests plus optional executable Skill contracts."""
    use_platform = catalog is None if include_platform is None else include_platform
    registry = CapabilityRegistry(default_capabilities() if use_platform else [])
    if catalog is not None:
        for metadata in catalog.list_metadata():
            try:
                skill = catalog.load(metadata.name)
                if skill.contract is None:
                    continue
                manifest = manifest_from_skill(skill)
                if manifest.trust_level == "untrusted":
                    try:
                        existing = registry.get(manifest.id, require_enabled=False)
                    except LookupError:
                        existing = None
                    if existing is not None:
                        raise ValueError(
                            f"external skill cannot overwrite capability {manifest.id}"
                        )
                registry.register(
                    manifest,
                    overwrite=manifest.trust_level == "trusted",
                )
            except Exception:
                if metadata.trust_level == "trusted":
                    raise
                logger.exception("Failed to register skill %s", metadata.name)
    if extra:
        for item in extra:
            registry.register(item, overwrite=True)
    return registry


def reload_registry(
    registry: CapabilityRegistry,
    catalog: SkillCatalog,
    *,
    extra: list[CapabilityManifest] | None = None,
    include_platform: bool = False,
) -> CapabilityRegistry:
    catalog.reload()
    rebuilt = build_registry(
        catalog,
        extra=extra,
        include_platform=include_platform,
    )
    registry.replace_all(rebuilt.list(include_disabled=True))
    return registry
