"""Unit tests for SQLite database health checks and snapshot garbage collection."""

import sqlite3
from pathlib import Path

from wrench.storage.health import check_database_health, garbage_collect_snapshots, repair_database


class TestDatabaseHealth:
    def test_health_check_valid_db(self, tmp_path: Path):
        db_file = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_file))
        conn.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, name TEXT)")
        conn.execute("INSERT INTO test VALUES (1, 'wrench')")
        conn.commit()

        health = check_database_health(conn)
        assert health["status"] == "ok"
        assert health["integrity_ok"] is True
        assert health["fk_ok"] is True

    def test_repair_database_recreates_schema(self, tmp_path: Path):
        db_file = tmp_path / "corrupt.db"
        db_file.write_text("not a valid sqlite file", encoding="utf-8")

        new_conn = repair_database(db_file)
        health = check_database_health(new_conn)
        assert health["status"] == "ok"

        # Check that corrupt backup was created
        backups = list(tmp_path.glob("corrupt.corrupt-*"))
        assert len(backups) == 1

    def test_garbage_collect_snapshots_empty_repo(self, tmp_path: Path):
        git_dir = tmp_path / ".git"
        git_dir.mkdir(parents=True)
        conn = sqlite3.connect(":memory:")
        pruned = garbage_collect_snapshots(tmp_path, conn)
        assert pruned == 0
