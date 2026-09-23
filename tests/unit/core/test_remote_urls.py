"""Unit tests for Git remote URL parsing."""

import pytest

from wrench.core.remote_urls import parse_remote_url


@pytest.mark.parametrize(
    ("url", "expected_host", "expected_owner", "expected_repo"),
    [
        # HTTPS standard
        ("https://github.com/torvalds/linux.git", "github.com", "torvalds", "linux"),
        ("https://github.com/torvalds/linux", "github.com", "torvalds", "linux"),
        ("http://gitlab.com/group/subgroup/project.git", "gitlab.com", "group/subgroup", "project"),
        ("https://forgejo.example.com/user/repo.git", "forgejo.example.com", "user", "repo"),
        # SSH SCP-like
        ("git@github.com:torvalds/linux.git", "github.com", "torvalds", "linux"),
        ("git@gitlab.com:group/subgroup/project.git", "gitlab.com", "group/subgroup", "project"),
        ("git@gitlab.com:org/repo", "gitlab.com", "org", "repo"),
        # SSH with scheme and port
        ("ssh://git@forge.example.com:2222/org/repo.git", "forge.example.com", "org", "repo"),
        ("ssh://git@github.com/owner/repo.git", "github.com", "owner", "repo"),
        # Case normalization for host
        ("https://GITHUB.COM/Owner/Repo.git", "github.com", "Owner", "Repo"),
    ],
)
def test_parse_remote_url_valid(url, expected_host, expected_owner, expected_repo):
    host, owner, repo = parse_remote_url(url)
    assert host == expected_host
    assert owner == expected_owner
    assert repo == expected_repo


@pytest.mark.parametrize(
    "invalid_url",
    [
        "",
        "not_a_url",
        "file:///tmp/repo.git",
        "https://github.com/",
        "git@github.com:",
    ],
)
def test_parse_remote_url_invalid(invalid_url):
    with pytest.raises(ValueError):
        parse_remote_url(invalid_url)
