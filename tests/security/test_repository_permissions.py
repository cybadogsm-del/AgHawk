from datetime import UTC, datetime
from pathlib import Path

import pytest

from turfhelm.db.connection import connect_sqlite
from turfhelm.db.migrations import apply_migrations
from turfhelm.repositories.orders import OrderRepository
from turfhelm.security.authentication import AuthenticatedPrincipal
from turfhelm.security.authority import SecurityContextAuthority
from turfhelm.security.permissions import PermissionDenied

AUTHORITY = SecurityContextAuthority(signing_key=b"permission-test-key-" + (b"x" * 32))


def seed_order_and_user(connection, *, role: str) -> AuthenticatedPrincipal:
    connection.execute(
        "INSERT INTO organizations (id, name, slug) VALUES (?, ?, ?)",
        ("org-1", "Farm One", "farm-one"),
    )
    connection.execute(
        """
        INSERT INTO users (id, oidc_subject, email, display_name)
        VALUES (?, ?, ?, ?)
        """,
        ("user-1", "auth0|user-1", "worker@example.com", "Worker One"),
    )
    connection.execute(
        """
        INSERT INTO organization_memberships (organization_id, user_id, role)
        VALUES (?, ?, ?)
        """,
        ("org-1", "user-1", role),
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
    return AuthenticatedPrincipal(
        oidc_subject="auth0|user-1",
        expires_at=datetime.max.replace(tzinfo=UTC),
    )


@pytest.mark.parametrize("role", ["driver", "site_supervisor", "installer"])
def test_unassigned_scoped_worker_cannot_read_order(tmp_path: Path, role: str) -> None:
    connection = connect_sqlite(tmp_path / "test.db")
    apply_migrations(connection)
    principal = seed_order_and_user(connection, role=role)
    context = AUTHORITY.resolve(
        connection,
        principal=principal,
        organization_id="org-1",
    )

    assert OrderRepository(connection, AUTHORITY).get_by_id(context, "order-1") is None


@pytest.mark.parametrize("role", ["driver", "site_supervisor", "installer"])
def test_directly_assigned_worker_can_read_but_not_change_core_status(
    tmp_path: Path,
    role: str,
) -> None:
    connection = connect_sqlite(tmp_path / "test.db")
    apply_migrations(connection)
    principal = seed_order_and_user(connection, role=role)
    context = AUTHORITY.resolve(
        connection,
        principal=principal,
        organization_id="org-1",
    )
    repository = OrderRepository(connection, AUTHORITY)
    connection.execute(
        """
        INSERT INTO order_assignments (
            organization_id, order_id, user_id, assignment_role
        ) VALUES (?, ?, ?, ?)
        """,
        ("org-1", "order-1", "user-1", role),
    )
    connection.commit()

    assert repository.get_by_id(context, "order-1") is not None
    with pytest.raises(PermissionDenied):
        repository.update_status(
            context,
            "order-1",
            "cancelled",
            expected_version=1,
            correlation_id="worker-denied",
        )
    status = connection.execute(
        "SELECT status FROM orders WHERE id = ?",
        ("order-1",),
    ).fetchone()[0]
    assert status == "pending"


@pytest.mark.parametrize("role", ["driver", "site_supervisor", "installer"])
def test_removed_direct_assignment_revokes_order_read(
    tmp_path: Path,
    role: str,
) -> None:
    connection = connect_sqlite(tmp_path / "test.db")
    apply_migrations(connection)
    principal = seed_order_and_user(connection, role=role)
    context = AUTHORITY.resolve(
        connection,
        principal=principal,
        organization_id="org-1",
    )
    repository = OrderRepository(connection, AUTHORITY)
    connection.execute(
        """
        INSERT INTO order_assignments (
            organization_id, order_id, user_id, assignment_role
        ) VALUES (?, ?, ?, ?)
        """,
        ("org-1", "order-1", "user-1", role),
    )
    connection.commit()
    assert repository.get_by_id(context, "order-1") is not None

    connection.execute(
        """
        UPDATE order_assignments
        SET status = 'removed', removed_at = CURRENT_TIMESTAMP
        WHERE organization_id = ? AND order_id = ?
          AND user_id = ? AND assignment_role = ?
        """,
        ("org-1", "order-1", "user-1", role),
    )
    connection.commit()

    assert repository.get_by_id(context, "order-1") is None


def test_administrator_can_change_order_status(tmp_path: Path) -> None:
    connection = connect_sqlite(tmp_path / "test.db")
    apply_migrations(connection)
    principal = seed_order_and_user(connection, role="admin")
    context = AUTHORITY.resolve(
        connection,
        principal=principal,
        organization_id="org-1",
    )

    changed = OrderRepository(connection, AUTHORITY).update_status(
        context,
        "order-1",
        "cancelled",
        expected_version=1,
        correlation_id="admin-cancel",
    )

    assert changed is True
