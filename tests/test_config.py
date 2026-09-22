"""Settings validation without real credentials or local dotenv dependencies."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import Settings


@pytest.fixture(autouse=True)
def isolate_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    for name in ("OPENAI_API_KEY", "OPENAI_MODEL", "OPENAI_TIMEOUT_SECONDS"):
        monkeypatch.delenv(name, raising=False)


def test_settings_load_environment_and_hide_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", " test-only-key ")
    monkeypatch.setenv("OPENAI_MODEL", " test-model ")
    monkeypatch.setenv("OPENAI_TIMEOUT_SECONDS", "12.5")

    settings = Settings()

    assert settings.openai_api_key.get_secret_value() == "test-only-key"
    assert settings.openai_model == "test-model"
    assert settings.openai_timeout_seconds == 12.5
    assert "test-only-key" not in repr(settings)
    assert "test-only-key" not in settings.model_dump_json()


def test_dotenv_loading_and_environment_precedence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / ".env").write_text(
        "OPENAI_API_KEY=test-only-key\nOPENAI_MODEL=file-model\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENAI_MODEL", "environment-model")

    settings = Settings()

    assert settings.openai_api_key.get_secret_value() == "test-only-key"
    assert settings.openai_model == "environment-model"
    assert settings.openai_timeout_seconds == 30


@pytest.mark.parametrize("missing", ["OPENAI_API_KEY", "OPENAI_MODEL"])
def test_missing_required_settings(
    monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-key")
    monkeypatch.setenv("OPENAI_MODEL", "test-model")
    monkeypatch.delenv(missing)

    with pytest.raises(ValidationError):
        Settings()


@pytest.mark.parametrize(
    "name,value",
    [
        ("OPENAI_API_KEY", ""),
        ("OPENAI_API_KEY", "   "),
        ("OPENAI_MODEL", ""),
        ("OPENAI_MODEL", "   "),
        ("OPENAI_TIMEOUT_SECONDS", "0"),
        ("OPENAI_TIMEOUT_SECONDS", "-1"),
        ("OPENAI_TIMEOUT_SECONDS", "nan"),
        ("OPENAI_TIMEOUT_SECONDS", "inf"),
        ("OPENAI_TIMEOUT_SECONDS", "invalid"),
    ],
)
def test_invalid_settings(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-key")
    monkeypatch.setenv("OPENAI_MODEL", "test-model")
    monkeypatch.setenv(name, value)

    with pytest.raises(ValidationError) as error:
        Settings()

    assert error.value.errors()[0]["loc"] == (name.lower(),)
    assert "test-only-key" not in str(error.value)
