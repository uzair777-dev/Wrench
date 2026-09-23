"""Internal git credential helper script (git credential-wrench).

FR-4.3 / FR-4.5: Resolves credentials via Secret Service D-Bus with host and path
disambiguation for multi-account support.
"""

import sqlite3
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

from wrench import credentials
from wrench.core import paths
from wrench.storage import forge_accounts


def _host_of(url: str) -> str:
    """Extract normalized host component from a URL."""
    try:
        parsed = urlsplit(url)
        if parsed.hostname:
            return parsed.hostname.lower()
    except Exception:
        pass
    # Fallback for plain host:port or scp-style user@host:path
    raw = url.replace("https://", "").replace("http://", "").replace("ssh://", "").split("/")[0]
    host_part = raw.split(":")[0].lower()
    if "@" in host_part:
        host_part = host_part.split("@")[-1]
    return host_part


def _normalize_path(path: str) -> str:
    """Normalize repo path: strip leading slashes and .git suffix."""
    p = path.strip().lstrip("/")
    if p.endswith(".git"):
        p = p[:-4]
    return p.rstrip("/")


def _open_db(db_path: Path, readonly: bool = True) -> sqlite3.Connection:
    """Open database with retry logic for locked database errors."""
    for attempt in range(3):
        try:
            if readonly:
                conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            else:
                conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            return conn
        except sqlite3.OperationalError as e:
            if "locked" in str(e).lower() and attempt < 2:
                time.sleep(0.1)
                continue
            raise
    raise sqlite3.OperationalError("database is locked after retries")


def _resolve_account(conn: sqlite3.Connection, host: str, path_str: str | None):
    """Disambiguate account by host and path prefix."""
    normalized_host = host.split(":")[0].lower()
    accounts = forge_accounts.list_accounts(conn)
    candidates = [acc for acc in accounts if _host_of(acc.instance_url) == normalized_host]

    if not candidates:
        return None

    if path_str:
        norm_path = _normalize_path(path_str)
        if "/" in norm_path:
            parts = norm_path.split("/")
            owner_slug, repo_slug = parts[0], parts[1]
            candidate_ids = [acc.id for acc in candidates]
            link = forge_accounts.find_link_by_path(
                conn, owner_slug, repo_slug, candidate_account_ids=candidate_ids
            )
            if link:
                matching = [acc for acc in candidates if acc.id == link.forge_account_id]
                if len(matching) == 1:
                    return matching[0]

    # Fallback to single account on this host
    if len(candidates) == 1:
        return candidates[0]

    # Ambiguous multi-account match without valid link -> fail closed
    return None


def main() -> None:
    """Main entry point for git credential-wrench."""
    if len(sys.argv) != 2 or sys.argv[1] not in ("get", "store", "erase"):
        sys.exit(1)

    op = sys.argv[1]

    try:
        data: dict[str, str] = {}
        for line in sys.stdin:
            line = line.rstrip("\r\n")
            if not line:
                break
            if "=" in line:
                k, v = line.split("=", 1)
                data[k.strip()] = v

        protocol = data.get("protocol")
        if protocol not in ("http", "https"):
            sys.exit(0)

        host = data.get("host")
        if not host:
            sys.exit(0)

        db_path = paths.data_dir() / "wrench.db"
        if not db_path.exists():
            sys.exit(0)

        path_str = data.get("path")
        backend = credentials.get_backend()

        if op == "get":
            conn = _open_db(db_path, readonly=True)
            try:
                account = _resolve_account(conn, host, path_str)
                if not account:
                    sys.exit(0)

                secret_key = forge_accounts.get_account_secret_key(conn, account.id)
                if not secret_key:
                    sys.exit(0)

                secret = backend.get_secret(secret_key)
                if not secret:
                    sys.exit(0)

                if account.username:
                    sys.stdout.write(f"username={account.username}\n")
                sys.stdout.write(f"password={secret}\n")
                sys.stdout.flush()
                sys.exit(0)
            finally:
                conn.close()

        elif op == "store":
            password = data.get("password")
            if not password:
                sys.exit(0)

            conn = _open_db(db_path, readonly=True)
            try:
                account = _resolve_account(conn, host, path_str)
            finally:
                conn.close()

            if not account:
                sys.exit(0)

            conn = _open_db(db_path, readonly=True)
            try:
                secret_key = forge_accounts.get_account_secret_key(conn, account.id)
            finally:
                conn.close()

            if not secret_key:
                sys.exit(0)

            backend.store_secret(
                key=secret_key,
                secret=password,
                label=f"Wrench: {account.label}",
            )

            username = data.get("username")
            if username and username != account.username:
                rw_conn = _open_db(db_path, readonly=False)
                try:
                    forge_accounts.update_username(rw_conn, account.id, username)
                finally:
                    rw_conn.close()

            sys.exit(0)

        elif op == "erase":
            conn = _open_db(db_path, readonly=True)
            try:
                account = _resolve_account(conn, host, path_str)
                if not account:
                    sys.exit(0)

                secret_key = forge_accounts.get_account_secret_key(conn, account.id)
                if not secret_key:
                    sys.exit(0)

                backend.delete_secret(secret_key)
                sys.exit(0)
            finally:
                conn.close()

    except SystemExit:
        raise
    except Exception as e:
        sys.stderr.write(f"git-credential-wrench error: {e}\n")
        sys.exit(0)


if __name__ == "__main__":
    main()
