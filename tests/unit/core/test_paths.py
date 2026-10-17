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
