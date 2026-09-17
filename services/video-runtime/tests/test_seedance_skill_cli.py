import importlib.util
import sys
from pathlib import Path

import pytest


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "skills"
    / "external"
    / "seedance2"
    / "scripts"
    / "seedance.py"
)


def _load_seedance_cli():
    spec = importlib.util.spec_from_file_location("seedance_skill_cli", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("audio_argument", "expected"),
    [([], True), (["--generate-audio", "false"], False)],
)
def test_seedance_cli_defaults_to_native_audio(monkeypatch, audio_argument, expected):
    module = _load_seedance_cli()
    captured = {}
    monkeypatch.setattr(module, "cmd_create", lambda args: captured.update(vars(args)))
    monkeypatch.setattr(
        sys,
        "argv",
        ["seedance.py", "create", "--prompt", "cinematic scene", *audio_argument],
    )

    module.main()

    assert captured["generate_audio"] is expected
