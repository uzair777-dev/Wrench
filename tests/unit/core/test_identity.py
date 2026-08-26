"""Unit tests for core/identity.py — git user.name and user.email check/config."""

import pygit2
import pytest

from wrench.core import identity
from wrench.core.exceptions import IdentityRequiredError


class TestIdentity:
    def test_missing_identity_raises_identity_required_error(self, tmp_path, monkeypatch):
        # Isolate from host's global ~/.gitconfig
        monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
        monkeypatch.setenv("GIT_CONFIG_SYSTEM", "/dev/null")

        repo_path = tmp_path / "no-identity"
        repo_path.mkdir()
        pygit2.init_repository(str(repo_path))

        with pytest.raises(IdentityRequiredError) as exc_info:
            identity.check_identity(repo_path)

        assert "user.name" in exc_info.value.missing or "user.email" in exc_info.value.missing

    def test_set_and_check_identity(self, tmp_path, monkeypatch):
        monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
        monkeypatch.setenv("GIT_CONFIG_SYSTEM", "/dev/null")

        repo_path = tmp_path / "ident-repo"
        repo_path.mkdir()
        pygit2.init_repository(str(repo_path))

        identity.set_identity(repo_path, "John Doe", "john@example.com")
        name, email = identity.check_identity(repo_path)
        assert name == "John Doe"
        assert email == "john@example.com"

    def test_invalid_email_raises_value_error(self, tmp_path):
        repo_path = tmp_path / "bad-email"
        repo_path.mkdir()
        pygit2.init_repository(str(repo_path))

        with pytest.raises(ValueError):
            identity.set_identity(repo_path, "John", "not-an-email")
