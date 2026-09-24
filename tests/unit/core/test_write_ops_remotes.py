"""Unit tests for streaming git execution, progress parsing, and failure classification."""

import sys
import threading
import time

import pytest

from wrench.core import write_ops
from wrench.core.exceptions import (
    AuthFailedError,
    AuthRequiredError,
    CLITimeoutError,
    CloneAbortedError,
    GitCommandError,
    MergeRequiredError,
    PushRejectedError,
    WorkflowScopeRequiredError,
)
from wrench.core.write_ops import (
    _classify_git_error,
    _parse_progress,
    run_git,
    run_git_streaming,
)


class TestProgressParsing:
    def test_parse_progress_standard_stages(self):
        cases = [
            ("Counting objects:  12% (12/100)", (12, "Counting objects")),
            ("remote: Counting objects:  50% (50/100)", (50, "Counting objects")),
            ("Compressing objects: 100% (100/100)", (100, "Compressing objects")),
            ("Writing objects:  80% (80/100)", (80, "Writing objects")),
            ("Receiving objects:  95% (950/1000)", (95, "Receiving objects")),
            ("Resolving deltas:  40% (40/100)", (40, "Resolving deltas")),
            ("remote: Enumerating objects: 10% (10/100)", (10, "Enumerating objects")),
        ]
        for line, expected in cases:
            assert _parse_progress(line) == expected

    def test_parse_progress_non_matching_lines(self):
        non_matching = [
            "Total 100 (delta 50), reused 0 (delta 0)",
            "remote: Compressing objects: done",
            "Everything up-to-date",
            "",
            "To https://github.com/user/repo.git",
        ]
        for line in non_matching:
            assert _parse_progress(line) is None


class TestFailureClassification:
    def test_push_rejected(self):
        stderr = (
            "To github.com:repo\n"
            " ! [rejected] main -> main (fetch first)\n"
            "error: failed to push"
        )
        err = _classify_git_error(["push", "origin", "main"], 1, stderr)
        assert isinstance(err, PushRejectedError)

    def test_push_rejected_workflow_scope(self):
        stderr = (
            "To https://github.com/uzair777-dev/Wrench.git\n"
            " ! [remote rejected] master -> master (refusing to allow an OAuth App to create or "
            "update workflow `.github/workflows/ci.yml` without `workflow` scope)\n"
            "error: failed to push some refs"
        )
        err = _classify_git_error(["push", "origin", "master"], 1, stderr)
        assert isinstance(err, WorkflowScopeRequiredError)
        assert not isinstance(err, PushRejectedError)

    def test_pull_merge_required(self):
        stderr = "fatal: Not possible to fast-forward, aborting."
        err = _classify_git_error(["pull", "--ff-only", "origin", "main"], 128, stderr)
        assert isinstance(err, MergeRequiredError)

    def test_auth_failed_http(self):
        stderr = "fatal: Authentication failed for 'https://github.com/user/repo.git/'"
        err = _classify_git_error(
            ["fetch", "origin"], 128, stderr, remote_url="https://github.com/user/repo.git"
        )
        assert isinstance(err, AuthFailedError)
        assert err.host == "github.com"

    def test_auth_failed_ssh(self):
        stderr = "git@github.com: Permission denied (publickey)."
        err = _classify_git_error(
            ["fetch", "origin"], 128, stderr, remote_url="git@github.com:user/repo.git"
        )
        assert isinstance(err, AuthFailedError)
        assert err.host == "github.com"

    def test_auth_failed_http_status_codes(self):
        stderr_403 = (
            "fatal: unable to access 'https://gitlab.com/repo': "
            "The requested URL returned error: 403"
        )
        err = _classify_git_error(
            ["fetch", "origin"], 128, stderr_403, remote_url="https://gitlab.com/repo"
        )
        assert isinstance(err, AuthFailedError)
        assert err.host == "gitlab.com"

    def test_auth_required_terminal_prompts_disabled(self):
        stderr = (
            "fatal: could not read Username for 'https://github.com': " "terminal prompts disabled"
        )
        err = _classify_git_error(
            ["fetch", "origin"], 128, stderr, remote_url="https://github.com/user/repo.git"
        )
        assert isinstance(err, AuthRequiredError)
        assert err.host == "github.com"

    def test_network_error_falls_back_to_git_command_error(self):
        stderr = "fatal: Could not resolve host: github.com"
        err = _classify_git_error(["fetch", "origin"], 128, stderr)
        assert isinstance(err, GitCommandError)
        assert not isinstance(err, (AuthFailedError, AuthRequiredError, PushRejectedError))


class TestRunGitStreaming:
    def test_streaming_dual_pipe_large_buffer_no_deadlock(self, tmp_path):
        # Generate script that writes >64 KiB to stderr and stdout concurrently
        script = (
            "import sys\n"
            "for i in range(2000):\n"
            "    sys.stdout.write('O' * 100 + '\\n')\n"
            "    sys.stderr.write('E' * 100 + '\\n')\n"
            "sys.stdout.flush()\n"
            "sys.stderr.flush()\n"
        )
        code_file = tmp_path / "writer.py"
        code_file.write_text(script)

        stderr_lines = []

        def on_line(line: str):
            stderr_lines.append(line)

        # We pass python via git alias/shim or custom command runner
        args = ["-c", f"alias.test=!{sys.executable} {code_file}", "test"]
        code, stdout, stderr = run_git_streaming(tmp_path, args, timeout=10, on_stderr_line=on_line)

        assert code == 0
        assert len(stdout) >= 200000
        assert len(stderr) >= 200000
        assert len(stderr_lines) >= 2000

    def test_streaming_progress_carriage_return_split(self, tmp_path):
        script = (
            "import sys\n"
            "sys.stderr.write('Counting objects:  10%\\r')\n"
            "sys.stderr.write('Counting objects:  50%\\r')\n"
            "sys.stderr.write('Counting objects: 100%\\n')\n"
            "sys.stderr.flush()\n"
        )
        code_file = tmp_path / "progress.py"
        code_file.write_text(script)

        fragments = []

        def on_fragment(line: str):
            fragments.append(line)

        args = ["-c", f"alias.test=!{sys.executable} {code_file}", "test"]
        code, stdout, stderr = run_git_streaming(
            tmp_path, args, timeout=10, on_stderr_line=on_fragment
        )

        assert code == 0
        assert "Counting objects:  10%" in fragments
        assert "Counting objects:  50%" in fragments
        assert "Counting objects: 100%" in fragments

    def test_streaming_timeout_raises_cli_timeout_error(self, tmp_path):
        script = "import time\ntime.sleep(5)\n"
        code_file = tmp_path / "sleep.py"
        code_file.write_text(script)

        args = ["-c", f"alias.test=!{sys.executable} {code_file}", "test"]
        with pytest.raises(CLITimeoutError):
            run_git_streaming(tmp_path, args, timeout=1)

    def test_streaming_cancellation(self, tmp_path):
        script = "import time\ntime.sleep(5)\n"
        code_file = tmp_path / "sleep2.py"
        code_file.write_text(script)

        cancel_event = threading.Event()

        def set_cancel():
            time.sleep(0.2)
            cancel_event.set()

        t = threading.Thread(target=set_cancel)
        t.start()

        args = ["-c", f"alias.test=!{sys.executable} {code_file}", "test"]
        code, stdout, stderr = run_git_streaming(
            tmp_path, args, timeout=10, cancel_event=cancel_event
        )
        t.join()

        # Non-zero returncode on termination
        assert code != 0
        assert cancel_event.is_set()


@pytest.fixture
def bare_repo_fixture(tmp_path):
    bare_dir = tmp_path / "remote.git"
    run_git(tmp_path, ["init", "--bare", str(bare_dir)])
    run_git(bare_dir, ["symbolic-ref", "HEAD", "refs/heads/main"])

    clone1_dir = tmp_path / "clone1"
    run_git(tmp_path, ["clone", str(bare_dir), str(clone1_dir)])
    run_git(clone1_dir, ["config", "user.name", "Test User"])
    run_git(clone1_dir, ["config", "user.email", "test@example.com"])

    (clone1_dir / "README.md").write_text("initial content\n")
    run_git(clone1_dir, ["add", "README.md"])
    run_git(clone1_dir, ["commit", "-m", "Initial commit"])
    run_git(clone1_dir, ["branch", "-M", "main"])
    run_git(clone1_dir, ["push", "-u", "origin", "main"])

    clone2_dir = tmp_path / "clone2"
    run_git(tmp_path, ["clone", str(bare_dir), str(clone2_dir)])
    run_git(clone2_dir, ["config", "user.name", "Test User 2"])
    run_git(clone2_dir, ["config", "user.email", "test2@example.com"])

    return bare_dir, clone1_dir, clone2_dir


class TestRemoteOperations:
    def test_push_happy_path(self, bare_repo_fixture):
        bare_dir, clone1_dir, _ = bare_repo_fixture
        (clone1_dir / "file.txt").write_text("hello from clone1\n")
        run_git(clone1_dir, ["add", "file.txt"])
        run_git(clone1_dir, ["commit", "-m", "Commit from clone1"])

        progress_events = []

        def on_prog(pct, stage):
            progress_events.append((pct, stage))

        write_ops.push(clone1_dir, "origin", "main", progress_cb=on_prog)

        rev1 = run_git(clone1_dir, ["rev-parse", "HEAD"]).stdout.strip()
        rev_bare = run_git(bare_dir, ["rev-parse", "main"]).stdout.strip()
        assert rev1 == rev_bare

    def test_push_rejected_non_fast_forward(self, bare_repo_fixture):
        _, clone1_dir, clone2_dir = bare_repo_fixture

        # Advance remote via clone2
        (clone2_dir / "file2.txt").write_text("from clone 2\n")
        run_git(clone2_dir, ["add", "file2.txt"])
        run_git(clone2_dir, ["commit", "-m", "Commit from clone2"])
        write_ops.push(clone2_dir, "origin", "main")

        # Create divergent commit in clone1
        (clone1_dir / "file1.txt").write_text("from clone 1\n")
        run_git(clone1_dir, ["add", "file1.txt"])
        run_git(clone1_dir, ["commit", "-m", "Divergent commit in clone1"])

        with pytest.raises(PushRejectedError):
            write_ops.push(clone1_dir, "origin", "main")

    def test_pull_happy_path_fast_forward(self, bare_repo_fixture):
        _, clone1_dir, clone2_dir = bare_repo_fixture

        (clone2_dir / "update.txt").write_text("new content\n")
        run_git(clone2_dir, ["add", "update.txt"])
        run_git(clone2_dir, ["commit", "-m", "Update from clone2"])
        write_ops.push(clone2_dir, "origin", "main")

        write_ops.pull(clone1_dir, "origin", "main")
        assert (clone1_dir / "update.txt").exists()

    def test_pull_merge_required(self, bare_repo_fixture):
        _, clone1_dir, clone2_dir = bare_repo_fixture

        # Advance remote via clone2
        (clone2_dir / "c2.txt").write_text("c2\n")
        run_git(clone2_dir, ["add", "c2.txt"])
        run_git(clone2_dir, ["commit", "-m", "c2 commit"])
        write_ops.push(clone2_dir, "origin", "main")

        # Divergent commit in clone1
        (clone1_dir / "c1.txt").write_text("c1\n")
        run_git(clone1_dir, ["add", "c1.txt"])
        run_git(clone1_dir, ["commit", "-m", "c1 commit"])

        with pytest.raises(MergeRequiredError):
            write_ops.pull(clone1_dir, "origin", "main")

    def test_fetch_records_setting(self, bare_repo_fixture, tmp_path):
        import sqlite3

        from wrench.storage import settings

        _, clone1_dir, _ = bare_repo_fixture

        db_file = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_file))
        conn.row_factory = sqlite3.Row
        conn.execute("""CREATE TABLE app_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )""")
        conn.commit()

        write_ops.fetch(clone1_dir, "origin", db_conn=conn)
        val = settings.get_setting(conn, "remote_last_fetch.origin")
        assert val is not None

    def test_clone_repo_success_and_config(self, bare_repo_fixture, tmp_path):
        bare_dir, _, _ = bare_repo_fixture
        dest = tmp_path / "new_clone"

        result = write_ops.clone_repo(str(bare_dir), dest)
        assert result.path == dest
        assert (dest / ".git").exists()
        assert (dest / "README.md").exists()

        # Check credential configuration
        h = run_git(dest, ["config", "--local", "credential.helper"]).stdout.strip()
        p = run_git(dest, ["config", "--local", "credential.useHttpPath"]).stdout.strip()
        assert h == "wrench"
        assert p == "true"

    def test_clone_repo_destination_exists_rejected(self, bare_repo_fixture, tmp_path):
        bare_dir, _, _ = bare_repo_fixture
        dest = tmp_path / "existing_dir"
        dest.mkdir()
        (dest / "file.txt").write_text("existing")

        with pytest.raises(GitCommandError) as exc_info:
            write_ops.clone_repo(str(bare_dir), dest)
        assert "exists" in str(exc_info.value)

    def test_clone_repo_cancelled_cleans_up(self, bare_repo_fixture, tmp_path):
        bare_dir, _, _ = bare_repo_fixture
        dest = tmp_path / "cancelled_clone"

        cancel_event = threading.Event()
        cancel_event.set()

        with pytest.raises(CloneAbortedError):
            write_ops.clone_repo(str(bare_dir), dest, cancel_event=cancel_event)

        assert not dest.exists()
