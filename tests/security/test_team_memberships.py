import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from turfhelm.db.connection import connect_sqlite
from turfhelm.db.migrations import apply_migrations
from turfhelm.repositories.orders import OrderRepository
from turfhelm.security.authentication import AuthenticatedPrincipal
from turfhelm.security.authority import SecurityContextAuthority

AUTHORITY = SecurityContextAuthority(signing_key=b"team-test-key-" + (b"x" * 32))


def seeded_team_order(tmp_path: Path, *, role: str = "installer"):
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
        ("worker-1", "auth0|worker-1", "worker@example.com", "Worker One"),
    )
    connection.execute(
        """
        INSERT INTO organization_memberships (organization_id, user_id, role)
        VALUES (?, ?, ?)
        """,
        ("org-1", "worker-1", role),
    )
    connection.execute(
        "INSERT INTO teams (id, organization_id, name) VALUES (?, ?, ?)",
        ("team-1", "org-1", "Install Team One"),
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
            id, organization_id, customer_id, team_id, variety_id,
            m2_area, pallet_size, remaining_balance
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "order-1",
            "org-1",
            "customer-1",
            "team-1",
            "variety-1",
            120,
            60,
            120,
        ),
    )
    connection.commit()
    principal = AuthenticatedPrincipal(
        oidc_subject="auth0|worker-1",
        expires_at=datetime.max.replace(tzinfo=UTC),
    )
    context = AUTHORITY.resolve(
        connection,
        principal=principal,
        organization_id="org-1",
    )
    return connection, context


@pytest.mark.parametrize("role", ["installer", "site_supervisor"])
def test_active_team_membership_grants_order_read(tmp_path: Path, role: str) -> None:
    connection, context = seeded_team_order(tmp_path, role=role)
    repository = OrderRepository(connection, AUTHORITY)
    assert repository.get_by_id(context, "order-1") is None

    connection.execute(
        """
        INSERT INTO team_memberships (
            organization_id, team_id, user_id, membership_role
        ) VALUES (?, ?, ?, ?)
        """,
        ("org-1", "team-1", "worker-1", role),
    )
    connection.commit()

    assert repository.get_by_id(context, "order-1") is not None


def test_membership_on_different_team_does_not_grant_order_read(tmp_path: Path) -> None:
    connection, context = seeded_team_order(tmp_path)
    connection.execute(
        "INSERT INTO teams (id, organization_id, name) VALUES (?, ?, ?)",
        ("team-2", "org-1", "Install Team Two"),
    )
    connection.execute(
        """
        INSERT INTO team_memberships (
            organization_id, team_id, user_id, membership_role
        ) VALUES (?, ?, ?, ?)
        """,
        ("org-1", "team-2", "worker-1", "installer"),
    )
    connection.commit()

    assert OrderRepository(connection, AUTHORITY).get_by_id(context, "order-1") is None


def test_removed_team_membership_revokes_order_read(tmp_path: Path) -> None:
    connection, context = seeded_team_order(tmp_path)
    connection.execute(
        """
        INSERT INTO team_memberships (
            organization_id, team_id, user_id, membership_role,
            status, removed_at
        ) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """,
        ("org-1", "team-1", "worker-1", "installer", "removed"),
    )
    connection.commit()

    assert OrderRepository(connection, AUTHORITY).get_by_id(context, "order-1") is None


def test_driver_cannot_be_added_as_install_team_member(tmp_path: Path) -> None:
    connection, _context = seeded_team_order(tmp_path, role="driver")

    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """
            INSERT INTO team_memberships (
                organization_id, team_id, user_id, membership_role
            ) VALUES (?, ?, ?, ?)
            """,
            ("org-1", "team-1", "worker-1", "driver"),
        )


def test_team_membership_role_must_match_real_membership_role(tmp_path: Path) -> None:
    connection, _context = seeded_team_order(tmp_path, role="installer")

    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """
            INSERT INTO team_memberships (
                organization_id, team_id, user_id, membership_role
            ) VALUES (?, ?, ?, ?)
            """,
            ("org-1", "team-1", "worker-1", "site_supervisor"),
        )


def test_cross_organization_team_membership_is_rejected(tmp_path: Path) -> None:
    connection, _context = seeded_team_order(tmp_path)
    connection.execute(
        "INSERT INTO organizations (id, name, slug) VALUES (?, ?, ?)",
        ("org-2", "Farm Two", "farm-two"),
    )
    connection.execute(
        "INSERT INTO teams (id, organization_id, name) VALUES (?, ?, ?)",
        ("team-2", "org-2", "Install Team Two"),
    )
    connection.commit()

    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """
            INSERT INTO team_memberships (
                organization_id, team_id, user_id, membership_role
            ) VALUES (?, ?, ?, ?)
            """,
            ("org-1", "team-2", "worker-1", "installer"),
        )


def test_team_membership_history_cannot_be_deleted(tmp_path: Path) -> None:
    connection, _context = seeded_team_order(tmp_path)
    connection.execute(
        """
        INSERT INTO team_memberships (
            organization_id, team_id, user_id, membership_role
        ) VALUES (?, ?, ?, ?)
        """,
        ("org-1", "team-1", "worker-1", "installer"),
    )
    connection.commit()

    with pytest.raises(sqlite3.IntegrityError, match="must be removed"):
        connection.execute(
            """
            DELETE FROM team_memberships
            WHERE organization_id = ? AND team_id = ? AND user_id = ?
            """,
            ("org-1", "team-1", "worker-1"),
        )
