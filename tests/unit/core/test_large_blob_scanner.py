from pathlib import Path

import pytest

from wrench.core import engine
from wrench.core.write_ops import run_git


@pytest.fixture
def repo_with_blobs(tmp_path: Path):
    run_git(tmp_path, ["init"])
    run_git(tmp_path, ["config", "user.name", "Test User"])
    run_git(tmp_path, ["config", "user.email", "test@example.com"])

    # Create initial commit
    init_file = tmp_path / "README.md"
    init_file.write_text("initial commit\n")
    run_git(tmp_path, ["add", "README.md"])
    run_git(tmp_path, ["commit", "-m", "initial"])

    handle = engine.open_repo(tmp_path)
    return handle


def test_engine_git_config_get_set(repo_with_blobs):
    # Local get/set
    assert engine.get_git_config(repo_with_blobs, "http.postBuffer", scope="local") is None
    engine.set_git_config(repo_with_blobs, "http.postBuffer", "524288000", scope="local")
    assert engine.get_git_config(repo_with_blobs, "http.postBuffer", scope="local") == "524288000"

    # Helpers
    assert engine.get_http_post_buffer(repo_with_blobs, scope="local") == 524288000
    engine.set_http_post_buffer(repo_with_blobs, 104857600, scope="local")
    assert engine.get_http_post_buffer(repo_with_blobs, scope="local") == 104857600

    assert engine.get_http_version(repo_with_blobs, scope="local") is None
    engine.set_http_version(repo_with_blobs, "HTTP/1.1", scope="local")
    assert engine.get_http_version(repo_with_blobs, scope="local") == "HTTP/1.1"


def test_scan_unpushed_large_blobs(repo_with_blobs, tmp_path: Path):
    # Add a mock large blob: threshold = 1.0 MB
    large_file = tmp_path / "big_data.bin"
    # Write 1.5 MB
    large_file.write_bytes(b"0" * int(1.5 * 1024 * 1024))
    run_git(tmp_path, ["add", "big_data.bin"])
    run_git(tmp_path, ["commit", "-m", "add big data"])

    blobs = engine.scan_unpushed_large_blobs(repo_with_blobs, threshold_mb=1.0)
    assert len(blobs) == 1
    path, size_mb = blobs[0]
    assert path == "big_data.bin"
    assert size_mb == pytest.approx(1.5, rel=1e-2)

    # Threshold 2.0 MB should return empty
    blobs_empty = engine.scan_unpushed_large_blobs(repo_with_blobs, threshold_mb=2.0)
    assert len(blobs_empty) == 0


def test_scan_unpushed_large_blobs_multi_commit(repo_with_blobs, tmp_path: Path):
    file1 = tmp_path / "dump.sql"
    file1.write_bytes(b"A" * int(1.2 * 1024 * 1024))
    run_git(tmp_path, ["add", "dump.sql"])
    run_git(tmp_path, ["commit", "-m", "commit 1"])

    file2 = tmp_path / "model.onnx"
    file2.write_bytes(b"B" * int(2.5 * 1024 * 1024))
    run_git(tmp_path, ["add", "model.onnx"])
    run_git(tmp_path, ["commit", "-m", "commit 2"])

    blobs = engine.scan_unpushed_large_blobs(repo_with_blobs, threshold_mb=1.0)
    assert len(blobs) == 2
    paths = [p for p, _ in blobs]
    assert "model.onnx" in paths
    assert "dump.sql" in paths


def test_extreme_compression_config():
    cfg = engine.EXTREME_COMPRESSION_CONFIG
    assert cfg["core.compression"] == "9"
    assert cfg["pack.compression"] == "9"
    assert cfg["pack.window"] == "10"
    assert cfg["http.postBuffer"] == "524288000"
