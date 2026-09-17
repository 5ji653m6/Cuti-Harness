"""Project-owned access to Harness Session maintenance; no Runtime LLM planner."""
from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from .api import _identity, _owned_project, get_runtime
from .deepseek_bff import get_deepseek_client
from .deepseek_client import DeepSeekHarnessClient, DeepSeekHarnessError
from .runtime import VideoBuildRuntime


router = APIRouter(prefix="/api/video")


@router.post("/projects/{project_id}/sessions/{session_id}/compact")
async def compact_project_session(
    project_id: str,
    session_id: str,
    identity: Annotated[tuple[str, str | None], Depends(_identity)],
    runtime: Annotated[VideoBuildRuntime, Depends(get_runtime)],
    harness: Annotated[DeepSeekHarnessClient, Depends(get_deepseek_client)],
) -> dict:
    project = await _owned_project(runtime, project_id, identity[0])
    try:
        bound, _ = await runtime.repo.project_for_session(session_id, project.user_id)
    except LookupError as exc:
        raise HTTPException(404, "Session is not bound to this project") from exc
    if bound.id != project_id or (identity[1] and identity[1] != session_id):
        raise HTTPException(403, "Session does not belong to this project or caller")
    async with runtime.session_control_locks.setdefault(project_id, asyncio.Lock()):
        try:
            return {"data": await harness.compact_session(session_id)}
        except DeepSeekHarnessError as exc:
            raise HTTPException(409, str(exc)) from exc
