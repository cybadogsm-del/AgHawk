from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from turfhelm.customers import (
    CustomerConflict,
    CustomerNotFound,
    CustomerRepository,
    CustomerService,
    TransactionOwnershipError,
)
from turfhelm.db.connection import connect_sqlite
from turfhelm.db.migrations import apply_migrations
from turfhelm.security.authentication import AuthenticatedPrincipal
from turfhelm.security.authority import SecurityContextAuthority
from turfhelm.security.context import SecurityContext
from turfhelm.security.permissions import PermissionDenied

AUTHORITY = SecurityContextAuthority(signing_key=b"customer-test-signing-key-" + b"x" * 32)


def _principal(subject: str) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        oidc_subject=subject,
        expires_at=datetime.max.replace(tzinfo=UTC),
    )


def _setup_contexts_on_connection(
    connection: sqlite3.Connection,
) -> dict[str, SecurityContext]:
    connection.executemany(
        "INSERT INTO organizations (id, name, slug) VALUES (?, ?, ?)",
        [("org-a", "Farm A", "farm-a"), ("org-b", "Farm B", "farm-b")],
    )
    principals = [
        ("admin-a", "oidc|admin-a", "Admin A", "org-a", "admin"),
        ("staff-a", "oidc|staff-a", "Staff A", "org-a", "farm_staff"),
        ("admin-b", "oidc|admin-b", "Admin B", "org-b", "admin"),
    ]
    for user_id, subject, name, organization_id, role in principals:
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
    contexts = {
        key: AUTHORITY.resolve(connection, principal=_principal(subject), organization_id=org)
        for key, subject, org in (
            ("admin_a", "oidc|admin-a", "org-a"),
            ("staff_a", "oidc|staff-a", "org-a"),
            ("admin_b", "oidc|admin-b", "org-b"),
        )
    }
    return contexts


def _setup(
    tmp_path: Path,
) -> tuple[sqlite3.Connection, CustomerService, dict[str, SecurityContext]]:
    connection = connect_sqlite(tmp_path / "test.db")
    apply_migrations(connection)
    contexts = _setup_contexts_on_connection(connection)
    service = CustomerService(CustomerRepository(connection, AUTHORITY))
    return connection, service, contexts


def test_empty_organization_has_no_customer_defaults(tmp_path: Path) -> None:
    _, service, contexts = _setup(tmp_path)

    assert service.list_customers(contexts["staff_a"]) == []


def test_admin_creates_normalized_relationships_and_members_list_active_records(
    tmp_path: Path,
) -> None:
    connection, service, contexts = _setup(tmp_path)
    customer = service.create_customer(
        contexts["admin_a"], "  Shared   Customer  ", correlation_id="customer"
    )
    site = service.create_site(
        contexts["admin_a"],
        customer.id,
        "  1   Main Street  ",
        correlation_id="site",
    )
    site_contact = service.create_contact(
        contexts["admin_a"],
        customer.id,
        "  Site   Person ",
        "  0400  111  222 ",
        site_id=site.id,
        correlation_id="site-contact",
    )
    general_contact = service.create_contact(
        contexts["admin_a"],
        customer.id,
        " Accounts  Person ",
        "+61  400 333 444",
        correlation_id="general-contact",
    )

    assert customer.name == "Shared Customer"
    assert site.address == "1 Main Street"
    assert site_contact.name == "Site Person"
    assert site_contact.phone == "0400 111 222"
    assert general_contact.site_id is None
    for record in (customer, site, site_contact, general_contact):
        assert uuid.UUID(record.id).version == 4
        assert record.organization_id == "org-a"
        assert record.status == "active"

    assert service.list_customers(contexts["staff_a"]) == [customer]
    assert service.list_sites(contexts["staff_a"], customer.id) == [site]
    assert service.list_contacts(contexts["staff_a"], customer.id) == [
        general_contact,
        site_contact,
    ]
    assert service.list_contacts(contexts["staff_a"], customer.id, site_id=site.id) == [
        site_contact
    ]
    assert {
        row["action"]
        for row in connection.execute(
            "SELECT action FROM audit_events WHERE organization_id = 'org-a'"
        )
    } == {
        "customer.created",
        "site.created",
        "contact.created",
    }


def test_relationship_reads_and_writes_hide_cross_org_and_wrong_parent_ids(tmp_path: Path) -> None:
    _, service, contexts = _setup(tmp_path)
    customer_a = service.create_customer(contexts["admin_a"], "A", correlation_id="a")
    customer_a2 = service.create_customer(contexts["admin_a"], "A2", correlation_id="a2")
    customer_b = service.create_customer(contexts["admin_b"], "B", correlation_id="b")
    site_a = service.create_site(
        contexts["admin_a"], customer_a.id, "1 A Street", correlation_id="site-a"
    )
    site_a2 = service.create_site(
        contexts["admin_a"], customer_a2.id, "2 A Street", correlation_id="site-a2"
    )
    site_b = service.create_site(
        contexts["admin_b"], customer_b.id, "1 B Street", correlation_id="site-b"
    )

    for hidden_customer in (customer_b.id, "guessed"):
        with pytest.raises(CustomerNotFound, match="customer not found"):
            service.list_sites(contexts["staff_a"], hidden_customer)
        with pytest.raises(CustomerNotFound, match="customer not found"):
            service.list_contacts(contexts["staff_a"], hidden_customer)
        with pytest.raises(CustomerNotFound, match="customer not found"):
            service.archive_customer(
                contexts["admin_a"], hidden_customer, correlation_id="hidden-archive"
            )
    for wrong_site in (site_a2.id, site_b.id, "guessed"):
        with pytest.raises(CustomerNotFound, match="site not found"):
            service.list_contacts(contexts["staff_a"], customer_a.id, site_id=wrong_site)
        with pytest.raises(CustomerNotFound, match="site not found"):
            service.create_contact(
                contexts["admin_a"],
                customer_a.id,
                "Wrong Link",
                "0400 000 000",
                site_id=wrong_site,
                correlation_id="wrong-link",
            )

    assert service.list_contacts(contexts["staff_a"], customer_a.id, site_id=site_a.id) == []


def test_only_admin_can_mutate_and_revocation_blocks_reads_and_writes(tmp_path: Path) -> None:
    connection, service, contexts = _setup(tmp_path)
    customer = service.create_customer(
        contexts["admin_a"], "Protected", correlation_id="protected"
    )
    with pytest.raises(PermissionDenied):
        service.create_customer(contexts["staff_a"], "Denied", correlation_id="denied")
    with pytest.raises(PermissionDenied):
        service.archive_customer(contexts["staff_a"], customer.id, correlation_id="denied")

    connection.execute(
        """
        UPDATE organization_memberships SET status = 'disabled'
        WHERE organization_id = 'org-a' AND user_id = 'admin-a'
        """
    )
    connection.commit()
    with pytest.raises(PermissionError, match="no longer active"):
        service.list_customers(contexts["admin_a"])
    with pytest.raises(PermissionError, match="no longer active"):
        service.create_customer(contexts["admin_a"], "Denied", correlation_id="revoked")


def test_archive_rejects_active_dependencies_then_retains_history_and_audits(
    tmp_path: Path,
) -> None:
    connection, service, contexts = _setup(tmp_path)
    context = contexts["admin_a"]
    customer = service.create_customer(context, "Customer", correlation_id="customer")
    site = service.create_site(context, customer.id, "1 Main", correlation_id="site")
    contact = service.create_contact(
        context,
        customer.id,
        "Person",
        "0400 000 000",
        site_id=site.id,
        correlation_id="contact",
    )

    with pytest.raises(CustomerConflict, match="active sites or contacts"):
        service.archive_customer(context, customer.id, correlation_id="blocked-customer")
    with pytest.raises(CustomerConflict, match="active contacts"):
        service.archive_site(context, customer.id, site.id, correlation_id="blocked-site")

    assert (
        service.archive_contact(
            context, customer.id, contact.id, correlation_id="archive-contact"
        ).status
        == "archived"
    )
    assert (
        service.archive_site(context, customer.id, site.id, correlation_id="archive-site").status
        == "archived"
    )
    assert service.archive_customer(
        context, customer.id, correlation_id="archive-customer"
    ).status == ("archived")
    assert service.list_customers(context) == []
    assert (
        connection.execute(
            "SELECT COUNT(*) FROM customers WHERE id = ?", (customer.id,)
        ).fetchone()[0]
        == 1
    )
    assert {
        row["action"]
        for row in connection.execute(
            "SELECT action FROM audit_events WHERE action LIKE '%.archived'"
        )
    } == {"customer.archived", "site.archived", "contact.archived"}


def test_normalized_duplicates_are_tenant_and_relationship_scoped(tmp_path: Path) -> None:
    _, service, contexts = _setup(tmp_path)
    customer_a = service.create_customer(
        contexts["admin_a"], " Shared Name ", correlation_id="customer-a"
    )
    customer_b = service.create_customer(
        contexts["admin_b"], "shared name", correlation_id="customer-b"
    )
    assert customer_a.organization_id != customer_b.organization_id
    with pytest.raises(CustomerConflict, match="customer already exists"):
        service.create_customer(contexts["admin_a"], "SHARED NAME", correlation_id="duplicate")

    site = service.create_site(
        contexts["admin_a"], customer_a.id, " 1  Main ", correlation_id="site"
    )
    with pytest.raises(CustomerConflict, match="site already exists"):
        service.create_site(
            contexts["admin_a"], customer_a.id, "1 MAIN", correlation_id="duplicate-site"
        )
    service.create_contact(
        contexts["admin_a"],
        customer_a.id,
        " Person ",
        "0400 000 000",
        site_id=site.id,
        correlation_id="contact",
    )
    with pytest.raises(CustomerConflict, match="contact already exists"):
        service.create_contact(
            contexts["admin_a"],
            customer_a.id,
            "PERSON",
            "0400 999 999",
            site_id=site.id,
            correlation_id="duplicate-contact",
        )
    # The same name is valid at the customer level because it is a distinct relationship scope.
    service.create_contact(
        contexts["admin_a"],
        customer_a.id,
        "person",
        "0400 111 111",
        correlation_id="general-contact",
    )


@pytest.mark.parametrize(
    ("operation", "message"),
    [
        (
            lambda service, context: service.create_customer(context, " ", correlation_id="bad"),
            "name",
        ),
        (
            lambda service, context: service.create_customer(
                context, "x" * 101, correlation_id="bad"
            ),
            "name",
        ),
        (
            lambda service, context: service.create_site(
                context, "customer", "x" * 201, correlation_id="bad"
            ),
            "address",
        ),
        (
            lambda service, context: service.create_contact(
                context, "customer", "Name", "x" * 41, correlation_id="bad"
            ),
            "phone",
        ),
    ],
)
def test_text_fields_are_normalized_and_length_limited(
    tmp_path: Path, operation, message: str
) -> None:
    _, service, contexts = _setup(tmp_path)
    with pytest.raises(ValueError, match=message):
        operation(service, contexts["admin_a"])


def test_audit_failure_rolls_back_create_and_archive(tmp_path: Path) -> None:
    connection, service, contexts = _setup(tmp_path)
    context = contexts["admin_a"]
    customer = service.create_customer(context, "Keep", correlation_id="create")
    connection.execute(
        """
        CREATE TRIGGER reject_customer_audit
        BEFORE INSERT ON audit_events
        WHEN NEW.action IN (
            'customer.created', 'site.created', 'contact.created',
            'customer.archived', 'site.archived', 'contact.archived'
        )
        BEGIN
            SELECT RAISE(ABORT, 'forced customer audit failure');
        END
        """
    )
    connection.commit()

    with pytest.raises(sqlite3.IntegrityError, match="forced customer audit failure"):
        service.create_customer(context, "Rollback", correlation_id="create-fails")
    with pytest.raises(sqlite3.IntegrityError, match="forced customer audit failure"):
        service.archive_customer(context, customer.id, correlation_id="archive-fails")

    assert (
        connection.execute("SELECT COUNT(*) FROM customers WHERE name = 'Rollback'").fetchone()[0]
        == 0
    )
    assert (
        connection.execute("SELECT status FROM customers WHERE id = ?", (customer.id,)).fetchone()[
            0
        ]
        == "active"
    )


def test_write_rechecks_revocation_after_obtaining_lock(tmp_path: Path) -> None:
    connection = connect_sqlite(tmp_path / "test.db")
    apply_migrations(connection)
    contexts = _setup_contexts_on_connection(connection)

    class RevokeAfterLock:
        def __init__(self) -> None:
            self.calls = 0

        def require_active(self, active_connection, context) -> None:
            self.calls += 1
            if self.calls == 3:
                active_connection.execute(
                    """
                    UPDATE organization_memberships SET status = 'disabled'
                    WHERE organization_id = ? AND user_id = ?
                    """,
                    (context.organization_id, context.user_id),
                )
            AUTHORITY.require_active(active_connection, context)

    service = CustomerService(CustomerRepository(connection, RevokeAfterLock()))
    with pytest.raises(PermissionError, match="no longer active"):
        service.create_customer(contexts["admin_a"], "Race", correlation_id="race")

    assert connection.execute("SELECT COUNT(*) FROM customers").fetchone()[0] == 0
    assert connection.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0] == 0


def test_ambient_transaction_is_preserved_without_rollback(tmp_path: Path) -> None:
    connection, service, contexts = _setup(tmp_path)
    connection.execute(
        "INSERT INTO system_config (organization_id, key, value) VALUES (?, ?, ?)",
        ("org-a", "pending", "keep"),
    )

    with pytest.raises(TransactionOwnershipError, match="active transaction"):
        service.create_customer(contexts["admin_a"], "Blocked", correlation_id="ambient")

    assert connection.in_transaction is True
    assert (
        connection.execute(
            "SELECT value FROM system_config WHERE organization_id = 'org-a' AND key = 'pending'"
        ).fetchone()[0]
        == "keep"
    )


def test_repository_rejects_direct_validation_bypass(tmp_path: Path) -> None:
    connection, _, contexts = _setup(tmp_path)
    repository = CustomerRepository(connection, AUTHORITY)
    with pytest.raises(ValueError, match="normalized name"):
        repository.create_customer(contexts["admin_a"], " bad ", correlation_id="direct")
