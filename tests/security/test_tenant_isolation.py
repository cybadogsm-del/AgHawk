from datetime import UTC, datetime
from pathlib import Path

import pytest

from turfhelm.db.connection import connect_sqlite
from turfhelm.db.migrations import apply_migrations
from turfhelm.repositories.orders import OrderConflict, OrderRepository
from turfhelm.security.authentication import AuthenticatedPrincipal
from turfhelm.security.authority import SecurityContextAuthority
from turfhelm.security.context import Role

TEST_AUTHORITY = SecurityContextAuthority(signing_key=b"test-key-" * 4)


def principal(subject: str) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        oidc_subject=subject,
        expires_at=datetime.max.replace(tzinfo=UTC),
    )


def seed_identity(
    connection,
    *,
    user_id: str,
    organization_id: str,
    role: Role,
) -> str:
    oidc_subject = f"provider|{user_id}"
    connection.execute(
        """
        INSERT INTO users (id, oidc_subject, email, display_name)
        VALUES (?, ?, ?, ?)
        """,
        (user_id, oidc_subject, f"{user_id}@example.com", user_id),
    )
    connection.execute(
        """
        INSERT INTO organization_memberships (organization_id, user_id, role)
        VALUES (?, ?, ?)
        """,
        (organization_id, user_id, role.value),
    )
    connection.commit()
    return oidc_subject


def seed_order(connection, *, organization_id: str, order_id: str) -> None:
    connection.execute(
        "INSERT INTO organizations (id, name, slug) VALUES (?, ?, ?)",
        (organization_id, organization_id, organization_id),
    )
    connection.execute(
        """
        INSERT INTO customers (id, organization_id, name)
        VALUES (?, ?, ?)
        """,
        (f"customer-{organization_id}", organization_id, "Test Customer"),
    )
    connection.execute(
        """
        INSERT INTO varieties (id, organization_id, name)
        VALUES (?, ?, ?)
        """,
        (f"variety-{organization_id}", organization_id, "Test Variety"),
    )
    connection.execute(
        """
        INSERT INTO orders (
            id,
            organization_id,
            customer_id,
            variety_id,
            m2_area,
            pallet_size,
            remaining_balance
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            order_id,
            organization_id,
            f"customer-{organization_id}",
            f"variety-{organization_id}",
            120,
            60,
            120,
        ),
    )
    connection.commit()


def test_order_read_cannot_cross_organization_wall(tmp_path: Path) -> None:
    connection = connect_sqlite(tmp_path / "test.db")
    apply_migrations(connection)
    seed_order(connection, organization_id="org-a", order_id="order-a")
    seed_order(connection, organization_id="org-b", order_id="order-b")
    repository = OrderRepository(connection, TEST_AUTHORITY)
    oidc_subject = seed_identity(
        connection,
        user_id="user-a",
        organization_id="org-a",
        role=Role.ADMIN,
    )
    org_a = TEST_AUTHORITY.resolve(
        connection,
        principal=principal(oidc_subject),
        organization_id="org-a",
    )

    own_order = repository.get_by_id(org_a, "order-a")
    other_organization_order = repository.get_by_id(org_a, "order-b")

    assert own_order is not None
    assert own_order.organization_id == "org-a"
    assert other_organization_order is None


def test_order_update_cannot_cross_organization_wall(tmp_path: Path) -> None:
    connection = connect_sqlite(tmp_path / "test.db")
    apply_migrations(connection)
    seed_order(connection, organization_id="org-a", order_id="order-a")
    seed_order(connection, organization_id="org-b", order_id="order-b")
    repository = OrderRepository(connection, TEST_AUTHORITY)
    oidc_subject = seed_identity(
        connection,
        user_id="user-a",
        organization_id="org-a",
        role=Role.ADMIN,
    )
    org_a = TEST_AUTHORITY.resolve(
        connection,
        principal=principal(oidc_subject),
        organization_id="org-a",
    )

    with pytest.raises(OrderConflict, match="status update conflict"):
        repository.update_status(
            org_a,
            "order-b",
            "cancelled",
            expected_version=1,
            correlation_id="cross-org-cancel",
        )
    actual_status = connection.execute(
        "SELECT status FROM orders WHERE id = ?",
        ("order-b",),
    ).fetchone()[0]

    assert actual_status == "pending"
