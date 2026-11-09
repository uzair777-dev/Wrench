"""Unit tests for virtualenv binary discovery in core/recovery/actions.py."""

from pathlib import Path

from wrench.core.recovery.actions import find_project_binary


def test_find_binary_in_dot_venv(tmp_path: Path) -> None:
    bin_dir = tmp_path / ".venv" / "bin"
    bin_dir.mkdir(parents=True)
    tool = bin_dir / "ruff"
    tool.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    tool.chmod(0o755)

    assert find_project_binary(tmp_path, "ruff") == tool


def test_find_binary_in_venv(tmp_path: Path) -> None:
    bin_dir = tmp_path / "venv" / "bin"
    bin_dir.mkdir(parents=True)
    tool = bin_dir / "black"
    tool.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    tool.chmod(0o755)

    assert find_project_binary(tmp_path, "black") == tool


def test_find_binary_in_node_modules(tmp_path: Path) -> None:
    bin_dir = tmp_path / "node_modules" / ".bin"
    bin_dir.mkdir(parents=True)
    tool = bin_dir / "prettier"
    tool.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    tool.chmod(0o755)

    assert find_project_binary(tmp_path, "prettier") == tool


def test_find_binary_via_virtual_env_var(tmp_path: Path, monkeypatch) -> None:
    venv_dir = tmp_path / "custom_env"
    bin_dir = venv_dir / "bin"
    bin_dir.mkdir(parents=True)
    tool = bin_dir / "flake8"
    tool.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    tool.chmod(0o755)

    monkeypatch.setenv("VIRTUAL_ENV", str(venv_dir))
    empty_repo = tmp_path / "repo"
    empty_repo.mkdir()

    assert find_project_binary(empty_repo, "flake8") == tool


def test_find_binary_ignores_non_executable(tmp_path: Path) -> None:
    bin_dir = tmp_path / ".venv" / "bin"
    bin_dir.mkdir(parents=True)
    tool = bin_dir / "mypy"
    tool.write_text("not executable", encoding="utf-8")
    tool.chmod(0o644)

    assert find_project_binary(tmp_path, "mypy") != tool


def test_find_binary_nonexistent_returns_none(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    monkeypatch.setenv("PATH", "")
    assert find_project_binary(tmp_path, "completely_nonexistent_tool_xyz_123") is None
