import pytest


@pytest.fixture(autouse=True)
def mock_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Provide minimal env vars so Settings can be instantiated without real secrets."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test:token")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")
    monkeypatch.setenv("GOOGLE_API_KEY", "test-google-key")
    monkeypatch.setenv("ZENDESK_API_TOKEN", "test-zendesk-token")
    monkeypatch.setenv("ZENDESK_EMAIL", "test@example.com")
