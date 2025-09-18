import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app import codex


def _prepare(monkeypatch: pytest.MonkeyPatch, tmp_path, expose_reasoning: bool) -> None:
    monkeypatch.setattr(codex, "_resolve_codex_executable", lambda: "/bin/codex")
    monkeypatch.setattr(codex.settings, "codex_workdir", str(tmp_path))
    monkeypatch.setattr(codex.settings, "expose_reasoning", expose_reasoning)


def test_hide_agent_reasoning_added_when_disabled(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    _prepare(monkeypatch, tmp_path, expose_reasoning=False)

    cmd = codex._build_cmd_and_env("hello world")

    assert "hide_agent_reasoning=true" in cmd


def test_hide_agent_reasoning_respects_override(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    _prepare(monkeypatch, tmp_path, expose_reasoning=False)

    cmd = codex._build_cmd_and_env("hello", overrides={"hide_agent_reasoning": False})

    assert "hide_agent_reasoning=true" not in cmd
    assert "hide_agent_reasoning=false" in cmd


def test_hide_agent_reasoning_not_added_when_exposed(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    _prepare(monkeypatch, tmp_path, expose_reasoning=True)

    cmd = codex._build_cmd_and_env("hello")

    assert all("hide_agent_reasoning=" not in token for token in cmd)
