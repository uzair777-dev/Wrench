from pathlib import Path
from unittest.mock import MagicMock, call, patch

from wrench.core.write_ops import push_incremental_batches


def test_push_incremental_batches_single_commit(tmp_path: Path):
    with (
        patch("wrench.core.write_ops.run_git") as mock_run,
        patch("wrench.core.write_ops.push") as mock_push,
    ):
        # Simulate rev-parse succeeding, rev-list returning 1 commit
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="refs/remotes/origin/main\n"),
            MagicMock(returncode=0, stdout="c1\n"),
        ]
        push_incremental_batches(tmp_path, "origin", "main", chunk_size=20)
        # For 1 commit, it delegates directly to push()
        mock_push.assert_called_once_with(
            tmp_path,
            "origin",
            "main",
            force=False,
            extra_config=None,
            progress_cb=None,
            cancel_event=None,
        )


def test_push_incremental_batches_multiple_commits(tmp_path: Path):
    with (
        patch("wrench.core.write_ops.run_git") as mock_run,
        patch("wrench.core.write_ops.push") as mock_push,
    ):
        # Simulate rev-parse succeeding, rev-list returning 45 commits
        commits = [f"commit_{i:02d}" for i in range(45)]
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="refs/remotes/origin/main\n"),
            MagicMock(returncode=0, stdout="\n".join(commits) + "\n"),
        ]

        progress_calls = []

        def on_prog(pct, stage):
            progress_calls.append((pct, stage))

        push_incremental_batches(
            tmp_path,
            "origin",
            "main",
            chunk_size=20,
            extra_config={"http.postBuffer": "524288000"},
            progress_cb=on_prog,
        )

        # 45 commits chunked by 20:
        # Chunk 1: commit index 19 (commit_19)
        # Chunk 2: commit index 39 (commit_39)
        # Final: HEAD / refs/heads/main
        assert mock_push.call_count == 3
        calls = mock_push.call_args_list

        assert calls[0] == call(
            tmp_path,
            "origin",
            "commit_19:refs/heads/main",
            force=False,
            extra_config={"http.postBuffer": "524288000"},
            cancel_event=None,
        )
        assert calls[1] == call(
            tmp_path,
            "origin",
            "commit_39:refs/heads/main",
            force=False,
            extra_config={"http.postBuffer": "524288000"},
            cancel_event=None,
        )
        assert calls[2] == call(
            tmp_path,
            "origin",
            "main",
            force=False,
            extra_config={"http.postBuffer": "524288000"},
            cancel_event=None,
        )
        assert len(progress_calls) >= 3
