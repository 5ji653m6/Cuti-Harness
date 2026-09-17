from pathlib import Path

from app.chat.v2.models import AgentRun
from app.chat.v2.skill_catalog import SkillCatalog
from app.domain.skills import make_skill_lock, skill_digest


def _write_skill(root: Path, name: str = "camera-language") -> Path:
    directory = root / name
    directory.mkdir(parents=True)
    (directory / "SKILL.md").write_text(
        "---\nname: camera-language\ndescription: Camera guidance\nversion: 1.2.0\n---\n\nUse closeups.",
        encoding="utf-8",
    )
    (directory / "templates").mkdir()
    (directory / "templates" / "shot.md").write_text("shot", encoding="utf-8")
    return directory


def test_skill_lock_uses_version_source_and_content_digest(tmp_path):
    root = tmp_path / "external"
    directory = _write_skill(root)
    metadata = SkillCatalog([root]).discover()[0]
    lock = make_skill_lock("project-1", metadata)

    assert lock.skill_id == "camera-language"
    assert lock.version == "1.2.0"
    assert lock.source == "external"
    assert lock.digest == skill_digest(directory)


def test_skill_locks_attach_to_agent_run_payload(tmp_path):
    root = tmp_path / "external"
    _write_skill(root)
    metadata = SkillCatalog([root]).discover()[0]
    run = AgentRun(
        thread_id="thread-1", project_id="project-1", user_id="user-1",
        objective="make a sample", idempotency_key="key-1",
        skill_locks=[make_skill_lock("project-1", metadata)],
    )
    assert run.skill_locks[0].digest == skill_digest(root / "camera-language")
