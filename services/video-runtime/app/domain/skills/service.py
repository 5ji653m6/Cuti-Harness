from __future__ import annotations

import hashlib
from pathlib import Path

from .lock import SkillLock


def skill_digest(root: Path) -> str:
    """Digest all visible Skill files so a project can be reproduced later."""
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(root).as_posix()
        if relative.startswith(".cuti-") or any(part.startswith(".") for part in Path(relative).parts):
            continue
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def make_skill_lock(project_id: str, metadata) -> SkillLock:
    root = metadata.path.parent
    config = dict(metadata.metadata or {})
    return SkillLock(
        project_id=project_id,
        skill_id=metadata.name,
        version=str(config.get("version") or "0.0.0"),
        digest=skill_digest(root),
        source="external" if root.parent.name == "external" else "builtin",
        enabled=metadata.enabled,
    )
