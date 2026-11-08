"""Unit tests for platform path resolvers in wrench.core.paths."""

from pathlib import Path

from wrench.core import paths


def test_cache_dir_returns_path_under_app_name():
    cache_path = paths.cache_dir()
    assert isinstance(cache_path, Path)
    assert "wrench" in str(cache_path).lower()


def test_existing_dirs_return_paths():
    assert isinstance(paths.data_dir(), Path)
    assert isinstance(paths.config_dir(), Path)
    assert isinstance(paths.state_dir(), Path)


def test_platform_abstraction_guard():
    """Enforces FR-11.1-11.3 CI platform-abstraction check across src/wrench."""
    import re

    root = Path(__file__).resolve().parents[3] / "src" / "wrench"
    pattern = re.compile(r"secretstorage|SSH_AUTH_SOCK|XDG_")
    exempt_parts = [
        ("credentials", "backend.py"),
        ("credentials", "secret_service.py"),
        ("credentials", "__init__.py"),
        ("core", "paths.py"),
        ("core", "ssh_agent.py"),
    ]

    violations = []
    for py_file in root.rglob("*.py"):
        rel = py_file.relative_to(root)
        if any(rel.parts[-2:] == exempt for exempt in exempt_parts):
            continue
        text = py_file.read_text(encoding="utf-8")
        for i, line in enumerate(text.splitlines(), start=1):
            if pattern.search(line):
                violations.append(f"{py_file}:{i}: {line.strip()}")

    assert (
        not violations
    ), "Found platform-specific references outside abstraction layer:\n" + "\n".join(violations)
