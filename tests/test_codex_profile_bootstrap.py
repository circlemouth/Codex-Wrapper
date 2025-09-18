import logging

import pytest

from app.codex import apply_codex_profile_overrides
from app.config import settings


@pytest.fixture
def restore_settings():
    original_profile_dir = settings.codex_profile_dir
    original_config_dir = settings.codex_config_dir
    yield
    settings.codex_profile_dir = original_profile_dir
    settings.codex_config_dir = original_config_dir


def test_apply_codex_profile_overrides_noop_when_missing(tmp_path, restore_settings, monkeypatch):
    profile_dir = tmp_path / "missing"
    codex_home = tmp_path / "home"

    monkeypatch.setattr(settings, "codex_profile_dir", str(profile_dir))
    monkeypatch.setattr(settings, "codex_config_dir", str(codex_home))

    apply_codex_profile_overrides()

    assert not (codex_home / "AGENTS.md").exists()
    assert not (codex_home / "config.toml").exists()


def test_apply_codex_profile_overrides_copies_present_files(tmp_path, restore_settings, monkeypatch):
    profile_dir = tmp_path / "profile"
    profile_dir.mkdir()
    (profile_dir / "codex_agents.md").write_text("agent directives", encoding="utf-8")
    (profile_dir / "codex_config.toml").write_text(
        "model = \"demo\"\n", encoding="utf-8"
    )

    codex_home = tmp_path / "home"

    monkeypatch.setattr(settings, "codex_profile_dir", str(profile_dir))
    monkeypatch.setattr(settings, "codex_config_dir", str(codex_home))

    apply_codex_profile_overrides()

    agents_path = codex_home / "AGENTS.md"
    config_path = codex_home / "config.toml"
    assert agents_path.read_text(encoding="utf-8") == "agent directives"
    assert config_path.read_text(encoding="utf-8") == "model = \"demo\"\n"


def test_apply_codex_profile_overrides_partial_copy(tmp_path, restore_settings, monkeypatch):
    profile_dir = tmp_path / "profile"
    profile_dir.mkdir()
    (profile_dir / "codex_agents.md").write_text("only agent", encoding="utf-8")

    codex_home = tmp_path / "home"

    monkeypatch.setattr(settings, "codex_profile_dir", str(profile_dir))
    monkeypatch.setattr(settings, "codex_config_dir", str(codex_home))

    apply_codex_profile_overrides()

    agents_path = codex_home / "AGENTS.md"
    assert agents_path.read_text(encoding="utf-8") == "only agent"
    assert not (codex_home / "config.toml").exists()


def test_apply_codex_profile_overrides_supports_legacy_names(
    tmp_path, restore_settings, monkeypatch, caplog
):
    profile_dir = tmp_path / "profile"
    profile_dir.mkdir()
    (profile_dir / "agent.md").write_text("legacy agent", encoding="utf-8")
    (profile_dir / "config.toml").write_text("legacy = true\n", encoding="utf-8")

    codex_home = tmp_path / "home"

    monkeypatch.setattr(settings, "codex_profile_dir", str(profile_dir))
    monkeypatch.setattr(settings, "codex_config_dir", str(codex_home))

    with caplog.at_level(logging.WARNING):
        apply_codex_profile_overrides()

    agents_path = codex_home / "AGENTS.md"
    config_path = codex_home / "config.toml"
    assert agents_path.read_text(encoding="utf-8") == "legacy agent"
    assert config_path.read_text(encoding="utf-8") == "legacy = true\n"
    warnings = [record.message for record in caplog.records if record.levelno >= logging.WARNING]
    assert any("legacy filename 'agent.md'" in msg for msg in warnings)
    assert any("legacy filename 'config.toml'" in msg for msg in warnings)


def test_apply_codex_profile_overrides_prefers_primary_over_legacy(
    tmp_path, restore_settings, monkeypatch, caplog
):
    profile_dir = tmp_path / "profile"
    profile_dir.mkdir()
    (profile_dir / "codex_agents.md").write_text("primary", encoding="utf-8")
    (profile_dir / "codex_config.toml").write_text("value = 1\n", encoding="utf-8")
    # Legacy files with different content should be ignored when primary files exist.
    (profile_dir / "agent.md").write_text("legacy", encoding="utf-8")
    (profile_dir / "config.toml").write_text("value = 2\n", encoding="utf-8")

    codex_home = tmp_path / "home"

    monkeypatch.setattr(settings, "codex_profile_dir", str(profile_dir))
    monkeypatch.setattr(settings, "codex_config_dir", str(codex_home))

    with caplog.at_level(logging.INFO):
        apply_codex_profile_overrides()

    agents_path = codex_home / "AGENTS.md"
    config_path = codex_home / "config.toml"
    assert agents_path.read_text(encoding="utf-8") == "primary"
    assert config_path.read_text(encoding="utf-8") == "value = 1\n"
    # No warnings expected because only primary filenames should be used.
    warnings = [record for record in caplog.records if record.levelno >= logging.WARNING]
    assert not warnings
