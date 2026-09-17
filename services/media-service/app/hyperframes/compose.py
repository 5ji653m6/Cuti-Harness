"""Slim HyperFrames overlay composer, adapted from OpenMontage's hyperframes_compose.

Used by media.hyperframes_caption. This is the overlay sandwich (source video
under captions/titles), not a whole-HTML music video and not Remotion.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Optional

import yaml

from app.hyperframes.style_bridge import style_bridge

PACKAGE_DIR = Path(__file__).resolve().parent
PLAYBOOKS_DIR = PACKAGE_DIR / "playbooks"
CAPTIONS_DIR = PACKAGE_DIR / "captions"


def list_playbooks() -> list[str]:
    return sorted(path.stem for path in PLAYBOOKS_DIR.glob("*.yaml"))


def load_playbook(name: str | None) -> dict[str, Any]:
    """Load a vendored OpenMontage playbook by file stem or identity.name."""
    if not name or not str(name).strip():
        return {}
    key = str(name).strip()
    slug = key.lower().replace(" ", "-").replace("_", "-")
    path = PLAYBOOKS_DIR / f"{slug}.yaml"
    if path.is_file():
        return _read_playbook(path, slug)
    for candidate in PLAYBOOKS_DIR.glob("*.yaml"):
        data = _read_playbook(candidate, candidate.stem)
        identity = str(data.get("name") or "").lower()
        if identity == key.lower() or candidate.stem == slug:
            return data
    return {}


def _read_playbook(path: Path, slug: str) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return {}
    identity = data.get("identity") or {}
    if isinstance(identity, dict):
        data.setdefault("name", identity.get("name") or slug)
    data.setdefault("id", slug)
    return data


def css_from_playbook(
    playbook: dict[str, Any] | None,
    *,
    accent_color: str | None = None,
) -> tuple[dict[str, str], str]:
    edit_decisions = {}
    if accent_color:
        edit_decisions = {"metadata": {"accent_color": accent_color}}
    return style_bridge(playbook, edit_decisions or None)


def css_vars_block(css_vars: dict[str, str]) -> str:
    body = "".join(f"{key}:{value};" for key, value in css_vars.items())
    return f":root{{{body}}}"


def write_workspace_config(workspace: Path) -> None:
    """Scaffold hyperframes.json the same way OpenMontage does."""
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "compositions").mkdir(exist_ok=True)
    (workspace / "assets").mkdir(exist_ok=True)
    (workspace / "hyperframes.json").write_text(
        json.dumps(
            {
                "registry": "https://raw.githubusercontent.com/heygen-com/hyperframes/main/registry",
                "paths": {
                    "blocks": "compositions",
                    "components": "compositions/components",
                    "assets": "assets",
                },
                "media": {"autoProxy": True},
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def caption_template_path(style: str) -> Path:
    return CAPTIONS_DIR / f"{style}.html"


def stage_caption_html(workspace: Path, style: str, html: str) -> Path:
    dest = workspace / "compositions" / f"{style}.html"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(html, encoding="utf-8")
    return dest


def try_add_block(workspace: Path, block_name: str, *, cli: Path | None = None) -> bool:
    """Run `hyperframes add <name>` when HYPERFRAMES_ADD is on; otherwise skip.

    Caption HTML is vendored next to this module (same files as the registry
    add). Runtime add is an optional refresh, not the default path.
    """
    if os.getenv("HYPERFRAMES_ADD", "").lower() not in {"1", "true", "yes"}:
        return False
    proc = run_hf(["add", block_name, "--no-clipboard"], cwd=workspace, timeout=120, cli=cli)
    return proc.returncode == 0


def run_hf(
    args: list[str],
    *,
    cwd: Optional[Path],
    timeout: int,
    cli: Path | None = None,
) -> subprocess.CompletedProcess:
    """Invoke the HyperFrames CLI. Prefer a resolved binary; fall back to npx."""
    if cli is not None:
        cmd = [str(cli), *args]
    else:
        cmd = ["npx", "--yes", "hyperframes", *args]
        if os.name == "nt":
            resolved = shutil.which(cmd[0])
            if resolved:
                cmd[0] = resolved
    try:
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(cwd) if cwd else None,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=124,
            stdout=exc.stdout or "",
            stderr=(exc.stderr or "") + f"\n[timeout after {timeout}s]",
        )
