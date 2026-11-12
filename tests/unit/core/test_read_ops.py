"""Unit tests for core/read_ops.py — pygit2-backed read operations."""

import logging
import subprocess
from pathlib import Path

import pygit2
import pytest

from wrench.core import engine, read_ops


class TestGetStatus:
    def test_empty_repo_has_branch_name(self, empty_repo):
        status = read_ops.get_status(empty_repo)
        assert status.current_branch is not None  # e.g. "main" or "master"
        assert status.is_detached is False
        assert status.staged == []
        assert status.unstaged == []
        assert status.untracked == []

    def test_detached_head(self, detached_head_repo):
        status = read_ops.get_status(detached_head_repo)
        assert status.is_detached is True
        assert status.current_branch is None
        assert status.detached_head_sha is not None

    def test_untracked_file(self, simple_repo):
        (simple_repo.path / "new_file.txt").write_text("new content\n")
        status = read_ops.get_status(simple_repo)
        assert "new_file.txt" in status.untracked

    def test_modified_file(self, simple_repo):
        (simple_repo.path / "hello.txt").write_text("changed!\n")
        status = read_ops.get_status(simple_repo)
        assert len(status.unstaged) == 1
        assert status.unstaged[0].path == "hello.txt"
        assert status.unstaged[0].change_type == "modified"


class TestGetLog:
    def test_empty_repo_returns_empty(self, empty_repo):
        commits = read_ops.get_log(empty_repo)
        assert commits == []

    def test_returns_commits_in_order(self, multi_commit_repo):
        commits = read_ops.get_log(multi_commit_repo)
        assert len(commits) == 3
        assert commits[0].message == "Third commit"
        assert commits[2].message == "First commit"

    def test_limit_works(self, multi_commit_repo):
        commits = read_ops.get_log(multi_commit_repo, limit=2)
        assert len(commits) == 2

    def test_parent_shas_populated(self, multi_commit_repo):
        commits = read_ops.get_log(multi_commit_repo)
        assert len(commits[0].parent_shas) == 1
        assert len(commits[2].parent_shas) == 0


class TestGetDiff:
    def test_binary_file_marked_as_binary(self, binary_file_repo):
        (binary_file_repo.path / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\xff" * 100)
        diff = read_ops.get_diff(binary_file_repo, "image.png", staged=False)
        assert diff.is_binary is True
        assert diff.hunks == []

    def test_text_file_diff(self, simple_repo):
        (simple_repo.path / "hello.txt").write_text("Hello, world!\nLine 2\n")
        diff = read_ops.get_diff(simple_repo, "hello.txt", staged=False)
        assert diff.is_binary is False
        assert len(diff.hunks) == 1
        assert any(line.origin == "+" and "Line 2" in line.content for line in diff.hunks[0].lines)

    def test_deleted_untracked_and_staged_unborn_diffs(self, simple_repo, empty_repo, monkeypatch):
        # Deleted tracked file (unstaged)
        (simple_repo.path / "hello.txt").unlink()
        del_diff = read_ops.get_diff(simple_repo, "hello.txt", staged=False)
        assert len(del_diff.hunks) == 1
        assert any(
            ln.origin == "-" and "Hello, world!" in ln.content for ln in del_diff.hunks[0].lines
        )

        # Untracked file (fast path)
        (simple_repo.path / "untracked.txt").write_text("untracked line 1\n")
        untracked_diff = read_ops.get_diff(simple_repo, "untracked.txt", staged=False)
        assert len(untracked_diff.hunks) == 1
        assert any(
            ln.origin == "+" and "untracked line 1" in ln.content
            for ln in untracked_diff.hunks[0].lines
        )

        # Oversized untracked file (> _MAX_IN_MEMORY_BLOB_BYTES) exercises --no-index exit=1
        (simple_repo.path / "large_untracked.txt").write_text(
            "".join(f"big-{i}\n" for i in range(30)),
            encoding="utf-8",
        )
        monkeypatch.setattr(read_ops, "_MAX_IN_MEMORY_BLOB_BYTES", 32)
        oversized_diff = read_ops.get_diff(simple_repo, "large_untracked.txt", staged=False)
        assert len(oversized_diff.hunks) == 1
        assert any(
            ln.origin == "+" and "big-29" in ln.content for ln in oversized_diff.hunks[0].lines
        )

        # Staged file on unborn HEAD
        (empty_repo.path / "first.txt").write_text("hello unborn\n", encoding="utf-8")
        subprocess.run(["git", "add", "first.txt"], cwd=empty_repo.path, check=True)
        staged_unborn = read_ops.get_diff(empty_repo, "first.txt", staged=True)
        assert len(staged_unborn.hunks) == 1
        assert any(
            ln.origin == "+" and "hello unborn" in ln.content for ln in staged_unborn.hunks[0].lines
        )

    def test_symlink_and_path_traversal_do_not_leak_external_files(self, simple_repo, tmp_path):
        outside_secret = tmp_path / "host_secret.txt"
        outside_secret.write_text("TOP_SECRET_OUTSIDE_REPO\n", encoding="utf-8")

        # 1. Explicit ../ traversal must return empty Diff and never read external file
        trav_unstaged = read_ops.get_diff(simple_repo, "../host_secret.txt", staged=False)
        trav_staged = read_ops.get_diff(simple_repo, "../host_secret.txt", staged=True)
        assert trav_unstaged.hunks == []
        assert trav_staged.hunks == []

        # 2. Untracked symlink pointing outside repo must show link target, never target contents
        sym = simple_repo.path / "escape_link"
        sym.symlink_to(outside_secret)
        sym_diff = read_ops.get_diff(simple_repo, "escape_link", staged=False)
        joined = "\n".join(ln.content for h in sym_diff.hunks for ln in h.lines)
        assert "TOP_SECRET_OUTSIDE_REPO" not in joined
        assert str(outside_secret) in joined

        # 3. Tracked symlink modified to another outside file falls back safely without reading it
        subprocess.run(["git", "add", "escape_link"], cwd=simple_repo.path, check=True)
        subprocess.run(
            ["git", "commit", "-m", "add tracked symlink"],
            cwd=simple_repo.path,
            check=True,
        )
        sym.unlink()
        outside_secret2 = tmp_path / "host_secret_2.txt"
        outside_secret2.write_text("SECOND_SECRET_CONTENT\n", encoding="utf-8")
        sym.symlink_to(outside_secret2)

        tracked_sym_diff = read_ops.get_diff(simple_repo, "escape_link", staged=False)
        joined2 = "\n".join(ln.content for h in tracked_sym_diff.hunks for ln in h.lines)
        assert "SECOND_SECRET_CONTENT" not in joined2
        assert str(outside_secret2) in joined2

    def test_stage_hunk_round_trip_and_52k_line_truncation(self, multi_commit_repo):
        target = multi_commit_repo.path / "file.txt"
        base = "\n".join(f"line{i}" for i in range(1, 25)) + "\n"
        target.write_text(base, encoding="utf-8")
        subprocess.run(["git", "add", "file.txt"], cwd=multi_commit_repo.path, check=True)
        subprocess.run(
            ["git", "commit", "-m", "expand file"], cwd=multi_commit_repo.path, check=True
        )

        lines = base.splitlines()
        lines[1] = "line2_hunk_a"
        lines[20] = "line21_hunk_b"
        target.write_text("\n".join(lines) + "\n", encoding="utf-8")

        diff_before = read_ops.get_diff(multi_commit_repo, "file.txt", staged=False)
        assert len(diff_before.hunks) == 2

        # Stage only hunk 0 using exact ID produced by single-file get_diff()
        engine.stage_hunk(multi_commit_repo, "file.txt", diff_before.hunks[0].id)
        staged = read_ops.get_diff(multi_commit_repo, "file.txt", staged=True)
        unstaged = read_ops.get_diff(multi_commit_repo, "file.txt", staged=False)
        assert len(staged.hunks) == 1
        assert any("line2_hunk_a" in ln.content for ln in staged.hunks[0].lines)
        assert len(unstaged.hunks) == 1
        assert any("line21_hunk_b" in ln.content for ln in unstaged.hunks[0].lines)

        # 52k-line max_lines truncation in single-file get_diff
        huge = multi_commit_repo.path / "huge_52k.txt"
        huge.write_text("".join(f"orig-{i:06d}\n" for i in range(52000)), encoding="utf-8")
        subprocess.run(["git", "add", "huge_52k.txt"], cwd=multi_commit_repo.path, check=True)
        subprocess.run(["git", "commit", "-m", "52k file"], cwd=multi_commit_repo.path, check=True)
        huge.write_text("".join(f"edit-{i:06d}\n" for i in range(52000)), encoding="utf-8")

        capped = read_ops.get_diff(multi_commit_repo, "huge_52k.txt", staged=False, max_lines=100)
        assert capped.is_truncated is True
        assert sum(len(h.lines) for h in capped.hunks) == 100

    def test_partial_clone_tree0_and_sparse_get_diff(self, tmp_path: Path):
        src = tmp_path / "src_mono"
        src.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=src, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=src, check=True)
        subprocess.run(["git", "config", "user.email", "t@e.com"], cwd=src, check=True)
        (src / "apps" / "api").mkdir(parents=True)
        (src / "apps" / "api" / "app.py").write_text("v = 1\n", encoding="utf-8")
        (src / "libs" / "core").mkdir(parents=True)
        (src / "libs" / "core" / "mod.py").write_text("m = 1\n", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=src, check=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=src, check=True)

        bare = tmp_path / "bare.git"
        subprocess.run(["git", "clone", "--bare", str(src), str(bare)], check=True)
        subprocess.run(["git", "config", "uploadpack.allowFilter", "true"], cwd=bare, check=True)
        subprocess.run(
            ["git", "config", "uploadpack.allowAnySHA1InWant", "true"], cwd=bare, check=True
        )

        dest = tmp_path / "tree0_sparse"
        clone_res = engine.clone_repo(bare.as_uri(), dest, filter_spec="tree:0", sparse=True)
        assert clone_res.path == dest
        engine.set_sparse_directories(dest, ["apps/api"], cone=True)
        handle = engine.open_repo(dest)

        # Modify a checked-out sparse file and verify get_diff skips non-checked-out files
        (dest / "apps" / "api" / "app.py").write_text("v = 2\n", encoding="utf-8")
        d = read_ops.get_diff(handle, "apps/api/app.py", staged=False)
        assert len(d.hunks) == 1
        assert any(ln.origin == "+" and "v = 2" in ln.content for ln in d.hunks[0].lines)

        # Excluded sparse file must NOT show phantom deletion diff
        excluded = read_ops.get_diff(handle, "libs/core/mod.py", staged=False)
        assert excluded.hunks == []


class TestBlame:
    def test_blame_file(self, multi_commit_repo):
        lines = read_ops.blame_file(multi_commit_repo, "file.txt")
        assert len(lines) == 3
        assert lines[0].line_content == "line1"
        assert lines[1].line_content == "line2"
        assert lines[2].line_content == "line3"


class TestCommitDetailsAndFilters:
    def test_get_commit_file_stats_and_diff(self, multi_commit_repo):
        commits = read_ops.get_log(multi_commit_repo)
        top_commit = commits[0]
        stats = read_ops.get_commit_file_stats(multi_commit_repo, top_commit.sha)
        assert len(stats) == 1
        assert stats[0].path == "file.txt"
        assert stats[0].additions > 0

        diff = read_ops.get_commit_diff(multi_commit_repo, top_commit.sha, "file.txt")
        assert diff.path == "file.txt"
        assert len(diff.hunks) >= 1

    def test_get_ref_labels(self, multi_commit_repo):
        labels = read_ops.get_ref_labels(multi_commit_repo)
        commits = read_ops.get_log(multi_commit_repo)
        top_sha = commits[0].sha
        assert top_sha in labels
        assert any(lbl.kind in ("branch", "head") for lbl in labels[top_sha])

    def test_get_ref_labels_handles_tree_and_blob_tags_without_errors(
        self, multi_commit_repo, caplog: pytest.LogCaptureFixture
    ):
        r = multi_commit_repo.pygit2_repo
        head_commit = r.head.peel(pygit2.Commit)
        sig = pygit2.Signature("Tagger", "tagger@example.com", 1_700_000_000, 0)

        # Create annotated tags pointing to non-commit objects (tree + blob, like git v2.6.11-tree)
        r.create_tag("v0-tree-tag", head_commit.tree.id, pygit2.GIT_OBJECT_TREE, sig, "tree tag")
        blob_oid = head_commit.tree["file.txt"].id
        r.create_tag("v0-blob-tag", blob_oid, pygit2.GIT_OBJECT_BLOB, sig, "blob tag")
        r.create_tag("v1.0.0", head_commit.id, pygit2.GIT_OBJECT_COMMIT, sig, "commit tag")

        caplog.clear()
        with caplog.at_level(logging.DEBUG, logger="wrench.core.read_ops"):
            labels = read_ops.get_ref_labels(multi_commit_repo)

        top_labels = [lbl.name for lbl in labels.get(str(head_commit.id), [])]
        all_names = [lbl.name for lst in labels.values() for lbl in lst]
        assert "v1.0.0" in top_labels
        assert "v0-tree-tag" not in all_names
        assert "v0-blob-tag" not in all_names
        assert "Failed resolving tag commit for label" not in caplog.text

    def test_get_log_path_filter(self, multi_commit_repo):
        from wrench.core.engine import LogFilter

        # file.txt exists in all commits
        commits = read_ops.get_log(multi_commit_repo, filter=LogFilter(path="file.txt"))
        assert len(commits) == 3

        # nonexistent.txt does not exist
        empty_commits = read_ops.get_log(
            multi_commit_repo, filter=LogFilter(path="nonexistent.txt")
        )
        assert len(empty_commits) == 0
