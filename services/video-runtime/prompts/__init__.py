"""
Prompts Package - 统一导出 Prompt 加载器
"""
from .prompt_loader import (
    load_prompt_with_fallback,
    load_prompt_with_fallback_async,
    load_local_mustache_template,
    invoke_prompt_with_multimodal,
    create_llm_from_model_config,
)

__all__ = [
    'load_prompt_with_fallback',
    'load_prompt_with_fallback_async',
    'load_local_mustache_template',
    'invoke_prompt_with_multimodal',
    'create_llm_from_model_config',
]

