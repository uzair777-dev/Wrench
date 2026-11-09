"""Unit tests for Git bundle operations (bundles.py and backup.py)."""

from pathlib import Path

import pytest

from wrench.core.backup import create_backup, restore_backup
from wrench.core.bundles import (
    create_bundle,
    get_bundle_info,
    unbundle,
    verify_bundle,
)
from wrench.core.engine import GitEngine, commit, init_repo, open_repo, stage_file


@pytest.fixture
def sample_repo(tmp_path: Path):
    repo_path = tmp_path / "bundle_src_repo"
    repo_path.mkdir()
    init_repo(repo_path)
    repo = open_repo(repo_path)

    readme = repo_path / "README.md"
    readme.write_text("# Bundle Source\n", encoding="utf-8")
    stage_file(repo, "README.md")
    commit(repo, "Initial commit for bundle")

    code = repo_path / "main.py"
    code.write_text("print('hello bundle')\n", encoding="utf-8")
    stage_file(repo, "main.py")
    commit(repo, "Add main.py")

    return repo


def test_create_and_verify_bundle(tmp_path: Path, sample_repo):
    bundle_path = tmp_path / "test_repo.bundle"
    created = create_bundle(sample_repo, bundle_path)
    assert created == bundle_path
    assert bundle_path.exists()
    assert bundle_path.stat().st_size > 0

    # Verify bundle
    assert verify_bundle(bundle_path, repo=sample_repo) is True

    # Bundle info
    info = get_bundle_info(bundle_path, repo=sample_repo)
    assert info.is_valid is True
    assert len(info.references) >= 1

    # Nonexistent bundle verification
    assert verify_bundle(tmp_path / "nonexistent.bundle") is False
    bad_info = get_bundle_info(tmp_path / "nonexistent.bundle")
    assert bad_info.is_valid is False


def test_unbundle_into_new_repo(tmp_path: Path, sample_repo):
    bundle_path = tmp_path / "archive.bundle"
    create_bundle(sample_repo, bundle_path)

    dest_path = tmp_path / "dest_repo"
    dest_path.mkdir()
    init_repo(dest_path)
    dest_repo = open_repo(dest_path)

    refs = unbundle(dest_repo, bundle_path)
    assert len(refs) >= 1


def test_backup_create_and_restore(tmp_path: Path, sample_repo):
    backup_file = tmp_path / "backup.bundle"
    create_backup(Path(sample_repo.path), backup_file)
    assert backup_file.exists()

    restore_path = tmp_path / "restored_repo"
    restore_backup(backup_file, restore_path)
    assert (restore_path / "README.md").exists()
    assert (restore_path / "main.py").exists()


def test_git_engine_bundle_facade(tmp_path: Path, sample_repo):
    engine = GitEngine(sample_repo)
    out_file = tmp_path / "engine_facade.bundle"
    res = engine.create_bundle(out_file)
    assert res.exists()
    assert GitEngine.verify_bundle(out_file, repo=sample_repo) is True
    info = GitEngine.get_bundle_info(out_file, repo=sample_repo)
    assert info.is_valid is True
