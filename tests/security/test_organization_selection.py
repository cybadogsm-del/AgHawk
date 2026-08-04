from datetime import UTC, datetime
from pathlib import Path

import pytest

from turfhelm.db.connection import connect_sqlite
from turfhelm.db.migrations import apply_migrations
from turfhelm.security.authentication import AuthenticatedPrincipal
from turfhelm.security.authority import SecurityContextAuthority
from turfhelm.security.context import Role
from turfhelm.security.organization_selection import OrganizationSelectionService


def principal(subject: str = "provider|user-1") -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        oidc_subject=subject,
        expires_at=datetime.max.replace(tzinfo=UTC),
    )


def migrated_connection(tmp_path: Path):
    connection = connect_sqlite(tmp_path / "test.db")
    apply_migrations(connection)
    return connection


def seed_user(connection, *, status: str = "active") -> None:
    connection.execute(
        """
        INSERT INTO users (id, oidc_subject, display_name, status)
        VALUES (?, ?, ?, ?)
        """,
        ("user-1", "provider|user-1", "Test User", status),
    )


def seed_organization_membership(
    connection,
    *,
    organization_id: str,
    name: str,
    role: str,
    organization_status: str = "active",
    membership_status: str = "active",
) -> None:
    connection.execute(
        """
        INSERT INTO organizations (id, name, slug, status)
        VALUES (?, ?, ?, ?)
        """,
        (organization_id, name, organization_id, organization_status),
    )
    connection.execute(
        """
        INSERT INTO organization_memberships (organization_id, user_id, role, status)
        VALUES (?, ?, ?, ?)
        """,
        (organization_id, "user-1", role, membership_status),
    )


def test_lists_persisted_active_organization_membership(tmp_path: Path) -> None:
    connection = migrated_connection(tmp_path)
    seed_user(connection)
    seed_organization_membership(
        connection,
        organization_id="org-immutable-id",
        name="Green Farm",
        role="driver",
    )
    connection.commit()

    choices = OrganizationSelectionService(connection).list_for(principal())

    assert len(choices) == 1
    assert choices[0].organization_id == "org-immutable-id"
    assert choices[0].display_name == "Green Farm"
    assert choices[0].role is Role.DRIVER


def test_lists_multiple_organizations_in_deterministic_name_and_id_order(
    tmp_path: Path,
) -> None:
    connection = migrated_connection(tmp_path)
    seed_user(connection)
    seed_organization_membership(
        connection,
        organization_id="org-z",
        name="Zulu Farm",
        role="installer",
    )
    seed_organization_membership(
        connection,
        organization_id="org-a-2",
        name="Alpha Farm",
        role="driver",
    )
    seed_organization_membership(
        connection,
        organization_id="org-a-1",
        name="Alpha Farm",
        role="admin",
    )
    connection.commit()

    choices = OrganizationSelectionService(connection).list_for(principal())

    assert [choice.organization_id for choice in choices] == ["org-a-1", "org-a-2", "org-z"]


def test_rejects_unlisted_organization_before_authority_resolution(tmp_path: Path) -> None:
    connection = migrated_connection(tmp_path)
    seed_user(connection)
    seed_organization_membership(
        connection,
        organization_id="org-allowed",
        name="Allowed Farm",
        role="driver",
    )
    connection.commit()

    class AuthorityMustNotBeCalled:
        def resolve(self, *args, **kwargs):
            raise AssertionError("authority.resolve must not receive an unlisted organization")

    with pytest.raises(PermissionError, match="organization selection is not available"):
        OrganizationSelectionService(connection).resolve_selected(
            principal(),
            selected_organization_id="org-from-editable-user-text",
            authority=AuthorityMustNotBeCalled(),
        )


@pytest.mark.parametrize(
    ("user_status", "membership_status", "organization_status"),
    [
        ("disabled", "active", "active"),
        ("active", "disabled", "active"),
        ("active", "active", "suspended"),
    ],
)
def test_inactive_identity_membership_or_organization_has_no_choices(
    tmp_path: Path,
    user_status: str,
    membership_status: str,
    organization_status: str,
) -> None:
    connection = migrated_connection(tmp_path)
    seed_user(connection, status=user_status)
    seed_organization_membership(
        connection,
        organization_id="org-hidden",
        name="Hidden Farm",
        role="admin",
        membership_status=membership_status,
        organization_status=organization_status,
    )
    connection.commit()

    assert OrganizationSelectionService(connection).list_for(principal()) == ()


def test_unknown_identity_has_no_choices(tmp_path: Path) -> None:
    connection = migrated_connection(tmp_path)
    seed_user(connection)
    seed_organization_membership(
        connection,
        organization_id="org-private",
        name="Private Farm",
        role="admin",
    )
    connection.commit()

    assert OrganizationSelectionService(connection).list_for(principal("provider|unknown")) == ()


def test_persisted_available_selection_resolves_sealed_context(tmp_path: Path) -> None:
    connection = migrated_connection(tmp_path)
    seed_user(connection)
    seed_organization_membership(
        connection,
        organization_id="org-allowed",
        name="Allowed Farm",
        role="farm_staff",
    )
    connection.commit()
    authority = SecurityContextAuthority(signing_key=b"organization-selection-key-123456")

    context = OrganizationSelectionService(connection).resolve_selected(
        principal(),
        selected_organization_id="org-allowed",
        authority=authority,
    )

    assert context.organization_id == "org-allowed"
    assert context.user_id == "user-1"
    assert context.role is Role.FARM_STAFF
    authority.require_active(connection, context)
