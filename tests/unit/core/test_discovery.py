import threading
from pathlib import Path

from tests.fixtures.git_repos import make_repo_forest
from wrench.core.discovery import discover_repos


def test_discover_repos_finds_valid_repositories(tmp_path):
    root, categorized = make_repo_forest(tmp_path)
    results = discover_repos(root, max_depth=3)

    result_paths = {p.resolve() for p in results}
    # All valid repos must be discovered
    assert categorized["valid"].issubset(result_paths)
    # Beyond max depth (depth 4) must be skipped
    assert categorized["deep"] not in result_paths
    # Dot-directories must be skipped
    assert categorized["hidden"] not in result_paths
    # Submodules inside parent repo must be pruned
    assert categorized["submodule"] not in result_paths
    # Results must be sorted Path objects
    assert results == sorted(results)
    assert all(isinstance(p, Path) for p in results)


def test_discover_repos_cancellation(tmp_path):
    root, _ = make_repo_forest(tmp_path)
    cancel_evt = threading.Event()
    cancel_evt.set()  # Pre-cancelled
    results = discover_repos(root, max_depth=3, cancel_event=cancel_evt)
    assert results == []


def test_discover_repos_progress_callback(tmp_path):
    root, categorized = make_repo_forest(tmp_path)
    counts = []
    results = discover_repos(root, max_depth=3, on_progress=counts.append)
    assert len(counts) == len(results)
    assert sorted(counts) == counts
    assert counts[-1] == len(results)


def test_discover_repos_invalid_or_missing_root(tmp_path):
    assert discover_repos(tmp_path / "non_existent") == []
    dummy_file = tmp_path / "file.txt"
    dummy_file.write_text("hello")
    assert discover_repos(dummy_file) == []


def test_discover_repos_on_single_repo(tmp_path):
    repo_dir = tmp_path / "single_repo"
    repo_dir.mkdir()
    import pygit2

    pygit2.init_repository(str(repo_dir))

    results = discover_repos(repo_dir, max_depth=3)
    assert len(results) == 1
    assert results[0] == repo_dir.resolve()


def test_engine_reexports_discover_repos():
    from wrench.core import engine

    assert hasattr(engine, "discover_repos")
    assert engine.discover_repos is discover_repos
