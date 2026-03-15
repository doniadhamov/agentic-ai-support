from loguru import logger

SUPPORTED_LANGUAGES = {"en", "ru", "uz"}
DEFAULT_LANGUAGE = "en"

# Map from langdetect codes → our supported codes
_LANGDETECT_MAP: dict[str, str] = {
    "en": "en",
    "ru": "ru",
    "uz": "uz",
}


def normalize_language(code: str) -> str:
    """Normalize a language code to one of: en, ru, uz. Falls back to 'en'."""
    normalized = _LANGDETECT_MAP.get(code.lower().split("-")[0], DEFAULT_LANGUAGE)
    if normalized not in SUPPORTED_LANGUAGES:
        logger.warning(f"Unsupported language code '{code}', falling back to '{DEFAULT_LANGUAGE}'")
        return DEFAULT_LANGUAGE
    return normalized


def detect_language_fallback(text: str) -> str:
    """Fallback language detection using langdetect library."""
    try:
        from langdetect import detect  # type: ignore[import-untyped]
        code = detect(text)
        return normalize_language(code)
    except Exception as e:
        logger.warning(f"langdetect failed: {e}, defaulting to '{DEFAULT_LANGUAGE}'")
        return DEFAULT_LANGUAGE
