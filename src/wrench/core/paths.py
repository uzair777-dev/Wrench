"""FR-11.2: Platform path abstraction via platformdirs."""

from pathlib import Path

lazy import platformdirs

from .exceptions import WrenchRepoNotFoundError

APP_NAME = "wrench"


def data_dir() -> Path:
    """Where Wrench stores its own data (DB, snapshot archives)."""
    return Path(platformdirs.user_data_dir(APP_NAME))


def config_dir() -> Path:
    """Where Wrench stores user configuration."""
    return Path(platformdirs.user_config_dir(APP_NAME))


def state_dir() -> Path:
    """Where Wrench stores runtime state (log files, etc)."""
    return Path(platformdirs.user_state_dir(APP_NAME))


def cache_dir() -> Path:
    """Where Wrench stores cache data (downloaded avatars, temp diffs)."""
    return Path(platformdirs.user_cache_dir(APP_NAME))


def resolve_git_dir(repo_path: Path | str) -> Path:
    """Resolve the actual gitdir path for standard repos, linked worktrees, or bare repos."""
    p = Path(repo_path)
    if not p.exists():
        raise WrenchRepoNotFoundError(f"Repository path does not exist: {p}")

    dot_git = p / ".git"
    if dot_git.is_dir():
        return dot_git

    if dot_git.is_file():
        raw_text = dot_git.read_text(encoding="utf-8", errors="replace")
        for line in raw_text.splitlines():
            stripped = line.strip()
            if stripped.startswith("gitdir:"):
                target_raw = stripped.split(":", 1)[1].strip()
                if not target_raw:
                    break
                target = Path(target_raw)
                if not target.is_absolute():
                    target = (p / target).resolve()
                if target.is_dir():
                    return target
                raise WrenchRepoNotFoundError(f"Linked worktree gitdir does not exist: {target}")
        raise WrenchRepoNotFoundError(f"Invalid .git gitdir file at: {dot_git}")

    if (p / "HEAD").is_file() and (p / "objects").is_dir():
        return p

    raise WrenchRepoNotFoundError(f"Not a git repository: {p}")
