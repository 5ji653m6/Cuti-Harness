from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

import asyncpg


def _database_url(source_pid: int | None, source_script: Path | None = None) -> str:
    if source_pid is not None:
        raw = Path(f"/proc/{source_pid}/environ").read_bytes().split(b"\0")
        inherited = dict(
            item.decode().split("=", 1) for item in raw if b"=" in item
        )
        if inherited.get("VIDEO_RUNTIME_DATABASE_URL"):
            return inherited["VIDEO_RUNTIME_DATABASE_URL"]
    if source_script is not None:
        source_url = next((
            line.removeprefix("export DATABASE_URL=").strip()
            for line in source_script.read_text(encoding="utf-8").splitlines()
            if line.startswith("export DATABASE_URL=")
        ), "")
        if source_url:
            return f"{source_url.rsplit('/', 1)[0]}/video_harness"
    value = os.getenv("VIDEO_RUNTIME_DATABASE_URL", "")
    if not value:
        raise RuntimeError("VIDEO_RUNTIME_DATABASE_URL is required")
    return value


async def apply(source_pid: int | None, source_script: Path | None = None) -> None:
    connection = await asyncpg.connect(_database_url(source_pid, source_script))
    try:
        root = Path(__file__).resolve().parents[1] / "migrations" / "video_runtime"
        for migration in sorted(root.glob("*.sql")):
            await connection.execute(migration.read_text(encoding="utf-8"))
            print(f"applied {migration.name}")
    finally:
        await connection.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-pid", type=int)
    parser.add_argument("--source-script", type=Path)
    args = parser.parse_args()
    asyncio.run(apply(args.source_pid, args.source_script))
