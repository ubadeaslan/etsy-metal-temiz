import pytest

from metal import config


@pytest.fixture(autouse=True)
def work(tmp_path, monkeypatch):
    """Every test gets its own empty calisma/ (settings, designs, rooms, ledger) and no API keys."""
    monkeypatch.setattr(config, "WORK", tmp_path)
    monkeypatch.setattr(config, "DESIGNS", tmp_path / "tasarimlar")
    monkeypatch.setattr(config, "ROOMS", tmp_path / "arka-planlar")
    monkeypatch.setattr(config, "READY_CARDS", tmp_path / "kartlar")
    monkeypatch.setattr(config, "SETTINGS_FILE", tmp_path / "ayarlar.json")
    monkeypatch.setattr(config, "USAGE_FILE", tmp_path / "harcama.jsonl")
    monkeypatch.setattr(config, "ENV_FILE", tmp_path / ".env")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    return tmp_path
