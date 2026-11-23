"""Core unit & integration tests for VP-18 Commit & Tag Signing."""

from __future__ import annotations

import subprocess
from pathlib import Path

from wrench.core import engine
from wrench.core.models import SignatureStatus, SigningKey
from wrench.core.signing_ops import (
    _SIGNATURE_CACHE,
    list_available_signing_keys,
    parse_signature_log_output,
)
from wrench.credentials.signing_askpass import SigningAskpassBridge


def _git(cwd: Path, *args: str) -> str:
    res = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )
    return res.stdout.strip()


def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-b", "main")
    _git(path, "config", "user.name", "Wrench Tester")
    _git(path, "config", "user.email", "tester@example.com")
    (path / "file.txt").write_text("content\n", encoding="utf-8")
    _git(path, "add", "-A")
    _git(path, "commit", "-m", "initial commit")
    return path


def test_parse_signature_log_output() -> None:
    # 1. Good valid signature
    line_g = (
        "1111111111111111111111111111111111111111|G|Alice <alice@test.org>|4A3B2C1D|4A3B2C1D|PGP"
    )
    res_g = parse_signature_log_output(line_g)
    assert res_g["1111111111111111111111111111111111111111"] == SignatureStatus(
        oid="1111111111111111111111111111111111111111",
        state="verified",
        signer="Alice <alice@test.org>",
        key_fingerprint="4A3B2C1D",
        key_type="gpg",
        validity_details="Key: 4A3B2C1D, Trust: PGP",
    )

    # 2. Good signature with untrusted/unverified key (U) with SSH fingerprint
    line_u = (
        "2222222222222222222222222222222222222222|U|Bob <bob@test.org>|SHA256:abc123|DEADBEEF|SSH"
    )
    res_u = parse_signature_log_output(line_u)
    assert res_u["2222222222222222222222222222222222222222"].state == "unverified_key"
    assert res_u["2222222222222222222222222222222222222222"].key_type == "ssh"

    # 3. Bad signature (B)
    line_b = "3333333333333333333333333333333333333333|B|Eve <eve@bad.com>|||"
    res_b = parse_signature_log_output(line_b)
    assert res_b["3333333333333333333333333333333333333333"].state == "bad"

    # 4. Expired signature (X)
    line_x = "4444444444444444444444444444444444444444|X|Charlie <charlie@test.org>|KEY1|KEY1|PGP"
    res_x = parse_signature_log_output(line_x)
    assert res_x["4444444444444444444444444444444444444444"].state == "expired"

    # 5. Revoked signature (R)
    line_r = "5555555555555555555555555555555555555555|R|Dave <dave@test.org>|KEY2|KEY2|PGP"
    res_r = parse_signature_log_output(line_r)
    assert res_r["5555555555555555555555555555555555555555"].state == "revoked"

    # 6. Unsigned commit (N)
    line_n = "6666666666666666666666666666666666666666|N||||"
    res_n = parse_signature_log_output(line_n)
    assert res_n["6666666666666666666666666666666666666666"].state == "unsigned"


def test_verify_commit_signatures_real_repo_and_cache(tmp_path: Path) -> None:
    repo_dir = _init_repo(tmp_path / "sig-repo")
    sha = _git(repo_dir, "rev-parse", "HEAD")

    # Clear test cache
    _SIGNATURE_CACHE.clear()

    # 1. First verification on real unsigned commit
    sigs = engine.verify_commit_signatures(repo_dir, [sha])
    assert sha in sigs
    assert sigs[sha].state == "unsigned"

    # Cache should now have the entry
    assert (str(repo_dir.resolve()), sha) in _SIGNATURE_CACHE

    # 2. Second verification should be fast cache hit
    sigs2 = engine.verify_commit_signatures(repo_dir, [sha])
    assert sigs2[sha] == sigs[sha]

    # Empty batch
    assert engine.verify_commit_signatures(repo_dir, []) == {}


def test_list_available_signing_keys() -> None:
    keys = list_available_signing_keys()
    assert isinstance(keys, list)
    for k in keys:
        assert isinstance(k, SigningKey)
        assert k.key_type in ("openpgp", "ssh", "x509")
        assert k.key_id


def test_signing_askpass_bridge_permissions() -> None:
    bridge = SigningAskpassBridge(prompt_callback=lambda p: "secret123")
    env = bridge.start()
    try:
        helper_path = Path(env["GIT_ASKPASS"])
        assert helper_path.exists()

        # Check SEC-4 filesystem permissions: directory must be 0o700, script must be 0o700, socket 0o600
        dir_stat = helper_path.parent.stat()
        file_stat = helper_path.stat()
        socket_path = Path(bridge._socket_path)
        socket_stat = socket_path.stat()

        assert (dir_stat.st_mode & 0o777) == 0o700
        assert (file_stat.st_mode & 0o777) == 0o700
        assert (socket_stat.st_mode & 0o777) == 0o600
    finally:
        bridge.stop()
        assert not helper_path.exists()
