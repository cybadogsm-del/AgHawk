from datetime import UTC, datetime
from pathlib import Path

import pytest

from turfhelm.db.connection import connect_sqlite
from turfhelm.db.migrations import apply_migrations
from turfhelm.repositories.orders import OrderRepository
from turfhelm.security.authentication import AuthenticatedPrincipal
from turfhelm.security.authority import SecurityContextAuthority
from turfhelm.security.context import Role, SecurityContext

TEST_AUTHORITY = SecurityContextAuthority(signing_key=b"test-key-" * 4)


def principal(subject: str) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        oidc_subject=subject,
        expires_at=datetime.max.replace(tzinfo=UTC),
    )


def seed_identity(
    connection,
    *,
    user_id: str = "user-1",
    oidc_subject: str = "provider|subject-1",
    organization_id: str = "org-1",
    role: str = "driver",
    user_status: str = "active",
    membership_status: str = "active",
) -> None:
    connection.execute(
        "INSERT INTO organizations (id, name, slug) VALUES (?, ?, ?)",
        (organization_id, "Test Farm", organization_id),
    )
    connection.execute(
        """
        INSERT INTO users (id, oidc_subject, email, display_name, status)
        VALUES (?, ?, ?, ?, ?)
        """,
        (user_id, oidc_subject, "worker@example.com", "Test Worker", user_status),
    )
    connection.execute(
        """
        INSERT INTO organization_memberships (
            organization_id, user_id, role, status
        ) VALUES (?, ?, ?, ?)
        """,
        (organization_id, user_id, role, membership_status),
    )
    connection.commit()


def test_resolver_loads_role_from_active_database_membership(tmp_path: Path) -> None:
    connection = connect_sqlite(tmp_path / "test.db")
    apply_migrations(connection)
    seed_identity(connection, role="driver")

    context = TEST_AUTHORITY.resolve(
        connection,
        principal=principal("provider|subject-1"),
        organization_id="org-1",
    )

    assert context.user_id == "user-1"
    assert context.organization_id == "org-1"
    assert context.role is Role.DRIVER


@pytest.mark.parametrize(
    ("user_status", "membership_status"),
    [("disabled", "active"), ("active", "disabled")],
)
def test_resolver_rejects_disabled_identity_or_membership(
    tmp_path: Path,
    user_status: str,
    membership_status: str,
) -> None:
    connection = connect_sqlite(tmp_path / "test.db")
    apply_migrations(connection)
    seed_identity(
        connection,
        user_status=user_status,
        membership_status=membership_status,
    )

    with pytest.raises(PermissionError, match="active organization membership"):
        TEST_AUTHORITY.resolve(
            connection,
            principal=principal("provider|subject-1"),
            organization_id="org-1",
        )


def test_resolver_rejects_unknown_subject(tmp_path: Path) -> None:
    connection = connect_sqlite(tmp_path / "test.db")
    apply_migrations(connection)
    seed_identity(connection)

    with pytest.raises(PermissionError, match="active organization membership"):
        TEST_AUTHORITY.resolve(
            connection,
            principal=principal("provider|attacker"),
            organization_id="org-1",
        )


def test_repository_rejects_context_after_membership_is_disabled(tmp_path: Path) -> None:
    connection = connect_sqlite(tmp_path / "test.db")
    apply_migrations(connection)
    seed_identity(connection, role="admin")
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
    context = TEST_AUTHORITY.resolve(
        connection,
        principal=principal("provider|subject-1"),
        organization_id="org-1",
    )
    connection.execute(
        """
        UPDATE organization_memberships
        SET status = 'disabled'
        WHERE organization_id = ? AND user_id = ?
        """,
        ("org-1", "user-1"),
    )
    connection.commit()

    with pytest.raises(PermissionError, match="no longer active"):
        OrderRepository(connection, TEST_AUTHORITY).get_by_id(context, "order-1")


def test_repository_rejects_forged_context_without_matching_membership(
    tmp_path: Path,
) -> None:
    connection = connect_sqlite(tmp_path / "test.db")
    apply_migrations(connection)
    seed_identity(connection, role="driver")
    forged_context = SecurityContext._from_active_membership(
        user_id="user-1",
        oidc_subject="provider|subject-1",
        organization_id="org-1",
        role=Role.ADMIN,
        proof=b"forged-proof",
    )

    with pytest.raises(PermissionError, match="proof is invalid"):
        OrderRepository(connection, TEST_AUTHORITY).get_by_id(forged_context, "order-1")
