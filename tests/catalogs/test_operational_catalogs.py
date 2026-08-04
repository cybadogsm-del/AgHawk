from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from turfhelm.catalogs.repository import (
    CatalogConflict,
    CatalogKind,
    CatalogNotFound,
    CatalogRepository,
    TransactionOwnershipError,
)
from turfhelm.catalogs.service import CatalogService
from turfhelm.db.connection import connect_sqlite
from turfhelm.db.migrations import apply_migrations
from turfhelm.security.authentication import AuthenticatedPrincipal
from turfhelm.security.authority import SecurityContextAuthority
from turfhelm.security.permissions import PermissionDenied

AUTHORITY = SecurityContextAuthority(signing_key=b"catalog-test-signing-key-" + b"x" * 32)


def principal(subject: str) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        oidc_subject=subject,
        expires_at=datetime.max.replace(tzinfo=UTC),
    )


def seed(connection: sqlite3.Connection) -> dict[str, object]:
    connection.executemany(
        "INSERT INTO organizations (id, name, slug) VALUES (?, ?, ?)",
        [("org-a", "Farm A", "farm-a"), ("org-b", "Farm B", "farm-b")],
    )
    users = [
        ("admin-a", "oidc|admin-a", "Admin A", "org-a", "admin"),
        ("staff-a", "oidc|staff-a", "Staff A", "org-a", "farm_staff"),
        ("admin-b", "oidc|admin-b", "Admin B", "org-b", "admin"),
    ]
    for user_id, subject, name, organization_id, role in users:
        connection.execute(
            "INSERT INTO users (id, oidc_subject, display_name) VALUES (?, ?, ?)",
            (user_id, subject, name),
        )
        connection.execute(
            """
            INSERT INTO organization_memberships (organization_id, user_id, role)
            VALUES (?, ?, ?)
            """,
            (organization_id, user_id, role),
        )
    connection.commit()
    return {
        "admin_a": AUTHORITY.resolve(
            connection, principal=principal("oidc|admin-a"), organization_id="org-a"
        ),
        "staff_a": AUTHORITY.resolve(
            connection, principal=principal("oidc|staff-a"), organization_id="org-a"
        ),
        "admin_b": AUTHORITY.resolve(
            connection, principal=principal("oidc|admin-b"), organization_id="org-b"
        ),
    }


def setup(tmp_path: Path) -> tuple[sqlite3.Connection, CatalogService, dict[str, object]]:
    connection = connect_sqlite(tmp_path / "test.db")
    apply_migrations(connection)
    contexts = seed(connection)
    return connection, CatalogService(CatalogRepository(connection, AUTHORITY)), contexts


def test_empty_organization_has_no_implicit_catalog_defaults(tmp_path: Path) -> None:
    _, service, contexts = setup(tmp_path)

    assert service.list_varieties(contexts["staff_a"]) == []
    assert service.list_pallet_sizes(contexts["staff_a"]) == []
    assert service.list_transport_options(contexts["staff_a"]) == []
    assert service.list_teams(contexts["staff_a"]) == []
    assert service.list_service_types(contexts["staff_a"]) == []


def test_admin_creates_normalized_uuid_catalog_values_with_atomic_audits(tmp_path: Path) -> None:
    connection, service, contexts = setup(tmp_path)
    context = contexts["admin_a"]

    variety = service.create_variety(context, "  Winter   Green  ", correlation_id="variety")
    pallet = service.create_pallet_size(context, 60, correlation_id="pallet")
    transport = service.create_transport_option(
        context, "  Truck   One ", pallet_capacity=30, correlation_id="transport"
    )
    team = service.create_team(context, " Install   North ", correlation_id="team")
    service_type = service.create_service_type(
        context, " Supply   and Lay ", correlation_id="service-type"
    )

    assert variety.name == "Winter Green"
    assert pallet.size == 60
    assert transport.name == "Truck One"
    assert transport.pallet_capacity == 30
    assert team.name == "Install North"
    assert service_type.name == "Supply and Lay"
    for item in (variety, pallet, transport, team, service_type):
        assert uuid.UUID(item.id).version == 4
        assert item.organization_id == "org-a"
        assert item.status == "active"

    actions = {
        row["action"]
        for row in connection.execute(
            "SELECT action FROM audit_events WHERE organization_id = ?", ("org-a",)
        )
    }
    assert actions == {
        "catalog.variety.created",
        "catalog.pallet_size.created",
        "catalog.transport_option.created",
        "catalog.team.created",
        "catalog.service_type.created",
    }


def test_identical_names_are_allowed_in_different_organizations_but_not_same_org(
    tmp_path: Path,
) -> None:
    _, service, contexts = setup(tmp_path)

    first = service.create_variety(contexts["admin_a"], "Kikuyu", correlation_id="a")
    second = service.create_variety(contexts["admin_b"], "Kikuyu", correlation_id="b")

    assert first.organization_id == "org-a"
    assert second.organization_id == "org-b"
    with pytest.raises(CatalogConflict, match="already exists"):
        service.create_variety(contexts["admin_a"], "  kikuyu ", correlation_id="duplicate")


def test_repository_rejects_unexpected_dynamic_catalog_columns(tmp_path: Path) -> None:
    connection = connect_sqlite(tmp_path / "test.db")
    apply_migrations(connection)
    contexts = seed(connection)
    repository = CatalogRepository(connection, AUTHORITY)

    with pytest.raises(ValueError, match="catalog fields"):
        repository.create(
            contexts["admin_a"],
            CatalogKind.VARIETY,
            {"name) VALUES ('forged', 'org-a', 'forged'); --": "payload"},
            correlation_id="malicious-column",
        )

    assert connection.execute("SELECT COUNT(*) FROM varieties").fetchone()[0] == 0


@pytest.mark.parametrize("name", [" unnormalized ", "", "x" * 101])
def test_repository_rejects_names_that_bypass_service_validation(
    tmp_path: Path, name: str
) -> None:
    connection = connect_sqlite(tmp_path / "test.db")
    apply_migrations(connection)
    contexts = seed(connection)
    repository = CatalogRepository(connection, AUTHORITY)

    with pytest.raises(ValueError, match="normalized name"):
        repository.create(
            contexts["admin_a"],
            CatalogKind.VARIETY,
            {"name": name},
            correlation_id="direct-invalid",
        )


def test_catalog_lists_are_tenant_scoped_sorted_and_omit_archived_values(tmp_path: Path) -> None:
    _, service, contexts = setup(tmp_path)
    beta = service.create_team(contexts["admin_a"], "Beta", correlation_id="beta")
    service.create_team(contexts["admin_a"], "Alpha", correlation_id="alpha")
    service.create_team(contexts["admin_b"], "Other Farm", correlation_id="other")

    archived = service.archive_team(contexts["admin_a"], beta.id, correlation_id="archive")

    assert archived.status == "archived"
    assert [item.name for item in service.list_teams(contexts["staff_a"])] == ["Alpha"]
    assert [item.name for item in service.list_teams(contexts["admin_b"])] == ["Other Farm"]


def test_cross_organization_ids_are_denied_without_disclosure(tmp_path: Path) -> None:
    _, service, contexts = setup(tmp_path)
    other = service.create_service_type(
        contexts["admin_b"], "Installation", correlation_id="create-b"
    )

    with pytest.raises(CatalogNotFound, match="not found"):
        service.archive_service_type(
            contexts["admin_a"], other.id, correlation_id="cross-organization"
        )

    assert [item.id for item in service.list_service_types(contexts["admin_b"])] == [other.id]


@pytest.mark.parametrize(
    ("create", "archive"),
    [
        (
            lambda service, context: service.create_variety(
                context, "Variety", correlation_id="denied"
            ),
            lambda service, context: service.archive_variety(
                context, "missing", correlation_id="denied"
            ),
        ),
        (
            lambda service, context: service.create_pallet_size(
                context, 60, correlation_id="denied"
            ),
            lambda service, context: service.archive_pallet_size(
                context, "missing", correlation_id="denied"
            ),
        ),
        (
            lambda service, context: service.create_transport_option(
                context, "Truck", pallet_capacity=1, correlation_id="denied"
            ),
            lambda service, context: service.archive_transport_option(
                context, "missing", correlation_id="denied"
            ),
        ),
        (
            lambda service, context: service.create_team(
                context, "Team", correlation_id="denied"
            ),
            lambda service, context: service.archive_team(
                context, "missing", correlation_id="denied"
            ),
        ),
        (
            lambda service, context: service.create_service_type(
                context, "Supply", correlation_id="denied"
            ),
            lambda service, context: service.archive_service_type(
                context, "missing", correlation_id="denied"
            ),
        ),
    ],
)
def test_non_admin_cannot_create_or_archive_catalogs(tmp_path: Path, create, archive) -> None:
    connection, service, contexts = setup(tmp_path)

    with pytest.raises(PermissionDenied):
        create(service, contexts["staff_a"])
    with pytest.raises(PermissionDenied):
        archive(service, contexts["staff_a"])

    assert connection.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0] == 0


def test_disabled_context_cannot_list_or_write(tmp_path: Path) -> None:
    connection, service, contexts = setup(tmp_path)
    connection.execute(
        """
        UPDATE organization_memberships SET status = 'disabled'
        WHERE organization_id = 'org-a' AND user_id = 'admin-a'
        """
    )
    connection.commit()

    with pytest.raises(PermissionError, match="no longer active"):
        service.list_varieties(contexts["admin_a"])
    with pytest.raises(PermissionError, match="no longer active"):
        service.create_team(contexts["admin_a"], "Team", correlation_id="disabled")


def test_archive_is_stale_safe_and_writes_audit(tmp_path: Path) -> None:
    connection, service, contexts = setup(tmp_path)
    created = service.create_transport_option(
        contexts["admin_a"], "Truck", pallet_capacity=20, correlation_id="create"
    )

    archived = service.archive_transport_option(
        contexts["admin_a"], created.id, correlation_id="archive"
    )

    assert archived.status == "archived"
    event = connection.execute(
        "SELECT * FROM audit_events WHERE action = 'catalog.transport_option.archived'"
    ).fetchone()
    assert event["object_id"] == created.id
    assert event["actor_user_id"] == "admin-a"
    assert event["correlation_id"] == "archive"
    with pytest.raises(CatalogConflict, match="already archived"):
        service.archive_transport_option(
            contexts["admin_a"], created.id, correlation_id="stale"
        )


def test_audit_failure_rolls_back_create_and_archive(tmp_path: Path) -> None:
    connection, service, contexts = setup(tmp_path)
    team = service.create_team(contexts["admin_a"], "North", correlation_id="first")
    connection.execute(
        """
        CREATE TRIGGER reject_catalog_audit
        BEFORE INSERT ON audit_events
        WHEN NEW.action LIKE 'catalog.%'
        BEGIN
            SELECT RAISE(ABORT, 'forced audit failure');
        END
        """
    )
    connection.commit()

    with pytest.raises(sqlite3.IntegrityError, match="forced audit failure"):
        service.create_team(contexts["admin_a"], "South", correlation_id="create-fails")
    with pytest.raises(sqlite3.IntegrityError, match="forced audit failure"):
        service.archive_team(contexts["admin_a"], team.id, correlation_id="archive-fails")

    assert [item.name for item in service.list_teams(contexts["admin_a"])] == ["North"]
    status = connection.execute(
        "SELECT status FROM teams WHERE id = ?", (team.id,)
    ).fetchone()[0]
    assert status == "active"


def test_write_rechecks_active_context_inside_owned_transaction(tmp_path: Path) -> None:
    connection = connect_sqlite(tmp_path / "test.db")
    apply_migrations(connection)
    contexts = seed(connection)

    class RevokeAfterLock:
        def __init__(self) -> None:
            self.calls = 0

        def require_active(self, active_connection, context) -> None:
            self.calls += 1
            if self.calls == 2:
                active_connection.execute(
                    """
                    UPDATE organization_memberships SET status = 'disabled'
                    WHERE organization_id = ? AND user_id = ?
                    """,
                    (context.organization_id, context.user_id),
                )
            AUTHORITY.require_active(active_connection, context)

    service = CatalogService(CatalogRepository(connection, RevokeAfterLock()))

    with pytest.raises(PermissionError, match="no longer active"):
        service.create_variety(contexts["admin_a"], "Race", correlation_id="race")

    assert connection.execute("SELECT COUNT(*) FROM varieties").fetchone()[0] == 0
    assert connection.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0] == 0


def test_write_rejects_ambient_transaction_without_rolling_it_back(tmp_path: Path) -> None:
    connection, service, contexts = setup(tmp_path)
    connection.execute(
        "INSERT INTO system_config (organization_id, key, value) VALUES (?, ?, ?)",
        ("org-a", "pending-setting", "keep-me"),
    )

    with pytest.raises(TransactionOwnershipError, match="active transaction"):
        service.create_service_type(
            contexts["admin_a"], "Supply", correlation_id="ambient"
        )

    assert connection.in_transaction is True
    assert connection.execute(
        "SELECT value FROM system_config WHERE organization_id = ? AND key = ?",
        ("org-a", "pending-setting"),
    ).fetchone()[0] == "keep-me"


@pytest.mark.parametrize("bad_name", ["", "   ", "x" * 101])
def test_names_are_required_and_length_limited(tmp_path: Path, bad_name: str) -> None:
    _, service, contexts = setup(tmp_path)

    with pytest.raises(ValueError, match="name"):
        service.create_variety(contexts["admin_a"], bad_name, correlation_id="invalid")


@pytest.mark.parametrize("bad_size", [True, 0, -1, 1.5, "60"])
def test_pallet_size_must_be_a_positive_integer(tmp_path: Path, bad_size: object) -> None:
    _, service, contexts = setup(tmp_path)

    with pytest.raises(ValueError, match="pallet size"):
        service.create_pallet_size(contexts["admin_a"], bad_size, correlation_id="invalid")


@pytest.mark.parametrize("bad_capacity", [True, -1, 1.5, "30"])
def test_transport_capacity_must_be_a_non_negative_integer(
    tmp_path: Path, bad_capacity: object
) -> None:
    _, service, contexts = setup(tmp_path)

    with pytest.raises(ValueError, match="pallet capacity"):
        service.create_transport_option(
            contexts["admin_a"], "Truck", pallet_capacity=bad_capacity, correlation_id="invalid"
        )
