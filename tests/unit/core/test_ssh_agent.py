"""Unit tests for core/ssh_agent.py and _git_env integration."""

from unittest.mock import patch

from wrench.core import ssh_agent
from wrench.core.write_ops import _git_env


class TestSSHAgent:
    def test_get_ssh_auth_socket_present(self, monkeypatch):
        monkeypatch.setenv("SSH_AUTH_SOCK", "/tmp/ssh-agent.sock")
        assert ssh_agent.get_ssh_auth_socket() == "/tmp/ssh-agent.sock"

    def test_get_ssh_auth_socket_absent(self, monkeypatch):
        monkeypatch.delenv("SSH_AUTH_SOCK", raising=False)
        with patch("os.path.exists", return_value=False):
            assert ssh_agent.get_ssh_auth_socket() is None


class TestGitEnv:
    def test_git_env_standard_vars(self):
        env = _git_env()
        assert env["GIT_TERMINAL_PROMPT"] == "0"
        assert env["GIT_ASKPASS"] == ""
        assert env["LC_ALL"] == "C"

    def test_git_env_with_ssh_socket(self):
        with patch("wrench.core.ssh_agent.get_ssh_auth_socket", return_value="/run/user/1000/ssh"):
            env = _git_env()
            assert env["SSH_AUTH_SOCK"] == "/run/user/1000/ssh"

    def test_git_env_without_ssh_socket(self, monkeypatch):
        monkeypatch.delenv("SSH_AUTH_SOCK", raising=False)
        with patch("wrench.core.ssh_agent.get_ssh_auth_socket", return_value=None):
            env = _git_env()
            assert "SSH_AUTH_SOCK" not in env
