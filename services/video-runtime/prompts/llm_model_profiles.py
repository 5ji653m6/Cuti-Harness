"""
LLM 质量档位（best / common / economy）→ 具体模型。

用法（两种，可并存）：
1. PROMPTS_CONFIG.model_config 写具体 model（现状）——不受档位影响
2. 写 role，由 LLM_QUALITY 解析：
   {"role": "tool", "timeout": 180}  →  解析为具体 model

环境变量：
  LLM_QUALITY=best|common|economy   （默认 best）

角色：
  text        — 纯文本 / 路由 / 完成文案
  tool        — ReAct / tool-calling agent
  multimodal  — 图/视频/音频理解（必须走 Gemini；OpenAI 无原生视频 media 块）
"""
from __future__ import annotations

import os
from typing import Any, Dict, Literal, Mapping

Quality = Literal["best", "common", "economy"]
Role = Literal["text", "tool", "multimodal"]

# 单点改这里即可全局换档；具体 prompt 用 role 后一键生效
QUALITY_ROLE_MODELS: Dict[Quality, Dict[Role, str]] = {
    "best": {
        # GPT-5.6 Sol = 旗舰；tool 用 Terra 控成本；多模态必须 Gemini Pro
        "text": "gpt-5.6-terra",
        "tool": "gpt-5.6-terra",
        "multimodal": "gemini-3.1-pro-preview",
    },
    "common": {
        "text": "gpt-5-mini",
        "tool": "gpt-5-mini",
        "multimodal": "gemini-2.5-flash",
    },
    "economy": {
        # 与当前线上主配置对齐
        "text": "gpt-4.1-mini",
        "tool": "gpt-4.1-mini",
        "multimodal": "gemini-2.5-flash",
    },
}

VALID_QUALITIES = frozenset(QUALITY_ROLE_MODELS.keys())
VALID_ROLES = frozenset({"text", "tool", "multimodal"})


def get_llm_quality() -> Quality:
    raw = (os.getenv("LLM_QUALITY") or "best").strip().lower()
    if raw not in VALID_QUALITIES:
        raise ValueError(
            f"Invalid LLM_QUALITY={raw!r}. Expected one of: {sorted(VALID_QUALITIES)}"
        )
    return raw  # type: ignore[return-value]


def resolve_role_model(role: str, quality: Quality | None = None) -> str:
    q = quality or get_llm_quality()
    if role not in VALID_ROLES:
        raise ValueError(f"Invalid model role={role!r}. Expected one of: {sorted(VALID_ROLES)}")
    return QUALITY_ROLE_MODELS[q][role]  # type: ignore[index]


def resolve_model_config(model_config: Mapping[str, Any]) -> Dict[str, Any]:
    """
    解析 model_config：
    - 有 role 且无 model → 按 LLM_QUALITY 填入 model
    - 已有显式 model → 保留 model，丢掉 role（fallback 覆盖主 role 时用）
    - 仅有 model → 原样返回
    """
    out = dict(model_config)
    role = out.pop("role", None)
    if role is not None and not out.get("model"):
        out["model"] = resolve_role_model(str(role))
    return out


def has_model_or_role(model_config: Mapping[str, Any]) -> bool:
    return bool(model_config.get("model") or model_config.get("role"))
