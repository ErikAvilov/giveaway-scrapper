"""Gemini credentials are optional unless analysis is attempted."""

from __future__ import annotations

import pytest
from pydantic import SecretStr

from app.config import (
    DEFAULT_GEMINI_MODEL,
    Settings,
    get_settings,
    require_gemini_api_key,
)
from app.gemini.client import GeminiClient


def test_default_gemini_model_is_current() -> None:
    assert DEFAULT_GEMINI_MODEL == "gemini-3.5-flash-lite"
    settings = Settings(
        database_url=SecretStr("postgresql://u:p@localhost/db"),
        gemini_api_key=None,
    )
    assert settings.gemini_model == "gemini-3.5-flash-lite"


def test_settings_load_without_gemini_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://user:pass@localhost:5432/neondb?sslmode=require",
    )
    # Ignore collector/.env so an optional local key cannot shadow the test.
    settings = Settings(
        _env_file=None,
        database_url=SecretStr(
            "postgresql://user:pass@localhost:5432/neondb?sslmode=require"
        ),
        gemini_api_key=None,
    )
    assert settings.gemini_api_key is None
    assert settings.gemini_model == "gemini-3.5-flash-lite"


def test_get_settings_allows_missing_gemini_when_env_omits_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "DATABASE_URL=postgresql://user:pass@localhost:5432/neondb?sslmode=require\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    get_settings.cache_clear()
    try:
        settings = get_settings()
        assert settings.gemini_api_key is None
    finally:
        get_settings.cache_clear()


def test_require_gemini_api_key_fails_clearly() -> None:
    settings = Settings(
        database_url=SecretStr("postgresql://u:p@localhost/db"),
        gemini_api_key=None,
    )
    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        require_gemini_api_key(settings)


def test_gemini_client_requires_api_key() -> None:
    settings = Settings(
        database_url=SecretStr("postgresql://u:p@localhost/db"),
        gemini_api_key=None,
    )
    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        GeminiClient(settings)


def test_empty_gemini_api_key_rejected() -> None:
    settings = Settings(
        database_url=SecretStr("postgresql://u:p@localhost/db"),
        gemini_api_key=SecretStr("   "),
    )
    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        require_gemini_api_key(settings)
