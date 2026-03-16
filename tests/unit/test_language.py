"""Unit tests for language.py — detection, normalization, BCP-47 tags, fallback to English."""

from __future__ import annotations

from unittest.mock import patch

from src.utils.language import (
    DEFAULT_LANGUAGE,
    SUPPORTED_LANGUAGES,
    detect_language_fallback,
    normalize_language,
)

# ---------------------------------------------------------------------------
# normalize_language
# ---------------------------------------------------------------------------


def test_normalize_en() -> None:
    assert normalize_language("en") == "en"


def test_normalize_ru() -> None:
    assert normalize_language("ru") == "ru"


def test_normalize_uz() -> None:
    assert normalize_language("uz") == "uz"


def test_normalize_case_insensitive() -> None:
    assert normalize_language("EN") == "en"
    assert normalize_language("Ru") == "ru"


def test_normalize_bcp47_tag() -> None:
    """BCP-47 tags like 'en-US' should normalize to 'en'."""
    assert normalize_language("en-US") == "en"
    assert normalize_language("ru-RU") == "ru"


def test_normalize_unknown_falls_back_to_english() -> None:
    assert normalize_language("fr") == DEFAULT_LANGUAGE
    assert normalize_language("de") == DEFAULT_LANGUAGE
    assert normalize_language("zh") == DEFAULT_LANGUAGE


def test_normalize_empty_string_falls_back() -> None:
    # split("-")[0] on empty string gives "", which won't match
    assert normalize_language("xx") == DEFAULT_LANGUAGE


# ---------------------------------------------------------------------------
# detect_language_fallback
# ---------------------------------------------------------------------------


def test_detect_english_text() -> None:
    with patch("langdetect.detect", return_value="en"):
        assert detect_language_fallback("Hello, how are you?") == "en"


def test_detect_russian_text() -> None:
    with patch("langdetect.detect", return_value="ru"):
        assert detect_language_fallback("Привет, как дела?") == "ru"


def test_detect_unsupported_language_falls_back() -> None:
    with patch("langdetect.detect", return_value="fr"):
        assert detect_language_fallback("Bonjour le monde") == DEFAULT_LANGUAGE


def test_detect_failure_falls_back_to_default() -> None:
    with patch("langdetect.detect", side_effect=Exception("detection failed")):
        assert detect_language_fallback("???") == DEFAULT_LANGUAGE


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


def test_supported_languages_set() -> None:
    assert {"en", "ru", "uz"} == SUPPORTED_LANGUAGES


def test_default_language_is_english() -> None:
    assert DEFAULT_LANGUAGE == "en"
