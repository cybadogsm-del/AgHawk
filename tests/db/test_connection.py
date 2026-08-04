from pathlib import Path

from turfhelm.db.connection import connect_sqlite


def test_connect_sqlite_always_enforces_foreign_keys(tmp_path: Path) -> None:
    connection = connect_sqlite(tmp_path / "test.db")

    enabled = connection.execute("PRAGMA foreign_keys").fetchone()[0]

    assert enabled == 1
