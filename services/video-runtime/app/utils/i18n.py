"""
Internationalization utility functions
Provides backend i18n translation and language-context management
"""
import asyncio
import json
from pathlib import Path
from contextvars import ContextVar
from typing import Dict, Any, Optional

# ============================================================================
# Language-context management (formerly language_context.py)
# ============================================================================

# create the language context var, defaults to 'en' (when unrecognized)
language_context: ContextVar[str] = ContextVar('language', default='en')

def get_current_language() -> str:
    """
    Get the current request's language setting.

    Returns:
        ISO 639-1 language code (e.g. en, zh, fr, es, ja)
    """
    return language_context.get()

def set_current_language(language_code: str) -> None:
    """
    Set the current request's language.

    Args:
        language_code: ISO 639-1 language code (e.g. en, zh, fr, es, ja)

    Note: stores the LLM-returned language code directly, without any conversion or normalization
    """
    language_context.set(language_code.lower())

# ============================================================================
# i18n translation
# ============================================================================

# translation JSON file path
I18N_DIR = Path(__file__).parent.parent / "i18n" / "locales"

# in-memory cached translation data
_translations_cache: Dict[str, Dict[str, Any]] = {}


def _load_translations(lang: str) -> Dict[str, Any]:
    """Load the translation file for the given language."""
    if lang in _translations_cache:
        return _translations_cache[lang]

    try:
        translation_file = I18N_DIR / f"{lang}.json"
        if not translation_file.exists():
            # if the language file does not exist, try loading English
            translation_file = I18N_DIR / "en.json"

        if translation_file.exists():
            with open(translation_file, 'r', encoding='utf-8') as f:
                translations = json.load(f)
                _translations_cache[lang] = translations
                return translations
    except Exception as e:
        print(f"Failed to load translation file for {lang}: {e}")

    # return an empty dict as fallback
    return {}


def get_i18n_message(key: str, default: Optional[str] = None, params: Optional[Dict[str, Any]] = None, lang: Optional[str] = None) -> str:
    """
    Get an i18n message by key, with parameter substitution.

    Args:
        key: translation key, supports nested keys like "common.success"
        default: default value when the translation is not found
        params: parameter dict for substituting placeholders in the message, e.g. {"count": 5}
        lang: language code, default None (auto-detected)

    Returns:
        str: the translated message

    Examples:
        >>> get_i18n_message("common.success")
        "Success" (for en) or "成功" (for zh)

        >>> get_i18n_message("video_segments.processing_completed", params={"count": 5})
        "Video segments processing completed, processed 5 segments"

        >>> get_i18n_message("music.generated", default="Music generated", lang="en")
        "Background music generated successfully"
    """
    if lang is None:
        lang = get_current_language()

    translations = _load_translations(lang)

    # handle nested keys like "common.success"
    keys = key.split(".")
    current = translations

    for k in keys:
        if isinstance(current, dict) and k in current:
            current = current[k]
        else:
            # if not found, try loading English as a fallback
            if lang != "en":
                en_translations = _load_translations("en")
                current = en_translations
                for k2 in keys:
                    if isinstance(current, dict) and k2 in current:
                        current = current[k2]
                    else:
                        final_message = default or key
                        # if there are parameters, substitute them
                        if params and isinstance(params, dict):
                            try:
                                final_message = final_message.format(**params)
                            except (KeyError, ValueError) as e:
                                print(f"Parameter substitution failed for key '{key}': {e}")
                        return final_message
                final_message = current if isinstance(current, str) else (default or key)
            else:
                final_message = default or key

            # if there are parameters, substitute them
            if params and isinstance(params, dict):
                try:
                    final_message = final_message.format(**params)
                except (KeyError, ValueError) as e:
                    print(f"Parameter substitution failed for key '{key}': {e}")
            return final_message

    # get the final message text
    final_message = current if isinstance(current, str) else (default or key)

    # if there are parameters, substitute them
    if params and isinstance(params, dict):
        try:
            final_message = final_message.format(**params)
        except (KeyError, ValueError) as e:
            # if parameter substitution fails, return the original message
            print(f"Parameter substitution failed for key '{key}': {e}")

    return final_message


async def get_i18n_message_async(
    key: str,
    default: Optional[str] = None,
    params: Optional[Dict[str, Any]] = None,
    lang: Optional[str] = None,
) -> str:
    """
    Async version: run get_i18n_message in a thread pool to avoid blocking the event loop.
    Use this function with await in an async context.
    """
    return await asyncio.to_thread(get_i18n_message, key, default=default, params=params, lang=lang)

