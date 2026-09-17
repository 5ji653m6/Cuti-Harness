from __future__ import annotations

import os
import sys
import warnings
from collections.abc import Mapping
from pathlib import Path


STATE_FILENAME = "video-runtime-state.json"


class LegacyStateMigrationRequired(RuntimeError):
    """Raised when a legacy state file would otherwise be hidden by a new default."""


def default_data_directory(
    *,
    environment: Mapping[str, str] | None = None,
    home: str | Path | None = None,
    platform_name: str | None = None,
) -> Path:
    """Return the Cuti Video Harness per-user data directory.

    The result intentionally matches ``@cuti-ai/video-agent-harness`` so direct
    Python startup and npm-managed startup share one durable project store.
    """
    values = os.environ if environment is None else environment
    user_home = Path.home() if home is None else Path(home)
    platform_value = sys.platform if platform_name is None else platform_name
    if platform_value == "win32":
        base = values.get("LOCALAPPDATA", "").strip()
        return (Path(base) if base else user_home) / "VideoAgentHarness"
    if platform_value == "darwin":
        return user_home / "Library" / "Application Support" / "VideoAgentHarness"
    base = values.get("XDG_DATA_HOME", "").strip()
    return (Path(base) if base else user_home / ".local" / "share") / "video-agent-harness"


def default_state_path(
    *,
    environment: Mapping[str, str] | None = None,
    home: str | Path | None = None,
    platform_name: str | None = None,
) -> Path:
    """Return the absolute default path for local Video Runtime state."""
    return (
        default_data_directory(
            environment=environment,
            home=home,
            platform_name=platform_name,
        )
        / STATE_FILENAME
    ).expanduser().resolve()


def legacy_state_paths(
    target: str | Path,
    *,
    current_directory: str | Path | None = None,
    module_path: str | Path | None = None,
) -> tuple[Path, ...]:
    """Return existing source-checkout state files that differ from ``target``."""
    canonical = Path(target).expanduser().resolve()
    cwd = Path.cwd() if current_directory is None else Path(current_directory)
    module = Path(__file__) if module_path is None else Path(module_path)
    candidates = [(cwd / "data" / STATE_FILENAME).resolve()]

    # A source checkout historically wrote both below services/video-runtime
    # and below the repository root. Installed wheels do not match this layout.
    service_root = module.resolve().parents[2]
    repository_root = service_root.parents[1]
    if (repository_root / "services" / "video-runtime").resolve() == service_root:
        candidates.extend([
            (service_root / "data" / STATE_FILENAME).resolve(),
            (repository_root / ".local-state" / STATE_FILENAME).resolve(),
        ])

    found: list[Path] = []
    for candidate in candidates:
        if candidate != canonical and candidate.is_file() and candidate not in found:
            found.append(candidate)
    return tuple(found)


def resolve_state_path(
    *,
    environment: Mapping[str, str] | None = None,
    current_directory: str | Path | None = None,
    module_path: str | Path | None = None,
    home: str | Path | None = None,
    platform_name: str | None = None,
) -> Path:
    """Resolve local state without silently abandoning an existing legacy file.

    ``VIDEO_RUNTIME_LOCAL_STATE_PATH`` selects the target when present. An
    existing legacy file still blocks creation of an empty selected store and
    the error names both paths. If the selected store already exists, legacy
    files are reported as ignored so operators can merge or remove them.
    """
    values = os.environ if environment is None else environment
    explicit = values.get("VIDEO_RUNTIME_LOCAL_STATE_PATH", "").strip()
    target = (
        Path(explicit).expanduser().resolve()
        if explicit
        else default_state_path(
            environment=values,
            home=home,
            platform_name=platform_name,
        )
    )
    legacy = legacy_state_paths(
        target,
        current_directory=current_directory,
        module_path=module_path,
    )
    if not legacy:
        return target

    sources = ", ".join(str(item) for item in legacy)
    instruction = (
        f"Legacy Video Runtime state detected at {sources}. "
        f"The canonical state path is {target}. "
        "Move or merge the legacy state into the canonical path, or set "
        "VIDEO_RUNTIME_LOCAL_STATE_PATH to the intended existing file before restarting."
    )
    if not target.exists():
        raise LegacyStateMigrationRequired(
            f"{instruction} Startup stopped to avoid creating an empty project library."
        )
    warnings.warn(
        f"{instruction} The canonical store will be used; legacy files are ignored.",
        RuntimeWarning,
        stacklevel=2,
    )
    return target
