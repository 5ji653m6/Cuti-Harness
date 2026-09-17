from __future__ import annotations

from hashlib import sha256
from typing import Any, Mapping

from app.capabilities.models import CapabilityRegistry
from app.chat.v2.skill_catalog import SkillCatalog
from app.orchestration.workflow_compiler import WorkflowSpec

from .models import ResolvedSkillRef, SkillContext, SkillResolutionRequest


class SkillResolver:
    """Resolve and freeze the installed Skills that apply to one execution step."""

    def __init__(
        self,
        catalog: SkillCatalog,
        capabilities: CapabilityRegistry,
        workflows: Mapping[str, WorkflowSpec] | None = None,
    ) -> None:
        self.catalog = catalog
        self.capabilities = capabilities
        self.workflows = workflows if workflows is not None else {}

    def resolve(
        self,
        request: SkillResolutionRequest,
        *,
        frozen_skills: Mapping[str, tuple[ResolvedSkillRef, str]] | None = None,
    ) -> SkillContext | None:
        """Resolve applicable Skills, reusing a running Build's frozen instructions.

        ``frozen_skills`` is accepted only when the installed Skill still declares
        the version captured by the Project lock. This lets an active Build finish
        after an unversioned on-disk edit without silently adopting the edit. A
        declared version change continues to require an explicit Project upgrade.
        """
        candidates: dict[str, str] = {}
        frozen_skills = frozen_skills or {}
        project_locks = {
            item.skill_id: item for item in request.project_skill_locks if item.enabled
        }
        workflow = (
            self.workflows.get(request.workflow_skill_id)
            if request.workflow_skill_id
            else None
        )
        if request.workflow_skill_id and workflow is None:
            raise LookupError(
                f"workflow Skill is not installed: {request.workflow_skill_id}",
            )
        if workflow is not None:
            candidates[workflow.skill_name] = "workflow"
            for name in workflow.skill_dependencies:
                candidates.setdefault(name, "workflow_dependency")

        for name in request.activated_skill_ids:
            candidates.setdefault(name, "activated")
        for lock in request.project_skill_locks:
            if lock.enabled:
                candidates[lock.skill_id] = "project_lock"
        for name in request.declared_skill_ids:
            candidates[name] = "declared"
        if request.capability_skill_id:
            candidates.setdefault(request.capability_skill_id, "capability")

        refs: list[ResolvedSkillRef] = []
        instruction_blocks: list[str] = []
        for name, source in sorted(candidates.items()):
            if not self.catalog.has(name):
                if source == "capability":
                    continue
                raise LookupError(f"required Skill is not installed: {name}")
            loaded = self.catalog.load(name)
            if not loaded.metadata.enabled:
                raise ValueError(f"required Skill is disabled: {name}")
            frozen = None
            if source == "project_lock":
                from app.domain.skills.service import make_skill_lock

                expected = project_locks[name]
                current = make_skill_lock(expected.project_id, loaded.metadata)
                if current.version != expected.version or current.digest != expected.digest:
                    frozen = frozen_skills.get(name)
                    if (
                        frozen is None
                        or current.version != expected.version
                        or frozen[0].version != expected.version
                    ):
                        raise ValueError(
                            f"project Skill lock is stale: {name}; disable and re-enable it "
                            "to accept the installed version",
                        )
            raw = dict(loaded.metadata.metadata or {})
            roles = list(frozen[0].roles) if frozen else self._roles(raw)
            if not self._matches(
                raw,
                roles=roles,
                source=source,
                capability_id=request.capability_id,
                output_type=request.output_type,
            ):
                continue
            if frozen:
                refs.append(frozen[0].model_copy(update={"source": source}))
                instruction_blocks.append(frozen[1])
            else:
                hooks = self._hooks(raw)
                digest = sha256(loaded.metadata.path.read_bytes()).hexdigest()
                version = str(raw.get("version") or "").strip() or None
                refs.append(ResolvedSkillRef(
                    skill_id=name,
                    version=version,
                    content_hash=digest,
                    roles=roles,
                    hooks=hooks,
                    source=source,
                ))
                instruction_blocks.append(
                    f"Skill `{name}` (roles: {', '.join(roles)}; "
                    f"hooks: {', '.join(hooks)}):\n{loaded.instructions.strip()}"
                )

        if not refs:
            return None
        contract = request.constraint_contract
        image_outputs = {"image", "keyframe", "character", "character_reference"}
        if (
            request.require_constraint_contract
            and request.output_type in image_outputs
            and contract is None
        ):
            raise ValueError(
                f"{request.capability_id} has applied Skills but no model-classified "
                "constraint_contract; refusing to schedule an unenforceable image step",
            )
        if contract is not None:
            resolved_ids = {item.skill_id for item in refs}
            unknown = {
                item.skill_id
                for item in contract.hard_constraints
                if item.skill_id not in resolved_ids
            }
            if unknown:
                raise ValueError(
                    "constraint_contract references Skills not resolved for this step: "
                    + ", ".join(sorted(unknown)),
                )
        return SkillContext(
            instructions="\n\n---\n\n".join(instruction_blocks),
            applied_skills=refs,
            constraint_contract=contract,
        )

    @staticmethod
    def _roles(raw: dict[str, Any]) -> list[str]:
        value = raw.get("roles")
        if isinstance(value, str):
            roles = [value]
        elif isinstance(value, list):
            roles = [str(item) for item in value if str(item).strip()]
        else:
            roles = ["workflow"] if raw.get("kind") == "workflow" else ["guidance"]
        return list(dict.fromkeys(role.strip().lower() for role in roles if role.strip()))

    @staticmethod
    def _hooks(raw: dict[str, Any]) -> list[str]:
        value = raw.get("hooks")
        if isinstance(value, str):
            hooks = [value]
        elif isinstance(value, list):
            hooks = [str(item) for item in value if str(item).strip()]
        else:
            hooks = ["before_step"]
        return list(dict.fromkeys(hook.strip() for hook in hooks if hook.strip()))

    @classmethod
    def _matches(
        cls,
        raw: dict[str, Any],
        *,
        roles: list[str],
        source: str,
        capability_id: str,
        output_type: str,
    ) -> bool:
        if "workflow" in roles and len(roles) == 1:
            return False

        scope = raw.get("scope") or {}
        if isinstance(scope, str):
            scope_type = scope
            scope_selectors: dict[str, Any] = {}
        elif isinstance(scope, dict):
            scope_type = str(scope.get("type") or "").strip()
            scope_selectors = scope.get("selectors") or {}
        else:
            scope_type = ""
            scope_selectors = {}

        if not scope_type:
            if source in {"capability", "declared", "workflow"}:
                scope_type = "stage"
            elif source in {"project_lock", "workflow_dependency"}:
                scope_type = "run"
            else:
                scope_type = "coordinator"
        if scope_type in {"workflow", "coordinator"}:
            return False

        selectors = raw.get("selectors") or scope_selectors or {}
        if not isinstance(selectors, dict):
            return False
        capabilities = cls._string_set(selectors.get("capabilities"))
        outputs = cls._string_set(
            selectors.get("artifact_types") or selectors.get("output_types"),
        )
        if capabilities and capability_id not in capabilities:
            return False
        if outputs and output_type not in outputs:
            return False
        return True

    @staticmethod
    def _string_set(value: Any) -> set[str]:
        if isinstance(value, str):
            return {value.strip()} if value.strip() else set()
        if isinstance(value, list):
            return {str(item).strip() for item in value if str(item).strip()}
        return set()
