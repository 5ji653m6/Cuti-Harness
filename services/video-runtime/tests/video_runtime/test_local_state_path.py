from pathlib import Path

import pytest

from app.video_runtime.local_state_path import (
    LegacyStateMigrationRequired,
    default_state_path,
    resolve_state_path,
)


def test_default_state_path_matches_cli_on_each_platform(tmp_path: Path):
    assert default_state_path(
        environment={"LOCALAPPDATA": str(tmp_path / "local")},
        home=tmp_path / "home",
        platform_name="win32",
    ) == (tmp_path / "local" / "VideoAgentHarness" / "video-runtime-state.json").resolve()
    assert default_state_path(
        environment={}, home=tmp_path / "home", platform_name="darwin",
    ) == (
        tmp_path / "home" / "Library" / "Application Support"
        / "VideoAgentHarness" / "video-runtime-state.json"
    ).resolve()
    assert default_state_path(
        environment={"XDG_DATA_HOME": str(tmp_path / "xdg")},
        home=tmp_path / "home",
        platform_name="linux",
    ) == (tmp_path / "xdg" / "video-agent-harness" / "video-runtime-state.json").resolve()


def test_existing_explicit_state_path_wins_and_reports_other_legacy_state(tmp_path: Path):
    legacy = tmp_path / "data" / "video-runtime-state.json"
    legacy.parent.mkdir()
    legacy.write_text("{}", encoding="utf-8")
    explicit = tmp_path / "chosen" / "state.json"
    explicit.parent.mkdir()
    explicit.write_text("{}", encoding="utf-8")
    with pytest.warns(RuntimeWarning, match="legacy files are ignored"):
        assert resolve_state_path(
            environment={"VIDEO_RUNTIME_LOCAL_STATE_PATH": str(explicit)},
            current_directory=tmp_path,
            module_path=tmp_path / "installed" / "standalone.py",
            home=tmp_path / "home",
            platform_name="linux",
        ) == explicit.resolve()


def test_missing_explicit_state_path_does_not_hide_legacy_state(tmp_path: Path):
    legacy = tmp_path / "data" / "video-runtime-state.json"
    legacy.parent.mkdir()
    legacy.write_text("{}", encoding="utf-8")
    explicit = tmp_path / "chosen" / "state.json"

    with pytest.raises(LegacyStateMigrationRequired, match="Startup stopped"):
        resolve_state_path(
            environment={"VIDEO_RUNTIME_LOCAL_STATE_PATH": str(explicit)},
            current_directory=tmp_path,
            module_path=tmp_path / "installed" / "standalone.py",
            home=tmp_path / "home",
            platform_name="linux",
        )
    assert not explicit.exists()


def test_legacy_state_stops_empty_canonical_store_creation(tmp_path: Path):
    legacy = tmp_path / "work" / "data" / "video-runtime-state.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text('{"projects": []}', encoding="utf-8")
    target = tmp_path / "xdg" / "video-agent-harness" / "video-runtime-state.json"

    with pytest.raises(LegacyStateMigrationRequired) as caught:
        resolve_state_path(
            environment={"XDG_DATA_HOME": str(tmp_path / "xdg")},
            current_directory=tmp_path / "work",
            module_path=tmp_path / "installed" / "standalone.py",
            home=tmp_path / "home",
            platform_name="linux",
        )

    message = str(caught.value)
    assert str(legacy.resolve()) in message
    assert str(target.resolve()) in message
    assert "Startup stopped" in message
    assert not target.exists()


def test_existing_canonical_store_warns_about_ignored_legacy_state(tmp_path: Path):
    target = tmp_path / "xdg" / "video-agent-harness" / "video-runtime-state.json"
    target.parent.mkdir(parents=True)
    target.write_text('{"projects": []}', encoding="utf-8")
    legacy = tmp_path / "work" / "data" / "video-runtime-state.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text('{"projects": [{"id": "legacy"}]}', encoding="utf-8")

    with pytest.warns(RuntimeWarning, match="legacy files are ignored"):
        resolved = resolve_state_path(
            environment={"XDG_DATA_HOME": str(tmp_path / "xdg")},
            current_directory=tmp_path / "work",
            module_path=tmp_path / "installed" / "standalone.py",
            home=tmp_path / "home",
            platform_name="linux",
        )
    assert resolved == target.resolve()
