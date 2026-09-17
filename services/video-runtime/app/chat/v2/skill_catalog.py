from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
import yaml


_FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_CONTRACT = re.compile(r"```cuti-contract\s*\n(.*?)\n```", re.DOTALL)

SUPPORTED_EXECUTORS = frozenset({
    "local.structured",
    "local.service",
    "mcp.call",
    "sandbox.run",
    "atomic.direct",
})
UNTRUSTED_EXECUTORS = frozenset({"sandbox.run"})


def _merge_metadata(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge platform sidecar metadata without editing vendor Skills."""
    merged = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_metadata(merged[key], value)
        else:
            merged[key] = value
    return merged


@dataclass(frozen=True)
class SkillMetadata:
    name: str
    description: str
    path: Path
    trust_level: str = "untrusted"
    enabled: bool = True
    metadata: dict[str, Any] | None = None

    def prompt_view(self) -> dict[str, Any]:
        meta = dict(self.metadata or {})
        return {
            "name": self.name,
            "description": self.description,
            "trust_level": self.trust_level,
            "enabled": self.enabled,
            "metadata": meta,
            "kind": meta.get("kind"),
        }


class SandboxPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entrypoint: str = "run/__main__.py"
    runtime: str = "python3.11"
    base_image: str = "python:3.11-slim"
    timeout_seconds: int = Field(default=120, ge=1, le=900)
    memory_mb: int = Field(default=512, ge=32, le=4096)
    cpus: float = Field(default=1.0, gt=0, le=4)
    pids_limit: int = Field(default=128, ge=16, le=512)
    max_output_bytes: int = Field(default=10 * 1024 * 1024, ge=1024, le=100 * 1024 * 1024)
    network: str = "none"
    allowed_domains: tuple[str, ...] = ()
    allowed_host_capabilities: tuple[str, ...] = (
        "artifact.read",
        "artifact.write",
        "log",
        "progress",
        "http.fetch",
        "http.request",
        "media.concat",
        "media.extract_frame",
        "media.trim",
        "media.speed_adjust",
        "media.audio_trim",
        "media.audio_analyze",
        "media.video_analyze",
        "media.mix_audio",
        "provider.generate",
    )
    allowed_output_mime_types: tuple[str, ...] = (
        "application/json",
        "text/plain",
    )

    @field_validator("entrypoint")
    @classmethod
    def validate_entrypoint(cls, value: str) -> str:
        path = Path(value)
        if path.is_absolute() or ".." in path.parts or not value.strip():
            raise ValueError("sandbox entrypoint must be a safe relative path")
        return path.as_posix()

    @field_validator("network")
    @classmethod
    def validate_network(cls, value: str) -> str:
        if value not in {"none", "allowlist"}:
            raise ValueError("sandbox network must be 'none' or 'allowlist'")
        return value

    @field_validator("allowed_domains")
    @classmethod
    def validate_domains(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = []
        for value in values:
            host = value.strip().lower().rstrip(".")
            if (
                not re.fullmatch(
                    r"(?=.{1,253}\Z)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
                    r"[a-z]{2,63}",
                    host,
                )
                or host == "localhost"
            ):
                raise ValueError(f"allowed domain must be an exact public hostname: {value}")
            normalized.append(host)
        return tuple(dict.fromkeys(normalized))

    @field_validator("runtime", "base_image")
    @classmethod
    def validate_runtime(cls, value: str, info) -> str:
        allowed = {
            "runtime": {"python3.11"},
            "base_image": {"python:3.11-slim"},
        }
        if value not in allowed[info.field_name]:
            raise ValueError(f"unsupported sandbox {info.field_name}: {value}")
        return value

    @model_validator(mode="after")
    def validate_network_policy(self):
        supported = {
            "artifact.read",
            "artifact.write",
            "log",
            "progress",
            "http.fetch",
            "http.request",
            "media.concat",
            "media.extract_frame",
            "media.trim",
            "media.speed_adjust",
            "media.audio_trim",
            "media.audio_analyze",
            "media.video_analyze",
            "media.mix_audio",
            "provider.generate",
        }
        unknown = set(self.allowed_host_capabilities) - supported
        if unknown:
            raise ValueError(f"unsupported host capabilities: {sorted(unknown)}")
        if self.network == "none" and self.allowed_domains:
            raise ValueError("allowed_domains requires network='allowlist'")
        if self.network == "allowlist" and not self.allowed_domains:
            raise ValueError("network='allowlist' requires allowed_domains")
        http_caps = {"http.fetch", "http.request"}
        if self.network == "allowlist" and not (http_caps & set(self.allowed_host_capabilities)):
            raise ValueError(
                "network='allowlist' requires http.fetch or http.request host capability"
            )
        return self


class TrustDeclaration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    level: str = "untrusted"

    @field_validator("level")
    @classmethod
    def validate_level(cls, value: str) -> str:
        if value not in {"trusted", "untrusted"}:
            raise ValueError("trust level must be trusted or untrusted")
        return value


class SkillContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: int = Field(default=1, ge=1, le=1)
    executor: str
    target: str
    produces: str
    accepts: tuple[str, ...] = ()
    capability_id: str | None = None
    mode: str | None = None
    required_inputs: tuple[str, ...] = ()
    parameters_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    mcp_server: str | None = None
    mcp_tool: str | None = None
    bundle_sha256: str | None = None
    signing_key_id: str | None = None
    bundle_signature: str | None = None
    trust: TrustDeclaration | None = None
    sandbox: SandboxPolicy | None = None

    @field_validator("bundle_sha256")
    @classmethod
    def validate_digest(cls, value: str | None) -> str | None:
        if value is not None and not re.fullmatch(r"[0-9a-fA-F]{64}", value):
            raise ValueError("bundle_sha256 must be a 64-character hex digest")
        return value.lower() if value else None

    @model_validator(mode="after")
    def validate_executor_fields(self):
        for schema in (self.parameters_schema, self.output_schema):
            if not schema:
                continue
            from jsonschema.validators import validator_for

            validator_for(schema).check_schema(schema)
        if self.executor not in SUPPORTED_EXECUTORS:
            raise ValueError(f"unsupported executor {self.executor!r}")
        if self.executor == "sandbox.run" and self.sandbox is None:
            raise ValueError("sandbox.run requires a sandbox policy")
        if self.executor == "mcp.call" and not (
            (self.mcp_server or self.target) and (self.mcp_tool or self.produces)
        ):
            raise ValueError("mcp.call requires an MCP server and tool")
        if bool(self.signing_key_id) != bool(self.bundle_signature):
            raise ValueError("signing_key_id and bundle_signature must be provided together")
        return self


@dataclass(frozen=True)
class LoadedSkill:
    metadata: SkillMetadata
    instructions: str
    contract: SkillContract | None = None


class SkillCatalog:
    """Discovers SKILL.md metadata eagerly and loads bodies/contracts on demand."""

    def __init__(self, roots: list[Path | str]):
        self.roots = [Path(root).expanduser().resolve() for root in roots]
        self._metadata: dict[str, SkillMetadata] = {}

    def discover(self) -> list[SkillMetadata]:
        discovered: dict[str, SkillMetadata] = {}
        for root in self.roots:
            if not root.exists():
                continue
            # Builtin Skills are grouped by domain (for example
            # builtin/storytelling/foo/SKILL.md), while system/external Skills
            # are usually one level deep. Recursive discovery makes all three
            # roots first-class without requiring separate Catalog instances.
            for skill_file in sorted(root.rglob("SKILL.md")):
                metadata = self._read_metadata(skill_file)
                if metadata.name in discovered:
                    raise ValueError(f"duplicate skill name: {metadata.name}")
                discovered[metadata.name] = metadata
        self._metadata = discovered
        return sorted(self._metadata.values(), key=lambda item: item.name)

    def reload(self) -> list[SkillMetadata]:
        self._metadata = {}
        return self.discover()

    def list_metadata(self) -> list[SkillMetadata]:
        if not self._metadata:
            return self.discover()
        return sorted(self._metadata.values(), key=lambda item: item.name)

    def has(self, name: str) -> bool:
        if not self._metadata:
            self.discover()
        return name in self._metadata

    def load(self, name: str) -> LoadedSkill:
        if not self._metadata:
            self.discover()
        metadata = self._metadata.get(name)
        if not metadata:
            raise LookupError(f"unknown skill: {name}")
        metadata = self._migrate_legacy_metadata_path(metadata)
        text = metadata.path.read_text(encoding="utf-8")
        frontmatter = _FRONTMATTER.match(text)
        body = text[frontmatter.end():].strip() if frontmatter else text.strip()
        contract_match = _CONTRACT.search(body)
        contract = (
            parse_skill_contract(json.loads(contract_match.group(1)))
            if contract_match
            else None
        )
        if (
            contract is not None
            and metadata.trust_level == "untrusted"
            and contract.executor not in UNTRUSTED_EXECUTORS
        ):
            raise ValueError(
                f"untrusted skill {name} cannot use executor {contract.executor!r}"
            )
        return LoadedSkill(metadata=metadata, instructions=body, contract=contract)

    @staticmethod
    def _migrate_legacy_metadata_path(metadata: SkillMetadata) -> SkillMetadata:
        """Resolve Skill metadata saved before the runtime-root migration.

        Deep Agent checkpoints can outlive a deployment.  Older runs may retain
        metadata that points at ``app/chat/skills/.system/<name>/SKILL.md``,
        while the canonical packages now live under ``services/agent/skills``.
        Do the migration at read time so resuming an old project does not need a
        database/checkpoint rewrite and never falls back to a duplicate runtime
        Skill tree.
        """
        if metadata.path.is_file():
            return metadata

        legacy_parts = metadata.path.as_posix().split("/app/chat/skills/")
        if len(legacy_parts) != 2:
            return metadata
        legacy_scope, _, remainder = legacy_parts[1].partition("/")
        scope_aliases = {
            ".system": "system",
            "system": "system",
            ".builtin": "builtin",
            "builtin": "builtin",
            ".external": "external",
            "external": "external",
        }
        scope = scope_aliases.get(legacy_scope)
        if not scope or not remainder:
            return metadata
        agent_root = Path(__file__).resolve().parents[3]
        canonical = agent_root / "skills" / scope / remainder
        if canonical.is_file():
            return replace(metadata, path=canonical)
        return metadata

    def load_all(self) -> list[LoadedSkill]:
        return [self.load(item.name) for item in self.list_metadata()]

    def skill_files(self) -> dict[str, Path]:
        if not self._metadata:
            self.discover()
        return {
            f"/skills/{item.name}/SKILL.md": item.path
            for item in self._metadata.values()
        }

    def prompt_view(self) -> list[dict[str, Any]]:
        return [
            item.prompt_view()
            for item in self.list_metadata()
            if item.enabled
        ]

    def list_resources(self, name: str) -> list[str]:
        skill = self.load(name)
        root = skill.metadata.path.parent.resolve()
        resources: list[str] = []
        for path in sorted(root.rglob("*")):
            if path.is_symlink() or not path.is_file() or path.name == "SKILL.md":
                continue
            relative = path.relative_to(root).as_posix()
            if relative.startswith(".cuti-") or any(
                part.startswith(".") for part in Path(relative).parts
            ):
                continue
            resources.append(relative)
        return resources

    def read_resource(
        self,
        name: str,
        relative_path: str,
        *,
        max_bytes: int = 256 * 1024,
    ) -> str:
        skill = self.load(name)
        root = skill.metadata.path.parent.resolve()
        requested = Path(str(relative_path).strip().strip("<>").removeprefix("./"))
        if requested.is_absolute() or ".." in requested.parts:
            raise ValueError("skill resource path must be relative")
        path = (root / requested).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ValueError("skill resource escapes its bundle") from exc
        if path.is_symlink() or not path.is_file() or path.name == "SKILL.md":
            raise LookupError(f"unknown skill resource: {relative_path}")
        data = path.read_bytes()
        if len(data) > max_bytes:
            raise ValueError(f"skill resource exceeds {max_bytes} bytes")
        if b"\x00" in data:
            raise ValueError("binary skill resources cannot be loaded into context")
        return data.decode("utf-8")

    @staticmethod
    def _read_metadata(path: Path) -> SkillMetadata:
        text = path.read_text(encoding="utf-8")
        match = _FRONTMATTER.match(text)
        if not match:
            raise ValueError(f"{path} has no YAML frontmatter")
        values = yaml.safe_load(match.group(1))
        if not isinstance(values, dict):
            raise ValueError(f"{path} frontmatter must be a YAML object")
        if "name" not in values or "description" not in values:
            raise ValueError(f"{path} frontmatter must contain name and description")
        name = str(values["name"])
        description = str(values["description"])
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", name):
            raise ValueError(f"invalid skill name in {path}")
        if not description or len(description) > 2048:
            raise ValueError(f"skill description must be 1..2048 characters: {path}")
        if path.parent.name != name:
            raise ValueError(f"skill folder and name differ: {path}")
        extra_metadata = values.get("metadata") or {}
        if not isinstance(extra_metadata, dict):
            raise ValueError(f"skill metadata must be a YAML object: {path}")
        declared_kind = extra_metadata.get("kind")
        # Keep third-party Skill instructions byte-for-byte upstream compatible.
        # A Cuti-owned sidecar may classify and route the Skill without changing
        # its identity, trust level, instructions, or executable contract.
        sidecar_path = path.parent / ".cuti-metadata.yaml"
        if sidecar_path.is_file():
            sidecar_document = yaml.safe_load(
                sidecar_path.read_text(encoding="utf-8")
            ) or {}
            if not isinstance(sidecar_document, dict):
                raise ValueError(f".cuti-metadata.yaml must be a YAML object: {path}")
            sidecar_metadata = sidecar_document.get("metadata") or {}
            if not isinstance(sidecar_metadata, dict):
                raise ValueError(
                    f".cuti-metadata.yaml metadata must be a YAML object: {path}"
                )
            extra_metadata = _merge_metadata(extra_metadata, sidecar_metadata)
            # A sidecar may enrich routing metadata, but executable Workflow
            # identity must be declared by the installed SKILL.md itself. This
            # prevents a prompt-only helper bundle from becoming a user-facing
            # Workflow merely because a stale local adapter says so.
            if (
                sidecar_metadata.get("kind") == "workflow"
                and declared_kind != "workflow"
            ):
                extra_metadata["kind"] = declared_kind or "helper"
                extra_metadata.pop("workflow", None)
                extra_metadata.pop("selectors", None)
                extra_metadata.pop("hooks", None)
                extra_metadata["roles"] = [
                    role for role in extra_metadata.get("roles", [])
                    if role not in {"workflow", "stage_supervisor"}
                ] or ["guidance"]
        # Version is platform metadata, not prompt content. Preserve a top-level
        # declaration so project SkillLocks can reproduce the selected package.
        if "version" in values:
            extra_metadata = {**extra_metadata, "version": str(values["version"])}
        interface_path = path.parent / "agents" / "openai.yaml"
        if interface_path.is_file():
            interface_document = yaml.safe_load(
                interface_path.read_text(encoding="utf-8")
            ) or {}
            if not isinstance(interface_document, dict):
                raise ValueError(f"agents/openai.yaml must be a YAML object: {path}")
            interface = interface_document.get("interface") or {}
            if not isinstance(interface, dict):
                raise ValueError(f"agents/openai.yaml interface must be an object: {path}")
            extra_metadata = {**extra_metadata, "interface": interface}
        # Trust is determined by the *root location*, not by a directory name
        # within an external package.  Otherwise an untrusted package could put
        # its SKILL.md below a directory named `system` and gain privileges.
        agent_root = Path(__file__).resolve().parents[3]
        trusted_roots = (
            agent_root / "skills" / "system",
            agent_root / "skills" / "builtin",
            # Pre-migration compatibility only; new packages must use skills/.
            agent_root / "app" / "chat" / "skills" / ".system",
        )
        resolved_path = path.resolve()
        trusted = any(
            resolved_path.is_relative_to(root.resolve())
            for root in trusted_roots
            if root.exists()
        )
        return SkillMetadata(
            name=name,
            description=description,
            path=path,
            trust_level="trusted" if trusted else "untrusted",
            enabled=not (path.parent / ".cuti-disabled").exists(),
            metadata=extra_metadata,
        )


def parse_skill_contract(raw: dict[str, Any]) -> SkillContract:
    return SkillContract.model_validate(raw)
