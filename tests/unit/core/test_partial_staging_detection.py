"""Unit tests for partial staging detection and FileStatusInfo."""

from wrench.core import engine, read_ops
from wrench.core.models import FileStatusInfo


def test_partial_staging_detected_in_get_status(simple_repo) -> None:
    # 1. Modify and stage hello.txt
    (simple_repo.path / "hello.txt").write_text("stage version\n")
    engine.stage_file(simple_repo, "hello.txt")

    # 2. Modify hello.txt again in working tree without staging
    (simple_repo.path / "hello.txt").write_text("working tree version\n")

    status = read_ops.get_status(simple_repo)

    # Both staged and unstaged should capture the file with is_partially_staged = True
    assert len(status.staged) == 1
    assert status.staged[0].path == "hello.txt"
    assert status.staged[0].is_partially_staged is True

    assert len(status.unstaged) == 1
    assert status.unstaged[0].path == "hello.txt"
    assert status.unstaged[0].is_partially_staged is True

    # Check dedicated partially_staged tracking
    assert len(status.partially_staged) == 1
    assert status.partially_staged[0].path == "hello.txt"
    assert "hello.txt" in status.partially_staged_paths


def test_pure_staged_and_pure_unstaged_are_not_partial(simple_repo) -> None:
    # Pure staged file
    (simple_repo.path / "file_a.txt").write_text("content a\n")
    engine.stage_file(simple_repo, "file_a.txt")

    # Pure unstaged file
    (simple_repo.path / "file_b.txt").write_text("content b\n")

    status = read_ops.get_status(simple_repo)
    assert any(f.path == "file_a.txt" and not f.is_partially_staged for f in status.staged)
    assert "file_b.txt" in status.untracked
    assert "file_a.txt" not in status.partially_staged_paths


def test_file_status_info_composite_badge() -> None:
    info_mm = FileStatusInfo(
        path="foo.py",
        staged_code="M",
        unstaged_code="M",
        is_partially_staged=True,
    )
    assert info_mm.composite_badge == "MM"

    info_am = FileStatusInfo(
        path="foo.py",
        staged_code="A",
        unstaged_code="M",
        is_partially_staged=True,
    )
    assert info_am.composite_badge == "AM"

    info_pure_m = FileStatusInfo(
        path="foo.py",
        staged_code="M",
        unstaged_code=" ",
        is_partially_staged=False,
    )
    assert info_pure_m.composite_badge == "M"
