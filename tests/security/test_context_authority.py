from datetime import UTC, datetime
from pathlib import Path

import pytest

from turfhelm.db.connection import connect_sqlite
from turfhelm.db.migrations import apply_migrations
from turfhelm.repositories.orders import OrderRepository
from turfhelm.security.authentication import AuthenticatedPrincipal
from turfhelm.security.authority import SecurityContextAuthority
from turfhelm.security.context import Role, SecurityContext

TEST_KEY = b"authority-test-key-" + (b"x" * 32)
OTHER_KEY = b"different-test-key-" + (b"y" * 32)
ADMIN_PRINCIPAL = AuthenticatedPrincipal(
    oidc_subject="auth0|admin-1",
    expires_at=datetime.max.replace(tzinfo=UTC),
)


def seeded_connection(tmp_path: Path):
    connection = connect_sqlite(tmp_path / "test.db")
    apply_migrations(connection)
    connection.execute(
        "INSERT INTO organizations (id, name, slug) VALUES (?, ?, ?)",
        ("victim-org", "Victim Farm", "victim-farm"),
    )
    connection.execute(
        """
        INSERT INTO users (id, oidc_subject, email, display_name)
        VALUES (?, ?, ?, ?)
        """,
        ("admin-1", "auth0|admin-1", "admin@example.com", "Admin One"),
    )
    connection.execute(
        """
        INSERT INTO organization_memberships (organization_id, user_id, role)
        VALUES (?, ?, ?)
        """,
        ("victim-org", "admin-1", "admin"),
    )
    connection.commit()
    return connection


def test_forged_active_administrator_context_fails_proof_check(tmp_path: Path) -> None:
    connection = seeded_connection(tmp_path)
    authority = SecurityContextAuthority(signing_key=TEST_KEY)
    forged = SecurityContext._from_active_membership(
        user_id="admin-1",
        oidc_subject="auth0|admin-1",
        organization_id="victim-org",
        role=Role.ADMIN,
        proof=b"forged-proof",
    )

    with pytest.raises(PermissionError, match="proof is invalid"):
        OrderRepository(connection, authority).get_by_id(forged, "order-1")


def test_context_from_different_authority_key_is_rejected(tmp_path: Path) -> None:
    connection = seeded_connection(tmp_path)
    trusted_authority = SecurityContextAuthority(signing_key=TEST_KEY)
    other_authority = SecurityContextAuthority(signing_key=OTHER_KEY)
    foreign_context = other_authority.resolve(
        connection,
        principal=ADMIN_PRINCIPAL,
        organization_id="victim-org",
    )

    with pytest.raises(PermissionError, match="proof is invalid"):
        OrderRepository(connection, trusted_authority).get_by_id(foreign_context, "order-1")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("user_id", "attacker"),
        ("oidc_subject", "auth0|attacker"),
        ("organization_id", "attacker-org"),
        ("role", Role.DRIVER),
    ],
)
def test_changing_any_protected_field_invalidates_proof(
    tmp_path: Path,
    field: str,
    value: str | Role,
) -> None:
    connection = seeded_connection(tmp_path)
    authority = SecurityContextAuthority(signing_key=TEST_KEY)
    genuine = authority.resolve(
        connection,
        principal=ADMIN_PRINCIPAL,
        organization_id="victim-org",
    )
    fields = {
        "user_id": genuine.user_id,
        "oidc_subject": genuine.oidc_subject,
        "organization_id": genuine.organization_id,
        "role": genuine.role,
    }
    fields[field] = value
    tampered = SecurityContext._from_active_membership(
        **fields,
        proof=genuine.proof,
    )

    with pytest.raises(PermissionError, match="proof is invalid"):
        OrderRepository(connection, authority).get_by_id(tampered, "order-1")


def test_context_and_errors_do_not_display_key_or_proof(tmp_path: Path) -> None:
    connection = seeded_connection(tmp_path)
    authority = SecurityContextAuthority(signing_key=TEST_KEY)
    genuine = authority.resolve(
        connection,
        principal=ADMIN_PRINCIPAL,
        organization_id="victim-org",
    )
    forged = SecurityContext._from_active_membership(
        user_id=genuine.user_id,
        oidc_subject=genuine.oidc_subject,
        organization_id=genuine.organization_id,
        role=genuine.role,
        proof=b"forged-proof",
    )

    assert "proof=" not in repr(genuine)
    assert TEST_KEY.hex() not in repr(authority)
    with pytest.raises(PermissionError) as error:
        OrderRepository(connection, authority).get_by_id(forged, "order-1")
    assert TEST_KEY.hex() not in str(error.value)
    assert genuine.proof.hex() not in str(error.value)


@pytest.mark.parametrize("length", [0, 1, 16, 31])
def test_weak_signing_keys_are_rejected(length: int) -> None:
    with pytest.raises(ValueError, match="at least 32 bytes"):
        SecurityContextAuthority(signing_key=b"x" * length)
