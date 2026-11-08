from pathlib import Path
from unittest.mock import patch

import pytest

from wrench.core.exceptions import GitNetworkTransferError, PushRejectedError
from wrench.core.write_ops import _classify_git_error, push


def test_git_network_transfer_error_fields():
    err = GitNetworkTransferError(
        ["git", "push", "origin", "main"],
        1,
        "error: RPC failed; HTTP 408 curl 22",
        kind="timeout_408",
        status_code=408,
        curl_code=22,
        payload_mb=105.75,
        commit_count=3,
    )
    assert isinstance(err, PushRejectedError)
    assert err.kind == "timeout_408"
    assert err.status_code == 408
    assert err.curl_code == 22
    assert err.payload_mb == pytest.approx(105.75)
    assert err.commit_count == 3
    assert err.is_timeout is True
    assert err.is_http2_error is False
    assert err.is_payload_too_large is False
    assert "105.8 MB" in str(err)
    assert "HTTP 408" in str(err)


def test_git_network_transfer_error_http2():
    err = GitNetworkTransferError(
        ["git", "push"],
        1,
        "error: RPC failed; curl 92 HTTP/2 stream 0 was not closed cleanly",
        kind="http2_stream_92",
        curl_code=92,
    )
    assert err.is_http2_error is True
    assert err.is_timeout is False


def test_git_network_transfer_error_payload_too_large():
    err = GitNetworkTransferError(
        ["git", "push"],
        1,
        "error: RPC failed; HTTP 413",
        kind="payload_too_large_413",
        status_code=413,
    )
    assert err.is_payload_too_large is True


def test_classify_git_error_http_408_exact_log():
    stderr = (
        "Enumerating objects: 266, done.\n"
        "Counting objects: 100% (266/266), done.\n"
        "Delta compression using up to 8 threads\n"
        "Compressing objects: 100% (262/262), done.\n"
        "error: RPC failed; HTTP 408 curl 22 The requested URL returned error: 408\n"
        "send-pack: unexpected disconnect while reading sideband packet\n"
        "Writing objects: 100% (265/265), 105.75 MiB | 1.08 MiB/s, done.\n"
        "Total 265 (delta 55), reused 0 (delta 0), pack-reused 0 (from 0)\n"
        "fatal: the remote end hung up unexpectedly\n"
        "Everything up-to-date\n"
    )
    exc = _classify_git_error(["push", "origin", "main"], 1, stderr)
    assert isinstance(exc, GitNetworkTransferError)
    assert exc.kind == "timeout_408"
    assert exc.status_code == 408
    assert exc.curl_code == 22
    assert exc.payload_mb == pytest.approx(105.75, rel=1e-2)
    assert exc.is_timeout is True


def test_classify_git_error_curl_92():
    stderr = (
        "error: RPC failed; curl 92 HTTP/2 stream 0 was not closed cleanly: "
        "PROTOCOL_ERROR (err 1)\n"
        "fatal: the remote end hung up unexpectedly\n"
    )
    exc = _classify_git_error(["push", "origin", "main"], 1, stderr)
    assert isinstance(exc, GitNetworkTransferError)
    assert exc.kind == "http2_stream_92"
    assert exc.curl_code == 92
    assert exc.is_http2_error is True


def test_classify_git_error_curl_56():
    stderr = (
        "error: RPC failed; curl 56 OpenSSL SSL_read: Connection reset by peer, errno 10054\n"
        "fatal: the remote end hung up unexpectedly\n"
    )
    exc = _classify_git_error(["push", "origin", "main"], 1, stderr)
    assert isinstance(exc, GitNetworkTransferError)
    assert exc.kind == "connection_reset_56"
    assert exc.curl_code == 56


def test_classify_git_error_http_413():
    stderr = (
        "error: RPC failed; HTTP 413 curl 22 The requested URL returned error: 413\n"
        "fatal: the remote end hung up unexpectedly\n"
    )
    exc = _classify_git_error(["push", "origin", "main"], 1, stderr)
    assert isinstance(exc, GitNetworkTransferError)
    assert exc.kind == "payload_too_large_413"
    assert exc.status_code == 413
    assert exc.is_payload_too_large is True


def test_classify_git_error_sideband_disconnect():
    stderr = (
        "Writing objects: 100% (50/50), 30.50 MiB, done.\n"
        "send-pack: unexpected disconnect while reading sideband packet\n"
        "fatal: the remote end hung up unexpectedly\n"
    )
    exc = _classify_git_error(["push", "origin", "main"], 1, stderr)
    assert isinstance(exc, GitNetworkTransferError)
    assert exc.kind == "sideband_disconnect"
    assert exc.payload_mb == pytest.approx(30.50, rel=1e-2)


def test_push_with_extra_config(tmp_path: Path):
    with patch("wrench.core.write_ops.run_git_streaming") as mock_stream:
        mock_stream.return_value = (0, "", "")
        push(
            tmp_path,
            "origin",
            "main",
            extra_config={"http.postBuffer": "524288000", "http.version": "HTTP/1.1"},
        )
        passed_args = mock_stream.call_args[0][1]
        assert "-c" in passed_args
        assert "http.postBuffer=524288000" in passed_args
        assert "http.version=HTTP/1.1" in passed_args
        # Verify -c flags precede push subcommand
        c_idx = passed_args.index("-c")
        push_idx = passed_args.index("push")
        assert c_idx < push_idx


def test_classify_git_error_cloudflare_524():
    stderr = (
        "error: RPC failed; HTTP 524 curl 22 The requested URL returned error: 524\n"
        "fatal: the remote end hung up unexpectedly\n"
    )
    exc = _classify_git_error(["push", "origin", "main"], 1, stderr)
    assert isinstance(exc, GitNetworkTransferError)
    assert exc.kind == "timeout_408"
    assert exc.status_code == 524
    assert exc.is_timeout is True


def test_classify_git_error_curl_28_timeout():
    stderr = (
        "error: RPC failed; curl 28 Operation timed out after 300000 milliseconds\n"
        "fatal: the remote end hung up unexpectedly\n"
    )
    exc = _classify_git_error(["push", "origin", "main"], 1, stderr)
    assert isinstance(exc, GitNetworkTransferError)
    assert exc.kind == "timeout_408"
    assert exc.curl_code == 28
    assert exc.is_timeout is True
