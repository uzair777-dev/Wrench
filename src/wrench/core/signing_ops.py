"""Cryptographic commit and tag signature verification and key discovery (VP-18, FR-2.9, FR-2.10)."""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any

from wrench.core import write_ops
from wrench.core.models import SignatureStatus, SigningKey

logger = logging.getLogger(__name__)

# LRU Cache for commit signature verification: (repo_path_str, oid) -> SignatureStatus
_SIGNATURE_CACHE: dict[tuple[str, str], SignatureStatus] = {}
_MAX_CACHE_ENTRIES = 10000


def parse_signature_log_output(output: str) -> dict[str, SignatureStatus]:
    """Parse git log --format=%H|%G?|%GS|%GF|%GK|%GT output into SignatureStatus mappings."""
    results: dict[str, SignatureStatus] = {}
    if not output:
        return results

    # Git %G? porcelain flags:
    # 'G': Good (valid) signature
    # 'B': Bad signature
    # 'U': Good signature with unknown validity / untrusted key
    # 'X': Good signature that has expired
    # 'Y': Good signature made by an expired key
    # 'R': Good signature made by a revoked key
    # 'E': Signature cannot be checked (missing key, etc.)
    # 'N': No signature
    status_map = {
        "G": "verified",
        "B": "bad",
        "U": "unverified_key",
        "X": "expired",
        "Y": "expired",
        "R": "revoked",
        "E": "unverified_key",
        "N": "unsigned",
    }

    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("|")
        if not parts:
            continue
        oid = parts[0].strip()
        flag = parts[1].strip() if len(parts) > 1 else "N"
        signer = parts[2].strip() if len(parts) > 2 and parts[2].strip() else None
        fingerprint = parts[3].strip() if len(parts) > 3 and parts[3].strip() else None
        key_id = parts[4].strip() if len(parts) > 4 and parts[4].strip() else None
        trust = parts[5].strip() if len(parts) > 5 and parts[5].strip() else None

        state = status_map.get(flag, "unsigned")

        details_parts = []
        if key_id:
            details_parts.append(f"Key: {key_id}")
        if trust:
            details_parts.append(f"Trust: {trust}")
        details = ", ".join(details_parts) if details_parts else None

        key_type = "gpg"
        if fingerprint and (fingerprint.startswith("SHA256:") or fingerprint.startswith("ssh-")):
            key_type = "ssh"

        results[oid] = SignatureStatus(
            oid=oid,
            state=state,
            signer=signer,
            key_fingerprint=fingerprint,
            key_type=key_type,
            validity_details=details,
        )

    return results


def verify_commit_signatures_batch(
    repo_path: Path | str,
    oids: list[str],
    settings: Any = None,
) -> dict[str, SignatureStatus]:
    """Batch-verify signatures for specified commit OIDs in a single subprocess call."""
    if not oids:
        return {}

    repo_str = str(Path(repo_path).resolve())

    # Fast short-circuit if signature badges are disabled in Settings (OPT-1 / Gate G4)
    if settings is not None:
        try:
            if hasattr(settings, "is_enabled") and not settings.is_enabled(
                "signing.verify_badges_in_graph.enabled", repo_str
            ):
                return {}
        except Exception as e:
            logger.debug("Failed querying signing settings: %s", e)

    results: dict[str, SignatureStatus] = {}
    missing_oids: list[str] = []

    # Check in-memory cache first
    for oid in oids:
        cached = _SIGNATURE_CACHE.get((repo_str, oid))
        if cached is not None:
            results[oid] = cached
        else:
            missing_oids.append(oid)

    if not missing_oids:
        return results

    # Execute single batch git log query with --no-walk
    cmd = [
        "log",
        "--no-walk",
        "--format=%H|%G?|%GS|%GF|%GK|%GT",
        *missing_oids,
    ]
    try:
        res = write_ops.run_git(repo_str, cmd, check=True)
        stdout_str = (
            res.stdout
            if isinstance(res.stdout, str)
            else res.stdout.decode("utf-8", errors="replace")
        )
        new_statuses = parse_signature_log_output(stdout_str)
    except write_ops.GitCommandError as e:
        logger.debug("Signature batch verification failed: %s", e)
        new_statuses = {}

    # Store in bounded LRU cache
    for oid in missing_oids:
        status = new_statuses.get(
            oid,
            SignatureStatus(oid=oid, state="unsigned"),
        )
        if len(_SIGNATURE_CACHE) >= _MAX_CACHE_ENTRIES:
            # Simple eviction of oldest entries
            keys_to_remove = list(_SIGNATURE_CACHE.keys())[:1000]
            for k in keys_to_remove:
                _SIGNATURE_CACHE.pop(k, None)
        _SIGNATURE_CACHE[(repo_str, oid)] = status
        results[oid] = status

    return results


def clear_signature_cache() -> None:
    """Clear in-memory signature verification cache."""
    _SIGNATURE_CACHE.clear()


def list_available_signing_keys() -> list[SigningKey]:
    """Scan local GPG and SSH keys available for signing."""
    keys: list[SigningKey] = []

    # 1. Discover OpenPGP secret keys via gpg CLI
    gpg_bin = shutil.which("gpg") or shutil.which("gpg2")
    if gpg_bin:
        try:
            proc = subprocess.run(
                [gpg_bin, "--batch", "--with-colons", "--list-secret-keys"],
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            )
            current_sec = ""
            current_fp = ""
            current_uid = ""
            for line in proc.stdout.splitlines():
                parts = line.split(":")
                record_type = parts[0] if parts else ""
                if record_type in ("sec", "ssb"):
                    current_sec = parts[4] if len(parts) > 4 else ""
                elif record_type == "fpr":
                    if not current_fp and len(parts) > 9:
                        current_fp = parts[9]
                elif record_type == "uid":
                    if not current_uid and len(parts) > 9:
                        current_uid = parts[9]
                if current_sec and current_fp and current_uid:
                    keys.append(
                        SigningKey(
                            key_id=current_sec,
                            key_type="openpgp",
                            display_name=f"GPG: {current_uid} ({current_sec[-8:]})",
                            fingerprint=current_fp,
                            email=current_uid,
                        )
                    )
                    current_sec = ""
                    current_fp = ""
                    current_uid = ""
        except Exception as e:
            logger.debug("Failed listing GPG keys: %s", e)

    # 2. Discover SSH public keys in ~/.ssh
    ssh_dir = Path.home() / ".ssh"
    if ssh_dir.exists() and ssh_dir.is_dir():
        try:
            for pub_path in sorted(ssh_dir.glob("*.pub")):
                try:
                    content = pub_path.read_text(encoding="utf-8", errors="replace").strip()
                    parts = content.split()
                    if len(parts) >= 2:
                        key_type = parts[0]
                        comment = parts[2] if len(parts) > 2 else pub_path.stem
                        keys.append(
                            SigningKey(
                                key_id=str(pub_path),
                                key_type="ssh",
                                display_name=f"SSH: {comment} ({key_type})",
                                fingerprint=str(pub_path),
                                email=comment,
                            )
                        )
                except OSError as e:
                    logger.debug("Failed reading SSH pubkey %s: %s", pub_path, e)
        except Exception as e:
            logger.debug("Failed scanning SSH keys: %s", e)

    return keys
