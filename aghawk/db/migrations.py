from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

MIGRATIONS_DIRECTORY = Path(__file__).with_name("migrations")


def _statements(script: str) -> Iterator[str]:
    """Split SQLite script without breaking trigger bodies at inner semicolons."""

    buffer: list[str] = []
    for line in script.splitlines(keepends=True):
        buffer.append(line)
        candidate = "".join(buffer).strip()
        if candidate and sqlite3.complete_statement(candidate):
            yield candidate
            buffer.clear()

    remainder = "".join(buffer).strip()
    if remainder:
        yield remainder


def apply_migrations(
    connection: sqlite3.Connection,
    *,
    migrations_directory: Path = MIGRATIONS_DIRECTORY,
) -> None:
    """Apply pending migrations once inside a single locked transaction."""

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    connection.commit()

    try:
        connection.execute("BEGIN IMMEDIATE")
        applied = {
            row[0]
            for row in connection.execute("SELECT version FROM schema_migrations").fetchall()
        }

        for migration in sorted(migrations_directory.glob("*.sql")):
            if migration.name in applied:
                continue
            for statement in _statements(migration.read_text(encoding="utf-8")):
                connection.execute(statement)
            connection.execute(
                "INSERT INTO schema_migrations (version) VALUES (?)",
                (migration.name,),
            )

        connection.commit()
    except Exception:
        connection.rollback()
        raise
