"""Unit tests for build_query() — query construction for en/ru/uz."""

from __future__ import annotations

from src.rag.query_builder import build_query


def test_returns_stripped_question() -> None:
    assert build_query("  How do I reset?  ", "en") == "How do I reset?"


def test_english_passthrough() -> None:
    assert build_query("Setup guide", "en") == "Setup guide"


def test_russian_passthrough() -> None:
    assert build_query("Как настроить?", "ru") == "Как настроить?"


def test_uzbek_passthrough() -> None:
    assert build_query("Qanday sozlash kerak?", "uz") == "Qanday sozlash kerak?"


def test_empty_string() -> None:
    assert build_query("", "en") == ""


def test_whitespace_only() -> None:
    assert build_query("   ", "en") == ""


def test_newlines_and_tabs_stripped() -> None:
    assert build_query("\n question \t", "en") == "question"
