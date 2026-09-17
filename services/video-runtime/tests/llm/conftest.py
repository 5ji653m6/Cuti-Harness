"""
LLM 集成测试共用：加载 .env 后强制关闭 LangSmith tracing，避免真实用例写入 trace。
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load_dev_env_disable_langsmith_tracing() -> None:
    """与 test_real_keyframe_gen 一致加载 env，再覆盖关闭 tracing（不删 KEY，仅关开关）。"""
    from dotenv import load_dotenv

    load_dotenv(_PROJECT_ROOT / ".env.development")
    load_dotenv(_PROJECT_ROOT / ".env.local", override=True)
    os.environ["LANGSMITH_TRACING"] = "false"


@pytest.fixture(scope="module")
def dev_env_loaded():
    load_dev_env_disable_langsmith_tracing()
