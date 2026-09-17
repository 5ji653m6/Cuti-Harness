from __future__ import annotations

import hashlib
import json
import logging
import os
import base64
import shutil
import stat
import tempfile
import zipfile
from io import BytesIO
from datetime import datetime, timezone
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .capability_loader import reload_registry
from .capabilities import CapabilityRegistry
from .skill_catalog import SUPPORTED_EXECUTORS, UNTRUSTED_EXECUTORS, SkillCatalog

logger = logging.getLogger(__name__)

MAX_BUNDLE_BYTES = 25 * 1024 * 1024
MAX_BUNDLE_FILES = 256
MAX_SKILL_MD_BYTES = 256 * 1024


class SkillInstallError(ValueError):
    pass


def _iter_bundle_files(source: Path):
    count = 0
    total = 0
    for path in sorted(source.rglob("*")):
        if path.is_symlink():
            raise SkillInstallError(f"symbolic links are not allowed: {path}")
        if not path.is_file():
            continue
        count += 1
        total += path.stat().st_size
        if count > MAX_BUNDLE_FILES:
            raise SkillInstallError(f"skill bundle exceeds {MAX_BUNDLE_FILES} files")
        if total > MAX_BUNDLE_BYTES:
            raise SkillInstallError(f"skill bundle exceeds {MAX_BUNDLE_BYTES} bytes")
        yield path


def compute_payload_digest(source: Path) -> str:
    """Digest executable payload files; SKILL.md is excluded to avoid self-reference."""
    digest = hashlib.sha256()
    for path in _iter_bundle_files(source):
        relative = path.relative_to(source).as_posix()
        if relative == "SKILL.md" or relative.startswith(".cuti-"):
            continue
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        digest.update(b"\0")
    return digest.hexdigest()


def _verify_optional_signature(contract, payload_digest: str) -> None:
    if not contract.bundle_signature:
        return
    try:
        from app.chat.config import get_settings

        configured = json.loads(get_settings().DEEP_AGENT_V2_SKILL_SIGNING_KEYS_JSON)
        encoded_key = configured[contract.signing_key_id]
        public_key = Ed25519PublicKey.from_public_bytes(base64.b64decode(encoded_key))
        signature = base64.b64decode(contract.bundle_signature)
        public_key.verify(signature, bytes.fromhex(payload_digest))
    except (KeyError, TypeError, ValueError, InvalidSignature, json.JSONDecodeError) as exc:
        raise SkillInstallError("skill bundle signature verification failed") from exc


def validate_skill_directory(source: Path) -> tuple[Path, str]:
    source = source.expanduser().resolve()
    if not source.is_dir():
        raise SkillInstallError(f"skill source is not a directory: {source}")
    list(_iter_bundle_files(source))
    skill_md = source / "SKILL.md"
    if not skill_md.is_file():
        raise SkillInstallError(f"missing SKILL.md in {source}")
    if skill_md.stat().st_size > MAX_SKILL_MD_BYTES:
        raise SkillInstallError(f"SKILL.md exceeds {MAX_SKILL_MD_BYTES} bytes")
    metadata = SkillCatalog._read_metadata(skill_md)
    if source.name != metadata.name:
        raise SkillInstallError(
            f"directory name {source.name!r} must match skill name {metadata.name!r}"
        )
    probe = SkillCatalog([source.parent])
    probe.discover()
    skill = probe.load(metadata.name)
    if skill.contract is None:
        return source, metadata.name
    if skill.contract.executor not in SUPPORTED_EXECUTORS:
        raise SkillInstallError(
            f"unsupported executor {skill.contract.executor!r}; "
            f"allowed={sorted(SUPPORTED_EXECUTORS)}"
        )
    if skill.contract.executor not in UNTRUSTED_EXECUTORS:
        raise SkillInstallError(
            f"external skills must use one of {sorted(UNTRUSTED_EXECUTORS)}"
        )
    if skill.contract.executor == "sandbox.run":
        entrypoint = source / skill.contract.sandbox.entrypoint
        try:
            entrypoint.resolve().relative_to(source)
        except ValueError as exc:
            raise SkillInstallError("sandbox entrypoint escapes the skill directory") from exc
        if not entrypoint.is_file():
            raise SkillInstallError(f"sandbox entrypoint does not exist: {entrypoint}")
        payload_digest = compute_payload_digest(source)
        if (
            skill.contract.bundle_sha256
            and skill.contract.bundle_sha256 != payload_digest
        ):
            raise SkillInstallError(
                "bundle_sha256 does not match the executable payload"
            )
        _verify_optional_signature(skill.contract, payload_digest)
    return source, metadata.name


def extract_skill_archive(data: bytes, destination_root: Path) -> Path:
    if len(data) > MAX_BUNDLE_BYTES:
        raise SkillInstallError(f"skill archive exceeds {MAX_BUNDLE_BYTES} bytes")
    destination_root.mkdir(parents=True, exist_ok=True)
    extract_root = Path(tempfile.mkdtemp(prefix=".skill-upload-", dir=destination_root))
    try:
        with zipfile.ZipFile(BytesIO(data)) as archive:
            members = archive.infolist()
            if len(members) > MAX_BUNDLE_FILES:
                raise SkillInstallError(f"skill archive exceeds {MAX_BUNDLE_FILES} files")
            expanded_size = 0
            for member in members:
                expanded_size += member.file_size
                if expanded_size > MAX_BUNDLE_BYTES:
                    raise SkillInstallError("expanded skill archive is too large")
                member_path = Path(member.filename)
                if (
                    member_path.is_absolute()
                    or ".." in member_path.parts
                    or member.filename.startswith(("/", "\\"))
                ):
                    raise SkillInstallError(f"unsafe archive path: {member.filename}")
                mode = member.external_attr >> 16
                if stat.S_ISLNK(mode):
                    raise SkillInstallError(f"archive symlink is not allowed: {member.filename}")
            archive.extractall(extract_root)
        candidates = [path.parent for path in extract_root.rglob("SKILL.md")]
        if len(candidates) != 1:
            raise SkillInstallError("archive must contain exactly one SKILL.md")
        return candidates[0]
    except Exception:
        shutil.rmtree(extract_root, ignore_errors=True)
        raise


def install_skill_directory(
    source: Path,
    external_root: Path,
    *,
    catalog: SkillCatalog,
    registry: CapabilityRegistry,
    overwrite: bool = False,
) -> str:
    source, name = validate_skill_directory(source)
    external_root = external_root.expanduser().resolve()
    external_root.mkdir(parents=True, exist_ok=True)
    destination = external_root / name
    existing = next(
        (item for item in catalog.list_metadata() if item.name == name),
        None,
    )
    if existing and existing.path.parent.resolve() != destination.resolve():
        raise SkillInstallError(f"skill name is reserved by {existing.path.parent}")
    temporary = Path(tempfile.mkdtemp(prefix=f".{name}-", dir=external_root))
    staged = temporary / name
    backup = external_root / f".{name}.backup"
    if destination.exists():
        if not overwrite:
            shutil.rmtree(temporary, ignore_errors=True)
            raise SkillInstallError(f"skill already installed: {destination}")
    try:
        shutil.copytree(source, staged)
        validate_skill_directory(staged)
        (staged / ".cuti-install.json").write_text(
            json.dumps(
                {
                    "name": name,
                    "payload_digest": compute_payload_digest(staged),
                    "installed_at": datetime.now(timezone.utc).isoformat(),
                    "source": "external_bundle",
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        if backup.exists():
            shutil.rmtree(backup)
        if destination.exists():
            os.replace(destination, backup)
        os.replace(staged, destination)
        shutil.rmtree(backup, ignore_errors=True)
    except Exception:
        if backup.exists() and not destination.exists():
            os.replace(backup, destination)
        raise
    finally:
        shutil.rmtree(temporary, ignore_errors=True)
    reload_registry(registry, catalog)
    logger.info("Installed external skill %s -> %s", name, destination)
    return name


def reload_skills(catalog: SkillCatalog, registry: CapabilityRegistry) -> int:
    reload_registry(registry, catalog)
    return len(catalog.list_metadata())
