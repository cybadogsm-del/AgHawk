import sqlite3
from pathlib import Path

import pytest

from turfhelm.db.connection import connect_sqlite
from turfhelm.db.migrations import apply_migrations


def seeded_assignment_database(tmp_path: Path):
    connection = connect_sqlite(tmp_path / "test.db")
    apply_migrations(connection)
    connection.execute(
        "INSERT INTO organizations (id, name, slug) VALUES (?, ?, ?)",
        ("org-1", "Farm One", "farm-one"),
    )
    connection.execute(
        """
        INSERT INTO users (id, oidc_subject, email, display_name)
        VALUES (?, ?, ?, ?)
        """,
        ("driver-1", "auth0|driver-1", "driver@example.com", "Driver One"),
    )
    connection.execute(
        """
        INSERT INTO organization_memberships (organization_id, user_id, role)
        VALUES (?, ?, ?)
        """,
        ("org-1", "driver-1", "driver"),
    )
    connection.execute(
        "INSERT INTO customers (id, organization_id, name) VALUES (?, ?, ?)",
        ("customer-1", "org-1", "Customer One"),
    )
    connection.execute(
        "INSERT INTO varieties (id, organization_id, name) VALUES (?, ?, ?)",
        ("variety-1", "org-1", "Variety One"),
    )
    connection.execute(
        """
        INSERT INTO orders (
            id, organization_id, customer_id, variety_id,
            m2_area, pallet_size, remaining_balance
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        ("order-1", "org-1", "customer-1", "variety-1", 120, 60, 120),
    )
    connection.commit()
    return connection


def test_assignment_role_must_match_membership_role(tmp_path: Path) -> None:
    connection = seeded_assignment_database(tmp_path)

    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """
            INSERT INTO order_assignments (
                organization_id, order_id, user_id, assignment_role
            ) VALUES (?, ?, ?, ?)
            """,
            ("org-1", "order-1", "driver-1", "installer"),
        )


def test_cross_organization_order_assignment_is_rejected(tmp_path: Path) -> None:
    connection = seeded_assignment_database(tmp_path)
    connection.execute(
        "INSERT INTO organizations (id, name, slug) VALUES (?, ?, ?)",
        ("org-2", "Farm Two", "farm-two"),
    )
    connection.execute(
        "INSERT INTO customers (id, organization_id, name) VALUES (?, ?, ?)",
        ("customer-2", "org-2", "Customer Two"),
    )
    connection.execute(
        "INSERT INTO varieties (id, organization_id, name) VALUES (?, ?, ?)",
        ("variety-2", "org-2", "Variety Two"),
    )
    connection.execute(
        """
        INSERT INTO orders (
            id, organization_id, customer_id, variety_id,
            m2_area, pallet_size, remaining_balance
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        ("order-2", "org-2", "customer-2", "variety-2", 80, 40, 80),
    )
    connection.commit()

    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """
            INSERT INTO order_assignments (
                organization_id, order_id, user_id, assignment_role
            ) VALUES (?, ?, ?, ?)
            """,
            ("org-1", "order-2", "driver-1", "driver"),
        )


def test_assignment_history_cannot_be_deleted(tmp_path: Path) -> None:
    connection = seeded_assignment_database(tmp_path)
    connection.execute(
        """
        INSERT INTO order_assignments (
            organization_id, order_id, user_id, assignment_role
        ) VALUES (?, ?, ?, ?)
        """,
        ("org-1", "order-1", "driver-1", "driver"),
    )
    connection.commit()

    with pytest.raises(sqlite3.IntegrityError, match="must be removed"):
        connection.execute(
            """
            DELETE FROM order_assignments
            WHERE organization_id = ? AND order_id = ? AND user_id = ?
            """,
            ("org-1", "order-1", "driver-1"),
        )
