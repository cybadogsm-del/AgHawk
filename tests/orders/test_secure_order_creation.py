import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from turfhelm.db.connection import connect_sqlite
from turfhelm.db.migrations import apply_migrations
from turfhelm.repositories.orders import (
    CreateOrderInput,
    OrderConflict,
    OrderRepository,
    OrderSelectionNotFound,
    TransactionOwnershipError,
)
from turfhelm.security.authentication import AuthenticatedPrincipal
from turfhelm.security.authority import SecurityContextAuthority
from turfhelm.security.permissions import PermissionDenied

AUTHORITY = SecurityContextAuthority(signing_key=b"order-create-test-key-" + (b"x" * 32))
SQLITE_INTEGER_MAX = 9_223_372_036_854_775_807
MAXIMUM_EXPECTED_VERSION = SQLITE_INTEGER_MAX - 1


def seeded_repository(tmp_path: Path):
    connection = connect_sqlite(tmp_path / "orders.db")
    apply_migrations(connection)
    connection.execute(
        "INSERT INTO organizations (id, name, slug) VALUES ('org-a', 'Farm A', 'farm-a')"
    )
    connection.execute(
        """
        INSERT INTO users (id, oidc_subject, email, display_name)
        VALUES ('admin-a', 'oidc|admin-a', 'admin@example.com', 'Admin')
        """
    )
    connection.execute(
        """
        INSERT INTO organization_memberships (organization_id, user_id, role)
        VALUES ('org-a', 'admin-a', 'admin')
        """
    )
    connection.execute(
        """
        INSERT INTO customers (id, organization_id, name)
        VALUES ('customer-a', 'org-a', 'Customer')
        """
    )
    connection.execute(
        """
        INSERT INTO sites (id, organization_id, customer_id, address)
        VALUES ('site-a', 'org-a', 'customer-a', '1 Main Street')
        """
    )
    connection.execute(
        """
        INSERT INTO contacts (id, organization_id, customer_id, site_id, name, phone)
        VALUES ('contact-a', 'org-a', 'customer-a', 'site-a', 'Person', '0400')
        """
    )
    connection.execute(
        """
        INSERT INTO service_types (id, organization_id, name)
        VALUES ('service-a', 'org-a', 'Supply')
        """
    )
    connection.execute(
        "INSERT INTO varieties (id, organization_id, name) VALUES ('variety-a', 'org-a', 'Kikuyu')"
    )
    connection.execute(
        "INSERT INTO pallet_sizes (id, organization_id, size) VALUES ('pallet-a', 'org-a', 60)"
    )
    connection.execute(
        """
        INSERT INTO transport_options (id, organization_id, name, pallet_capacity)
        VALUES ('transport-a', 'org-a', 'Truck', 20)
        """
    )
    connection.execute(
        "INSERT INTO teams (id, organization_id, name) VALUES ('team-a', 'org-a', 'Crew A')"
    )
    connection.commit()
    context = AUTHORITY.resolve(
        connection,
        principal=AuthenticatedPrincipal(
            oidc_subject="oidc|admin-a", expires_at=datetime.max.replace(tzinfo=UTC)
        ),
        organization_id="org-a",
    )
    return connection, context, OrderRepository(connection, AUTHORITY)


def valid_input(**overrides: object) -> CreateOrderInput:
    values = {
        "customer_id": "customer-a",
        "site_id": "site-a",
        "site_contact_id": None,
        "service_type_id": "service-a",
        "variety_id": "variety-a",
        "pallet_size_id": "pallet-a",
        "transport_option_id": None,
        "team_id": None,
        "purchase_order": "PO 123",
        "special_instructions": "Call before arrival",
        "parking_pin": "Map pin 1",
        "m2_area": 125,
        "harvest_date": None,
        "install_date": None,
    }
    values.update(overrides)
    return CreateOrderInput(**values)


def test_admin_creates_pending_order_from_authoritative_catalog_snapshots(tmp_path: Path) -> None:
    connection, context, repository = seeded_repository(tmp_path)

    created = repository.create(context, valid_input(), correlation_id="request-1")

    order = connection.execute("SELECT * FROM orders WHERE id = ?", (created.id,)).fetchone()
    reference = connection.execute(
        "SELECT * FROM order_catalog_references WHERE order_id = ?", (created.id,)
    ).fetchone()
    audit = connection.execute(
        "SELECT * FROM audit_events WHERE object_id = ?", (created.id,)
    ).fetchone()
    assert created.status == "pending"
    assert order["service_type"] == "Supply"
    assert order["pallet_size"] == 60
    assert (order["full_pallets"], order["loose_rolls"], order["remaining_balance"]) == (
        2,
        5,
        125,
    )
    reference_values = (
        reference["organization_id"],
        reference["service_type_id"],
        reference["pallet_size_id"],
    )
    assert reference_values == (
        "org-a",
        "service-a",
        "pallet-a",
    )
    assert audit["action"] == "order.created"
    assert audit["correlation_id"] == "request-1"


def assert_no_creation_writes(connection) -> None:
    assert connection.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 0
    assert connection.execute("SELECT COUNT(*) FROM order_catalog_references").fetchone()[0] == 0
    assert connection.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0] == 0


def add_other_organization_catalog(connection) -> None:
    connection.execute(
        "INSERT INTO organizations (id, name, slug) VALUES ('org-b', 'Farm B', 'farm-b')"
    )
    connection.execute(
        "INSERT INTO customers (id, organization_id, name) VALUES ('customer-b', 'org-b', 'Other')"
    )
    connection.execute(
        """
        INSERT INTO sites (id, organization_id, customer_id, address)
        VALUES ('site-b', 'org-b', 'customer-b', '2 Other Street')
        """
    )
    connection.execute(
        """
        INSERT INTO contacts (id, organization_id, customer_id, site_id, name, phone)
        VALUES ('contact-b', 'org-b', 'customer-b', 'site-b', 'Other', '0500')
        """
    )
    connection.execute(
        """
        INSERT INTO service_types (id, organization_id, name)
        VALUES ('service-b', 'org-b', 'Other')
        """
    )
    connection.execute(
        "INSERT INTO varieties (id, organization_id, name) VALUES ('variety-b', 'org-b', 'Other')"
    )
    connection.execute(
        "INSERT INTO pallet_sizes (id, organization_id, size) VALUES ('pallet-b', 'org-b', 50)"
    )
    connection.execute(
        """
        INSERT INTO transport_options (id, organization_id, name, pallet_capacity)
        VALUES ('transport-b', 'org-b', 'Other', 1)
        """
    )
    connection.execute(
        "INSERT INTO teams (id, organization_id, name) VALUES ('team-b', 'org-b', 'Other')"
    )
    connection.commit()


@pytest.mark.parametrize(
    ("field", "foreign_id"),
    [
        ("customer_id", "customer-b"),
        ("site_id", "site-b"),
        ("site_contact_id", "contact-b"),
        ("service_type_id", "service-b"),
        ("variety_id", "variety-b"),
        ("pallet_size_id", "pallet-b"),
        ("transport_option_id", "transport-b"),
        ("team_id", "team-b"),
    ],
)
def test_cross_organization_selection_is_denied_without_writes(
    tmp_path: Path, field: str, foreign_id: str
) -> None:
    connection, context, repository = seeded_repository(tmp_path)
    add_other_organization_catalog(connection)

    with pytest.raises(OrderSelectionNotFound):
        repository.create(context, valid_input(**{field: foreign_id}), correlation_id="request")

    assert_no_creation_writes(connection)


@pytest.mark.parametrize(
    ("archive_sql", "field", "record_id"),
    [
        ("UPDATE customers SET status = 'archived' WHERE id = ?", "customer_id", "customer-a"),
        ("UPDATE sites SET status = 'archived' WHERE id = ?", "site_id", "site-a"),
        ("UPDATE contacts SET status = 'archived' WHERE id = ?", "site_contact_id", "contact-a"),
        (
            "UPDATE service_types SET status = 'archived' WHERE id = ?",
            "service_type_id",
            "service-a",
        ),
        ("UPDATE varieties SET status = 'archived' WHERE id = ?", "variety_id", "variety-a"),
        ("UPDATE pallet_sizes SET status = 'archived' WHERE id = ?", "pallet_size_id", "pallet-a"),
        (
            "UPDATE transport_options SET status = 'archived' WHERE id = ?",
            "transport_option_id",
            "transport-a",
        ),
        ("UPDATE teams SET status = 'archived' WHERE id = ?", "team_id", "team-a"),
    ],
)
def test_archived_selection_is_denied_without_writes(
    tmp_path: Path, archive_sql: str, field: str, record_id: str
) -> None:
    connection, context, repository = seeded_repository(tmp_path)
    connection.execute(archive_sql, (record_id,))
    connection.commit()

    with pytest.raises(OrderSelectionNotFound):
        repository.create(context, valid_input(**{field: record_id}), correlation_id="request")

    assert_no_creation_writes(connection)


def test_site_and_contact_must_match_exact_customer_and_site(tmp_path: Path) -> None:
    connection, context, repository = seeded_repository(tmp_path)
    connection.execute(
        "INSERT INTO customers (id, organization_id, name) VALUES ('customer-2', 'org-a', 'Two')"
    )
    connection.execute(
        """
        INSERT INTO sites (id, organization_id, customer_id, address)
        VALUES ('site-2', 'org-a', 'customer-2', '2 Main')
        """
    )
    connection.execute(
        """
        INSERT INTO contacts (id, organization_id, customer_id, site_id, name, phone)
        VALUES ('contact-2', 'org-a', 'customer-2', 'site-2', 'Two', '0500')
        """
    )
    connection.commit()

    with pytest.raises(OrderSelectionNotFound):
        repository.create(context, valid_input(site_id="site-2"), correlation_id="site-mismatch")
    with pytest.raises(OrderSelectionNotFound):
        repository.create(
            context, valid_input(site_contact_id="contact-2"), correlation_id="contact-mismatch"
        )

    assert_no_creation_writes(connection)


@pytest.mark.parametrize("role", ["farm_staff", "site_supervisor", "driver", "installer"])
def test_every_non_admin_role_is_denied_without_writes(tmp_path: Path, role: str) -> None:
    connection, _context, _repository = seeded_repository(tmp_path)
    connection.execute(
        "UPDATE organization_memberships SET role = ? WHERE user_id = 'admin-a'", (role,)
    )
    connection.commit()
    context = AUTHORITY.resolve(
        connection,
        principal=AuthenticatedPrincipal(
            oidc_subject="oidc|admin-a", expires_at=datetime.max.replace(tzinfo=UTC)
        ),
        organization_id="org-a",
    )

    with pytest.raises(PermissionDenied):
        OrderRepository(connection, AUTHORITY).create(
            context, valid_input(), correlation_id="denied"
        )

    assert_no_creation_writes(connection)


@pytest.mark.parametrize(
    "disable_sql",
    [
        "UPDATE users SET status = 'disabled' WHERE id = 'admin-a'",
        "UPDATE organization_memberships SET status = 'disabled' WHERE user_id = 'admin-a'",
    ],
)
def test_disabled_or_revoked_context_is_denied_without_writes(
    tmp_path: Path, disable_sql: str
) -> None:
    connection, context, repository = seeded_repository(tmp_path)
    connection.execute(disable_sql)
    connection.commit()

    with pytest.raises(PermissionError):
        repository.create(context, valid_input(), correlation_id="revoked")

    assert_no_creation_writes(connection)


def test_revocation_immediately_before_lock_is_rechecked(tmp_path: Path) -> None:
    connection, context, _repository = seeded_repository(tmp_path)

    class RevokeAfterInitialCheck:
        def __init__(self) -> None:
            self.calls = 0

        def require_active(self, checked_connection, checked_context) -> None:
            AUTHORITY.require_active(checked_connection, checked_context)
            self.calls += 1
            if self.calls == 1:
                checked_connection.execute(
                    """
                    UPDATE organization_memberships SET status = 'disabled'
                    WHERE user_id = 'admin-a'
                    """
                )
                checked_connection.commit()

    authority = RevokeAfterInitialCheck()
    repository = OrderRepository(connection, authority)  # type: ignore[arg-type]

    with pytest.raises(PermissionError):
        repository.create(context, valid_input(), correlation_id="race")

    assert authority.calls == 1
    assert_no_creation_writes(connection)


def test_empty_catalogs_do_not_produce_hidden_defaults(tmp_path: Path) -> None:
    connection, context, repository = seeded_repository(tmp_path)
    connection.execute("DELETE FROM service_types")
    connection.execute("DELETE FROM varieties")
    connection.execute("DELETE FROM pallet_sizes")
    connection.commit()

    with pytest.raises(OrderSelectionNotFound):
        repository.create(context, valid_input(), correlation_id="empty")

    assert_no_creation_writes(connection)


@pytest.mark.parametrize(
    "field",
    ["customer_id", "site_id", "service_type_id", "variety_id", "pallet_size_id"],
)
def test_required_selection_ids_have_no_implicit_default(tmp_path: Path, field: str) -> None:
    connection, context, repository = seeded_repository(tmp_path)

    with pytest.raises(ValueError, match="normalized"):
        repository.create(context, valid_input(**{field: None}), correlation_id="missing-id")

    assert_no_creation_writes(connection)


@pytest.mark.parametrize(("m2_area", "expected"), [(59, (0, 59)), (120, (2, 0)), (121, (2, 1))])
def test_pallet_calculation_uses_authoritative_size(
    tmp_path: Path, m2_area: int, expected: tuple[int, int]
) -> None:
    connection, context, repository = seeded_repository(tmp_path)

    created = repository.create(
        context, valid_input(m2_area=m2_area), correlation_id=f"calc-{m2_area}"
    )

    row = connection.execute(
        "SELECT full_pallets, loose_rolls FROM orders WHERE id = ?", (created.id,)
    ).fetchone()
    assert tuple(row) == expected


@pytest.mark.parametrize("m2_area", [0, -1, True, 1.5, "1"])
def test_m2_must_be_a_positive_integer(tmp_path: Path, m2_area: object) -> None:
    connection, context, repository = seeded_repository(tmp_path)

    with pytest.raises(ValueError, match="positive integer"):
        repository.create(context, valid_input(m2_area=m2_area), correlation_id="invalid-area")

    assert_no_creation_writes(connection)


def test_m2_accepts_sqlite_signed_integer_maximum(tmp_path: Path) -> None:
    connection, context, repository = seeded_repository(tmp_path)

    created = repository.create(
        context,
        valid_input(m2_area=9_223_372_036_854_775_807),
        correlation_id="maximum-area",
    )

    stored = connection.execute(
        "SELECT m2_area FROM orders WHERE id = ?", (created.id,)
    ).fetchone()[0]
    assert stored == 9_223_372_036_854_775_807


def test_m2_rejects_values_above_sqlite_signed_integer_maximum_before_write(
    tmp_path: Path,
) -> None:
    connection, context, repository = seeded_repository(tmp_path)

    with pytest.raises(ValueError, match="SQLite integer maximum"):
        repository.create(
            context,
            valid_input(m2_area=9_223_372_036_854_775_808),
            correlation_id="oversized-area",
        )

    assert_no_creation_writes(connection)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"harvest_date": "2026-08-01"}, "both"),
        ({"install_date": "2026-08-01"}, "both"),
        ({"harvest_date": "2026-08-02", "install_date": "2026-08-01"}, "after"),
        ({"harvest_date": "2026-8-1", "install_date": "2026-08-01"}, "ISO"),
        ({"harvest_date": "not-a-date", "install_date": "2026-08-01"}, "ISO"),
    ],
)
def test_invalid_date_pairs_are_rejected_without_writes(
    tmp_path: Path, overrides: dict[str, object], message: str
) -> None:
    connection, context, repository = seeded_repository(tmp_path)

    with pytest.raises(ValueError, match=message):
        repository.create(context, valid_input(**overrides), correlation_id="invalid-date")

    assert_no_creation_writes(connection)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("purchase_order", " leading"),
        ("purchase_order", "x" * 101),
        ("special_instructions", "two  spaces"),
        ("special_instructions", "x" * 2001),
        ("parking_pin", "trailing "),
        ("parking_pin", "x" * 501),
        ("customer_id", ""),
        ("site_id", "x" * 101),
        ("service_type_id", " service-a"),
    ],
)
def test_text_and_id_bounds_are_rejected_without_writes(
    tmp_path: Path, field: str, value: str
) -> None:
    connection, context, repository = seeded_repository(tmp_path)

    with pytest.raises(ValueError, match="normalized"):
        repository.create(context, valid_input(**{field: value}), correlation_id="invalid-text")

    assert_no_creation_writes(connection)


def test_scheduled_order_stores_all_optional_values(tmp_path: Path) -> None:
    connection, context, repository = seeded_repository(tmp_path)

    created = repository.create(
        context,
        valid_input(
            site_contact_id="contact-a",
            transport_option_id="transport-a",
            team_id="team-a",
            harvest_date="2026-08-04",
            install_date="2026-08-05",
        ),
        correlation_id="scheduled",
    )

    row = connection.execute("SELECT * FROM orders WHERE id = ?", (created.id,)).fetchone()
    assert created.status == "scheduled"
    assert (row["site_contact_id"], row["transport_option_id"], row["team_id"]) == (
        "contact-a",
        "transport-a",
        "team-a",
    )
    assert (row["harvest_date"], row["install_date"]) == ("2026-08-04", "2026-08-05")


def test_audit_failure_rolls_back_order_and_reference(tmp_path: Path) -> None:
    connection, context, repository = seeded_repository(tmp_path)
    connection.execute(
        """
        CREATE TRIGGER reject_order_audit
        BEFORE INSERT ON audit_events WHEN NEW.action = 'order.created'
        BEGIN SELECT RAISE(ABORT, 'simulated audit outage'); END
        """
    )
    connection.commit()

    with pytest.raises(OrderConflict, match="could not be created"):
        repository.create(context, valid_input(), correlation_id="audit-fails")

    assert_no_creation_writes(connection)


def test_ambient_transaction_is_preserved_and_not_rolled_back(tmp_path: Path) -> None:
    connection, context, repository = seeded_repository(tmp_path)
    connection.execute(
        "INSERT INTO system_config (organization_id, key, value) VALUES ('org-a', 'pending', 'yes')"
    )

    with pytest.raises(TransactionOwnershipError):
        repository.create(context, valid_input(), correlation_id="ambient")

    assert connection.in_transaction is True
    pending = connection.execute(
        "SELECT value FROM system_config WHERE key = 'pending'"
    ).fetchone()
    assert pending[0] == "yes"
    connection.rollback()
    pending = connection.execute(
        "SELECT value FROM system_config WHERE key = 'pending'"
    ).fetchone()
    assert pending is None


def test_sidecar_foreign_keys_enforce_tenant_boundaries(tmp_path: Path) -> None:
    connection, context, repository = seeded_repository(tmp_path)
    add_other_organization_catalog(connection)
    created = repository.create(context, valid_input(), correlation_id="valid")
    connection.execute("DELETE FROM order_catalog_references WHERE order_id = ?", (created.id,))

    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """
            INSERT INTO order_catalog_references (
                order_id, organization_id, service_type_id, pallet_size_id
            ) VALUES (?, 'org-a', 'service-b', 'pallet-b')
            """,
            (created.id,),
        )
    connection.rollback()


def test_catalog_archive_preserves_historical_snapshots_and_stable_ids(tmp_path: Path) -> None:
    connection, context, repository = seeded_repository(tmp_path)
    created = repository.create(context, valid_input(), correlation_id="history")

    connection.execute("UPDATE service_types SET status = 'archived' WHERE id = 'service-a'")
    connection.execute("UPDATE pallet_sizes SET status = 'archived' WHERE id = 'pallet-a'")
    connection.commit()

    with pytest.raises(sqlite3.IntegrityError):
        connection.execute("DELETE FROM service_types WHERE id = 'service-a'")
    connection.rollback()

    order = connection.execute(
        "SELECT service_type, pallet_size FROM orders WHERE id = ?", (created.id,)
    ).fetchone()
    reference = connection.execute(
        "SELECT service_type_id, pallet_size_id FROM order_catalog_references WHERE order_id = ?",
        (created.id,),
    ).fetchone()
    assert tuple(order) == ("Supply", 60)
    assert tuple(reference) == ("service-a", "pallet-a")


def test_created_order_id_is_a_uuid(tmp_path: Path) -> None:
    _connection, context, repository = seeded_repository(tmp_path)

    created = repository.create(context, valid_input(), correlation_id="uuid")

    assert str(uuid.UUID(created.id)) == created.id


@pytest.mark.parametrize("initial_status", ["pending", "scheduled"])
def test_admin_cancellation_is_versioned_and_audited_atomically(
    tmp_path: Path, initial_status: str
) -> None:
    connection, context, repository = seeded_repository(tmp_path)
    dates = (
        {}
        if initial_status == "pending"
        else {"harvest_date": "2026-08-04", "install_date": "2026-08-05"}
    )
    created = repository.create(context, valid_input(**dates), correlation_id="create")

    changed = repository.update_status(
        context,
        created.id,
        "cancelled",
        expected_version=1,
        correlation_id="cancel-request",
    )

    order = connection.execute(
        "SELECT status, version FROM orders WHERE id = ?", (created.id,)
    ).fetchone()
    audit = connection.execute(
        "SELECT * FROM audit_events WHERE object_id = ? AND action = 'order.status.updated'",
        (created.id,),
    ).fetchone()
    assert changed is True
    assert tuple(order) == ("cancelled", 2)
    assert audit["organization_id"] == "org-a"
    assert audit["actor_user_id"] == "admin-a"
    assert audit["correlation_id"] == "cancel-request"
    assert json.loads(audit["before_summary"]) == {"status": initial_status, "version": 1}
    assert json.loads(audit["after_summary"]) == {"status": "cancelled", "version": 2}


def test_status_audit_failure_rolls_back_status_and_version(tmp_path: Path) -> None:
    connection, context, repository = seeded_repository(tmp_path)
    created = repository.create(context, valid_input(), correlation_id="create")
    connection.execute(
        """
        CREATE TRIGGER reject_status_audit
        BEFORE INSERT ON audit_events WHEN NEW.action = 'order.status.updated'
        BEGIN SELECT RAISE(ABORT, 'simulated audit outage'); END
        """
    )
    connection.commit()

    with pytest.raises(OrderConflict, match="status update conflict"):
        repository.update_status(
            context,
            created.id,
            "cancelled",
            expected_version=1,
            correlation_id="audit-fails",
        )

    row = connection.execute(
        "SELECT status, version FROM orders WHERE id = ?", (created.id,)
    ).fetchone()
    assert tuple(row) == ("pending", 1)


def test_status_update_rejects_ambient_transaction_without_rollback(tmp_path: Path) -> None:
    connection, context, repository = seeded_repository(tmp_path)
    created = repository.create(context, valid_input(), correlation_id="create")
    connection.execute(
        "INSERT INTO system_config (organization_id, key, value) VALUES ('org-a', 'pending', 'yes')"
    )

    with pytest.raises(TransactionOwnershipError):
        repository.update_status(
            context,
            created.id,
            "cancelled",
            expected_version=1,
            correlation_id="ambient",
        )

    assert connection.in_transaction is True
    assert connection.execute(
        "SELECT value FROM system_config WHERE key = 'pending'"
    ).fetchone()[0] == "yes"
    connection.rollback()
    assert connection.execute(
        "SELECT value FROM system_config WHERE key = 'pending'"
    ).fetchone() is None


def test_status_update_revalidates_revocation_after_write_lock(tmp_path: Path) -> None:
    connection, context, _repository = seeded_repository(tmp_path)
    created = OrderRepository(connection, AUTHORITY).create(
        context, valid_input(), correlation_id="create"
    )

    class RevokeAfterInitialCheck:
        def __init__(self) -> None:
            self.calls = 0

        def require_active(self, checked_connection, checked_context) -> None:
            AUTHORITY.require_active(checked_connection, checked_context)
            self.calls += 1
            if self.calls == 1:
                checked_connection.execute(
                    """
                    UPDATE organization_memberships SET status = 'disabled'
                    WHERE user_id = 'admin-a'
                    """
                )
                checked_connection.commit()

    authority = RevokeAfterInitialCheck()
    repository = OrderRepository(connection, authority)  # type: ignore[arg-type]

    with pytest.raises(PermissionError):
        repository.update_status(
            context,
            created.id,
            "cancelled",
            expected_version=1,
            correlation_id="revoked",
        )

    row = connection.execute(
        "SELECT status, version FROM orders WHERE id = ?", (created.id,)
    ).fetchone()
    assert tuple(row) == ("pending", 1)
    assert connection.execute(
        "SELECT COUNT(*) FROM audit_events WHERE action = 'order.status.updated'"
    ).fetchone()[0] == 0


@pytest.mark.parametrize("case", ["not-found", "cross-org", "stale"])
def test_status_update_returns_same_generic_conflict_without_writes(
    tmp_path: Path, case: str
) -> None:
    connection, context, repository = seeded_repository(tmp_path)
    created = repository.create(context, valid_input(), correlation_id="create")
    order_id = created.id
    expected_version = 1
    if case == "not-found":
        order_id = "missing-order"
    elif case == "cross-org":
        add_other_organization_catalog(connection)
        connection.execute(
            """
            INSERT INTO orders (
                id, organization_id, customer_id, variety_id,
                m2_area, pallet_size, remaining_balance
            ) VALUES ('order-b', 'org-b', 'customer-b', 'variety-b', 1, 1, 1)
            """
        )
        connection.commit()
        order_id = "order-b"
    else:
        expected_version = 2

    with pytest.raises(OrderConflict, match="^order status update conflict$"):
        repository.update_status(
            context,
            order_id,
            "cancelled",
            expected_version=expected_version,
            correlation_id="conflict",
        )

    assert connection.execute(
        "SELECT COUNT(*) FROM audit_events WHERE action = 'order.status.updated'"
    ).fetchone()[0] == 0
    assert tuple(
        connection.execute(
            "SELECT status, version FROM orders WHERE id = ?", (created.id,)
        ).fetchone()
    ) == ("pending", 1)


@pytest.mark.parametrize("status", ["Cancelled", "complete", "pending", " cancelled", True])
def test_status_update_rejects_illegal_target_status_before_write(
    tmp_path: Path, status: object
) -> None:
    connection, context, repository = seeded_repository(tmp_path)
    created = repository.create(context, valid_input(), correlation_id="create")

    with pytest.raises(ValueError, match="target status"):
        repository.update_status(
            context,
            created.id,
            status,  # type: ignore[arg-type]
            expected_version=1,
            correlation_id="illegal",
        )

    assert tuple(
        connection.execute(
            "SELECT status, version FROM orders WHERE id = ?", (created.id,)
        ).fetchone()
    ) == ("pending", 1)


def test_status_update_rejects_backwards_transition(tmp_path: Path) -> None:
    connection, context, repository = seeded_repository(tmp_path)
    created = repository.create(context, valid_input(), correlation_id="create")
    repository.update_status(
        context,
        created.id,
        "cancelled",
        expected_version=1,
        correlation_id="first-cancel",
    )

    with pytest.raises(OrderConflict, match="^order status update conflict$"):
        repository.update_status(
            context,
            created.id,
            "cancelled",
            expected_version=2,
            correlation_id="repeat-cancel",
        )

    assert tuple(
        connection.execute(
            "SELECT status, version FROM orders WHERE id = ?", (created.id,)
        ).fetchone()
    ) == ("cancelled", 2)
    assert connection.execute(
        "SELECT COUNT(*) FROM audit_events WHERE action = 'order.status.updated'"
    ).fetchone()[0] == 1


@pytest.mark.parametrize(
    "expected_version",
    [0, -1, True, 1.5, "1", SQLITE_INTEGER_MAX, SQLITE_INTEGER_MAX + 1],
)
def test_status_update_requires_bounded_positive_integer_expected_version(
    tmp_path: Path, expected_version: object
) -> None:
    connection, context, repository = seeded_repository(tmp_path)
    created = repository.create(context, valid_input(), correlation_id="create")

    with pytest.raises(ValueError, match="expected_version"):
        repository.update_status(
            context,
            created.id,
            "cancelled",
            expected_version=expected_version,  # type: ignore[arg-type]
            correlation_id="invalid-version",
        )

    assert tuple(
        connection.execute(
            "SELECT status, version FROM orders WHERE id = ?", (created.id,)
        ).fetchone()
    ) == ("pending", 1)


def test_status_update_at_sqlite_version_ceiling_returns_generic_conflict(
    tmp_path: Path,
) -> None:
    connection, context, repository = seeded_repository(tmp_path)
    created = repository.create(context, valid_input(), correlation_id="create")
    connection.execute(
        "UPDATE orders SET version = ? WHERE id = ?",
        (SQLITE_INTEGER_MAX, created.id),
    )
    connection.commit()

    with pytest.raises(OrderConflict, match="^order status update conflict$"):
        repository.update_status(
            context,
            created.id,
            "cancelled",
            expected_version=MAXIMUM_EXPECTED_VERSION,
            correlation_id="ceiling-conflict",
        )

    assert connection.execute(
        "SELECT version FROM orders WHERE id = ?", (created.id,)
    ).fetchone()[0] == SQLITE_INTEGER_MAX


@pytest.mark.parametrize(
    ("order_id", "correlation_id"),
    [
        (" order", "valid"),
        ("", "valid"),
        ("x" * 101, "valid"),
        ("order", " bad"),
        ("order", ""),
        ("order", "x" * 101),
    ],
)
def test_status_update_rejects_unbounded_or_unnormalized_identifiers(
    tmp_path: Path, order_id: str, correlation_id: str
) -> None:
    connection, context, repository = seeded_repository(tmp_path)

    with pytest.raises(ValueError, match="normalized"):
        repository.update_status(
            context,
            order_id,
            "cancelled",
            expected_version=1,
            correlation_id=correlation_id,
        )

    assert connection.execute(
        "SELECT COUNT(*) FROM audit_events WHERE action = 'order.status.updated'"
    ).fetchone()[0] == 0
