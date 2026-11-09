"""Git bundle operations (create, verify, unbundle)."""

import logging
from pathlib import Path

from .models import BundleInfo
from .write_ops import run_git

logger = logging.getLogger(__name__)


def create_bundle(
    repo,
    output_path: Path | str,
    revs: list[str] | None = None,
) -> Path:
    """Create a git bundle file from repository references."""
    out = Path(output_path).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    if revs is None:
        revs = ["--all"]

    cmd = ["bundle", "create", "--", str(out), *revs]
    run_git(repo.path, cmd)
    return out


def verify_bundle(bundle_path: Path | str, repo=None) -> bool:
    """Verify that a bundle file is valid and its prerequisites exist."""
    b_path = Path(bundle_path).resolve()
    if not b_path.exists():
        return False

    cwd = repo.path if repo is not None else b_path.parent
    res = run_git(cwd, ["bundle", "verify", "--", str(b_path)], check=False)
    return res.returncode == 0


def unbundle(repo, bundle_path: Path | str) -> list[str]:
    """Unbundle objects and references into repository ODB."""
    b_path = Path(bundle_path).resolve()
    res = run_git(repo.path, ["bundle", "unbundle", "--", str(b_path)])

    unbundled_refs: list[str] = []
    output = (res.stdout or "") + (res.stderr or "")
    for line in output.splitlines():
        trimmed = line.strip()
        if trimmed:
            unbundled_refs.append(trimmed)

    return unbundled_refs


def get_bundle_info(bundle_path: Path | str, repo=None) -> BundleInfo:
    """Extract metadata, prerequisites, and contained refs from a bundle."""
    b_path = Path(bundle_path).resolve()
    if not b_path.exists():
        return BundleInfo(path=b_path, is_valid=False)

    cwd = repo.path if repo is not None else b_path.parent
    res = run_git(cwd, ["bundle", "verify", "--", str(b_path)], check=False)
    is_valid = res.returncode == 0

    prereqs: list[str] = []
    refs: list[str] = []

    parsing_prereqs = False
    parsing_refs = False

    for line in (res.stdout or "").splitlines():
        trimmed = line.strip()
        if "The bundle contains these" in trimmed:
            parsing_refs = True
            parsing_prereqs = False
            continue
        if "The bundle requires these" in trimmed:
            parsing_prereqs = True
            parsing_refs = False
            continue

        if parsing_refs and trimmed:
            refs.append(trimmed)
        elif parsing_prereqs and trimmed:
            prereqs.append(trimmed)

    return BundleInfo(
        path=b_path,
        is_valid=is_valid,
        prerequisites=prereqs,
        references=refs,
    )
