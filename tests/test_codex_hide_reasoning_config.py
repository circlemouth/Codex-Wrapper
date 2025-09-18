from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app import codex


def test_hide_reasoning_enabled_includes_config(monkeypatch, tmp_path):
    monkeypatch.setattr(codex.settings, "hide_reasoning", True, raising=False)
    monkeypatch.setattr(codex.settings, "codex_workdir", str(tmp_path), raising=False)
    fake_codex = tmp_path / "codex"
    fake_codex.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake_codex.chmod(0o755)
    monkeypatch.setattr(codex.settings, "codex_path", str(fake_codex), raising=False)
    cmd = codex._build_cmd_and_env("prompt text")
    assert "--config" in cmd
    assert any(part == "hide_agent_reasoning=true" for part in cmd)


def test_override_can_disable_hide_reasoning(monkeypatch, tmp_path):
    monkeypatch.setattr(codex.settings, "hide_reasoning", True, raising=False)
    monkeypatch.setattr(codex.settings, "codex_workdir", str(tmp_path), raising=False)
    fake_codex = tmp_path / "codex"
    fake_codex.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake_codex.chmod(0o755)
    monkeypatch.setattr(codex.settings, "codex_path", str(fake_codex), raising=False)
    cmd = codex._build_cmd_and_env("prompt text", overrides={"hide_reasoning": False})
    assert "--config" in cmd
    assert any(part == "hide_agent_reasoning=false" for part in cmd)
