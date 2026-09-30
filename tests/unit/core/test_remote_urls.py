"""Unit tests for Git remote URL parsing (Phase 4.1 expanded matrix)."""

import pytest

from wrench.core.remote_urls import RemoteUrlParts, host_of_instance_url, parse_remote_url


class TestParseRemoteUrl:
    """Full parse matrix: https, scp, ssh://, file://, garbage→None."""

    @pytest.mark.parametrize(
        ("url", "expected"),
        [
            # HTTPS standard
            (
                "https://github.com/torvalds/linux.git",
                RemoteUrlParts("https", "github.com", "torvalds", "linux"),
            ),
            (
                "https://github.com/torvalds/linux",
                RemoteUrlParts("https", "github.com", "torvalds", "linux"),
            ),
            (
                "https://github.com/torvalds/linux/",
                RemoteUrlParts("https", "github.com", "torvalds", "linux"),
            ),
            # HTTPS with port
            (
                "https://forge.example.com:8443/org/repo.git",
                RemoteUrlParts("https", "forge.example.com", "org", "repo"),
            ),
            # HTTP
            (
                "http://gitlab.com/group/subgroup/project.git",
                RemoteUrlParts("http", "gitlab.com", "group/subgroup", "project"),
            ),
            # Self-hosted subpath
            (
                "https://forgejo.example.com/user/repo.git",
                RemoteUrlParts("https", "forgejo.example.com", "user", "repo"),
            ),
            # SSH SCP-like
            (
                "git@github.com:torvalds/linux.git",
                RemoteUrlParts("ssh", "github.com", "torvalds", "linux"),
            ),
            (
                "git@gitlab.com:group/subgroup/project.git",
                RemoteUrlParts("ssh", "gitlab.com", "group/subgroup", "project"),
            ),
            (
                "git@gitlab.com:org/repo",
                RemoteUrlParts("ssh", "gitlab.com", "org", "repo"),
            ),
            # SSH with scheme and port
            (
                "ssh://git@forge.example.com:2222/org/repo.git",
                RemoteUrlParts("ssh", "forge.example.com", "org", "repo"),
            ),
            (
                "ssh://git@github.com/owner/repo.git",
                RemoteUrlParts("ssh", "github.com", "owner", "repo"),
            ),
            # Case normalization for host
            (
                "https://GITHUB.COM/Owner/Repo.git",
                RemoteUrlParts("https", "github.com", "Owner", "Repo"),
            ),
            # file:// scheme
            (
                "file:///home/user/repos/myrepo.git",
                RemoteUrlParts("file", "", "repos", "myrepo"),
            ),
            (
                "file:///tmp/repo",
                RemoteUrlParts("file", "", "tmp", "repo"),
            ),
        ],
    )
    def test_parse_remote_url_valid(self, url, expected):
        result = parse_remote_url(url)
        assert result is not None
        assert result.protocol == expected.protocol
        assert result.host == expected.host
        assert result.owner == expected.owner
        assert result.repo == expected.repo

    @pytest.mark.parametrize(
        "url",
        [
            "",
            "   ",
        ],
    )
    def test_parse_remote_url_returns_none(self, url):
        assert parse_remote_url(url) is None

    def test_frozen_dataclass(self):
        parts = parse_remote_url("https://github.com/owner/repo")
        assert parts is not None
        with pytest.raises(AttributeError):
            parts.host = "evil.com"  # type: ignore[misc]


class TestHostOfInstanceUrl:
    """Tests for host_of_instance_url — same semantics as old _host_of."""

    @pytest.mark.parametrize(
        ("instance_url", "expected"),
        [
            ("https://github.com", "github.com"),
            ("https://GITHUB.COM", "github.com"),
            ("https://gitlab.example.com:8443", "gitlab.example.com"),
            ("https://forge.example.com/", "forge.example.com"),
            ("http://git.internal.corp", "git.internal.corp"),
            ("github.com", "github.com"),
        ],
    )
    def test_host_extraction(self, instance_url, expected):
        assert host_of_instance_url(instance_url) == expected
