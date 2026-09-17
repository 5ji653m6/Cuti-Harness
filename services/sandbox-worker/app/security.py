from pathlib import Path, PurePosixPath


def validate_relative_path(value: str) -> PurePosixPath:
    if "\\" in value or "\x00" in value:
        raise ValueError("paths must use safe POSIX separators")
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in ("", ".", "..") for part in path.parts):
        raise ValueError("path must be a normalized relative path")
    if ":" in path.parts[0]:
        raise ValueError("drive-qualified paths are forbidden")
    return path


def confined_path(root: Path, relative: str) -> Path:
    path = root.joinpath(*validate_relative_path(relative).parts)
    root_resolved = root.resolve()
    try:
        path.resolve(strict=False).relative_to(root_resolved)
    except ValueError as exc:
        raise ValueError("path escapes workspace") from exc
    return path

