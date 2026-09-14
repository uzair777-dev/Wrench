"""Unit tests for streaming git execution, progress parsing, and failure classification."""

import sys
import threading
import time

import pytest

from wrench.core.exceptions import (
    AuthFailedError,
    AuthRequiredError,
    CLITimeoutError,
    GitCommandError,
    MergeRequiredError,
    PushRejectedError,
)
from wrench.core.write_ops import (
    _classify_git_error,
    _parse_progress,
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
