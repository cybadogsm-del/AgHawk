import shutil
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest

from turfhelm.db.connection import connect_sqlite
from turfhelm.db.migrations import MIGRATIONS_DIRECTORY, apply_migrations

TENANT_TABLES = {
    "organization_memberships",
    "customers",
    "sites",
    "contacts",
    "varieties",
    "pallet_sizes",
    "transport_options",
    "teams",
    "orders",
    "system_config",
    "audit_events",
    "order_assignments",
    "team_memberships",
    "brand_assets",
    "organization_branding",
    "service_types",
    "order_catalog_references",
}


def test_initial_migration_puts_every_business_table_inside_an_organization(
    tmp_path: Path,
) -> None:
    connection = connect_sqlite(tmp_path / "test.db")

    apply_migrations(connection)

    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    assert {"organizations", "users", "schema_migrations"} <= tables
    assert TENANT_TABLES <= tables

    for table in TENANT_TABLES:
        columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table})").fetchall()}
        assert "organization_id" in columns, f"{table} has no organization wall"


def test_database_rejects_cross_organization_relationships(tmp_path: Path) -> None:
    connection = connect_sqlite(tmp_path / "test.db")
    apply_migrations(connection)
    connection.executemany(
        "INSERT INTO organizations (id, name, slug) VALUES (?, ?, ?)",
        [("org-a", "Farm A", "farm-a"), ("org-b", "Farm B", "farm-b")],
    )
    connection.execute(
        "INSERT INTO customers (id, organization_id, name) VALUES (?, ?, ?)",
        ("customer-b", "org-b", "Farm B Customer"),
    )
    connection.execute(
        "INSERT INTO varieties (id, organization_id, name) VALUES (?, ?, ?)",
        ("variety-a", "org-a", "Farm A Variety"),
    )

    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """
            INSERT INTO orders (
                id, organization_id, customer_id, variety_id,
                m2_area, pallet_size, remaining_balance
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("order-a", "org-a", "customer-b", "variety-a", 120, 60, 120),
        )


@pytest.mark.parametrize(
    "table",
    ["varieties", "transport_options", "teams", "service_types"],
)
def test_named_catalog_database_preserves_case_variants_for_admin_cleanup(
    tmp_path: Path, table: str
) -> None:
    connection = connect_sqlite(tmp_path / "test.db")
    apply_migrations(connection)
    connection.executemany(
        "INSERT INTO organizations (id, name, slug) VALUES (?, ?, ?)",
        [("org-a", "Farm A", "farm-a"), ("org-b", "Farm B", "farm-b")],
    )
    connection.execute(
        f"INSERT INTO {table} (id, organization_id, name) VALUES (?, ?, ?)",  # noqa: S608
        ("first", "org-a", "Shared Name"),
    )
    connection.execute(
        f"INSERT INTO {table} (id, organization_id, name) VALUES (?, ?, ?)",  # noqa: S608
        ("other-org", "org-b", "shared name"),
    )
    connection.execute(
        f"INSERT INTO {table} (id, organization_id, name) VALUES (?, ?, ?)",  # noqa: S608
        ("case-variant", "org-a", "SHARED NAME"),
    )

    count = connection.execute(
        f"SELECT COUNT(*) FROM {table} WHERE organization_id = ?",  # noqa: S608
        ("org-a",),
    ).fetchone()[0]
    assert count == 2


def test_order_site_must_belong_to_selected_customer(tmp_path: Path) -> None:
    connection = connect_sqlite(tmp_path / "test.db")
    apply_migrations(connection)
    connection.execute(
        "INSERT INTO organizations (id, name, slug) VALUES (?, ?, ?)",
        ("org-a", "Farm A", "farm-a"),
    )
    connection.executemany(
        "INSERT INTO customers (id, organization_id, name) VALUES (?, ?, ?)",
        [
            ("customer-1", "org-a", "Customer One"),
            ("customer-2", "org-a", "Customer Two"),
        ],
    )
    connection.execute(
        "INSERT INTO sites (id, organization_id, customer_id, address) VALUES (?, ?, ?, ?)",
        ("site-2", "org-a", "customer-2", "2 Other Street"),
    )
    connection.execute(
        "INSERT INTO varieties (id, organization_id, name) VALUES (?, ?, ?)",
        ("variety-1", "org-a", "Test Variety"),
    )

    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """
            INSERT INTO orders (
                id, organization_id, customer_id, site_id, variety_id,
                m2_area, pallet_size, remaining_balance
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "order-1",
                "org-a",
                "customer-1",
                "site-2",
                "variety-1",
                120,
                60,
                120,
            ),
        )


def test_order_contact_must_belong_to_selected_site(tmp_path: Path) -> None:
    connection = connect_sqlite(tmp_path / "test.db")
    apply_migrations(connection)
    connection.execute(
        "INSERT INTO organizations (id, name, slug) VALUES (?, ?, ?)",
        ("org-a", "Farm A", "farm-a"),
    )
    connection.execute(
        "INSERT INTO customers (id, organization_id, name) VALUES (?, ?, ?)",
        ("customer-1", "org-a", "Customer One"),
    )
    connection.executemany(
        "INSERT INTO sites (id, organization_id, customer_id, address) VALUES (?, ?, ?, ?)",
        [
            ("site-1", "org-a", "customer-1", "1 Main Street"),
            ("site-2", "org-a", "customer-1", "2 Main Street"),
        ],
    )
    connection.execute(
        """
        INSERT INTO contacts (id, organization_id, customer_id, site_id, name, phone)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        ("contact-2", "org-a", "customer-1", "site-2", "Other Contact", "0400000000"),
    )
    connection.execute(
        "INSERT INTO varieties (id, organization_id, name) VALUES (?, ?, ?)",
        ("variety-1", "org-a", "Test Variety"),
    )

    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """
            INSERT INTO orders (
                id, organization_id, customer_id, site_id, site_contact_id, variety_id,
                m2_area, pallet_size, remaining_balance
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "order-1",
                "org-a",
                "customer-1",
                "site-1",
                "contact-2",
                "variety-1",
                120,
                60,
                120,
            ),
        )


def test_audit_actor_must_belong_to_event_organization(tmp_path: Path) -> None:
    connection = connect_sqlite(tmp_path / "test.db")
    apply_migrations(connection)
    connection.executemany(
        "INSERT INTO organizations (id, name, slug) VALUES (?, ?, ?)",
        [("org-a", "Farm A", "farm-a"), ("org-b", "Farm B", "farm-b")],
    )
    connection.execute(
        """
        INSERT INTO users (id, oidc_subject, email, display_name)
        VALUES (?, ?, ?, ?)
        """,
        ("user-b", "subject-b", "user-b@example.com", "User B"),
    )
    connection.execute(
        """
        INSERT INTO organization_memberships (organization_id, user_id, role)
        VALUES (?, ?, ?)
        """,
        ("org-b", "user-b", "admin"),
    )

    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """
            INSERT INTO audit_events (
                id, organization_id, actor_user_id, action,
                object_type, object_id, outcome, correlation_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "event-1",
                "org-a",
                "user-b",
                "order.created",
                "order",
                "order-1",
                "success",
                "request-1",
            ),
        )


def test_audit_history_cannot_be_changed_or_deleted(tmp_path: Path) -> None:
    connection = connect_sqlite(tmp_path / "test.db")
    apply_migrations(connection)
    connection.execute(
        "INSERT INTO organizations (id, name, slug) VALUES (?, ?, ?)",
        ("org-a", "Farm A", "farm-a"),
    )
    connection.execute(
        """
        INSERT INTO audit_events (
            id, organization_id, action, object_type, object_id, outcome, correlation_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        ("event-1", "org-a", "order.created", "order", "order-1", "success", "request-1"),
    )
    connection.commit()

    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        connection.execute(
            "UPDATE audit_events SET action = ? WHERE id = ?",
            ("changed", "event-1"),
        )

    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        connection.execute("DELETE FROM audit_events WHERE id = ?", ("event-1",))


def test_audit_history_cannot_be_replaced(tmp_path: Path) -> None:
    connection = connect_sqlite(tmp_path / "test.db")
    apply_migrations(connection)
    connection.execute(
        "INSERT INTO organizations (id, name, slug) VALUES (?, ?, ?)",
        ("org-a", "Farm A", "farm-a"),
    )
    event = (
        "event-1",
        "org-a",
        "order.created",
        "order",
        "order-1",
        "success",
        "request-1",
    )
    connection.execute(
        """
        INSERT INTO audit_events (
            id, organization_id, action, object_type, object_id, outcome, correlation_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        event,
    )
    connection.commit()

    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        connection.execute(
            """
            INSERT OR REPLACE INTO audit_events (
                id, organization_id, action, object_type, object_id, outcome, correlation_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "event-1",
                "org-a",
                "order.forged",
                "order",
                "order-1",
                "success",
                "request-2",
            ),
        )

    action = connection.execute(
        "SELECT action FROM audit_events WHERE id = ?",
        ("event-1",),
    ).fetchone()[0]
    assert action == "order.created"


def test_concurrent_migration_runners_apply_each_version_once(tmp_path: Path) -> None:
    database_path = tmp_path / "test.db"
    workers = 8
    starting_line = Barrier(workers)

    def migrate() -> None:
        connection = connect_sqlite(database_path)
        try:
            starting_line.wait()
            apply_migrations(connection)
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(migrate) for _ in range(workers)]
        for future in futures:
            future.result()

    connection = connect_sqlite(database_path)
    versions = connection.execute(
        "SELECT version, COUNT(*) FROM schema_migrations GROUP BY version"
    ).fetchall()
    assert [(row[0], row[1]) for row in versions] == [
        ("0001_initial.sql", 1),
        ("0002_order_assignments.sql", 1),
        ("0003_organization_branding.sql", 1),
        ("0004_operational_catalogs.sql", 1),
        ("0005_customer_configuration.sql", 1),
        ("0006_order_catalog_references.sql", 1),
    ]


def test_customer_configuration_migration_preserves_existing_contacts_and_orders(
    tmp_path: Path,
) -> None:
    first_four = tmp_path / "first-four"
    first_four.mkdir()
    for migration in sorted(MIGRATIONS_DIRECTORY.glob("000[1-4]_*.sql")):
        shutil.copy(migration, first_four / migration.name)
    connection = connect_sqlite(tmp_path / "test.db")
    apply_migrations(connection, migrations_directory=first_four)
    connection.execute(
        "INSERT INTO organizations (id, name, slug) VALUES ('org-a', 'Farm A', 'farm-a')"
    )
    connection.execute(
        """
        INSERT INTO users (id, oidc_subject, display_name)
        VALUES ('worker', 'oidc|worker', 'Worker')
        """
    )
    connection.execute(
        """
        INSERT INTO organization_memberships (organization_id, user_id, role)
        VALUES ('org-a', 'worker', 'driver')
        """
    )
    connection.execute(
        "INSERT INTO customers (id, organization_id, name) VALUES ('customer', 'org-a', 'Customer')"
    )
    connection.execute(
        """
        INSERT INTO sites (id, organization_id, customer_id, address)
        VALUES ('site', 'org-a', 'customer', '1 Main')
        """
    )
    connection.execute(
        """
        INSERT INTO contacts (id, organization_id, site_id, name, phone)
        VALUES ('contact', 'org-a', 'site', 'Person', '0400')
        """
    )
    connection.execute(
        "INSERT INTO varieties (id, organization_id, name) VALUES ('variety', 'org-a', 'Grass')"
    )
    connection.execute(
        """
        INSERT INTO orders (
            id, organization_id, customer_id, site_id, site_contact_id,
            variety_id, m2_area, pallet_size, remaining_balance
        ) VALUES ('order', 'org-a', 'customer', 'site', 'contact', 'variety', 1, 1, 1)
        """
    )
    connection.execute(
        """
        INSERT INTO order_assignments (organization_id, order_id, user_id, assignment_role)
        VALUES ('org-a', 'order', 'worker', 'driver')
        """
    )
    connection.commit()

    apply_migrations(connection)

    contact = connection.execute("SELECT * FROM contacts WHERE id = 'contact'").fetchone()
    assert contact["customer_id"] == "customer"
    assert connection.execute("SELECT site_contact_id FROM orders WHERE id = 'order'").fetchone()[
        0
    ] == ("contact")
    assert connection.execute("SELECT order_id FROM order_assignments").fetchone()[0] == "order"
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_contacts_allow_customer_level_records_and_reject_wrong_customer_site_links(
    tmp_path: Path,
) -> None:
    connection = connect_sqlite(tmp_path / "test.db")
    apply_migrations(connection)
    connection.execute(
        "INSERT INTO organizations (id, name, slug) VALUES ('org-a', 'Farm A', 'farm-a')"
    )
    connection.executemany(
        "INSERT INTO customers (id, organization_id, name) VALUES (?, 'org-a', ?)",
        [("customer-1", "One"), ("customer-2", "Two")],
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
        VALUES ('general', 'org-a', 'customer-1', NULL, 'General', '0400')
        """
    )

    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """
            INSERT INTO contacts (id, organization_id, customer_id, site_id, name, phone)
            VALUES ('wrong', 'org-a', 'customer-1', 'site-2', 'Wrong', '0400')
            """
        )


def test_catalog_migrations_preserve_existing_case_variant_names(tmp_path: Path) -> None:
    first_three = tmp_path / "first-three"
    first_three.mkdir()
    for migration in sorted(MIGRATIONS_DIRECTORY.glob("000[1-3]_*.sql")):
        shutil.copy(migration, first_three / migration.name)
    connection = connect_sqlite(tmp_path / "test.db")
    apply_migrations(connection, migrations_directory=first_three)
    connection.execute(
        "INSERT INTO organizations (id, name, slug) VALUES ('org-a', 'Farm A', 'farm-a')"
    )
    connection.executemany(
        "INSERT INTO customers (id, organization_id, name) VALUES (?, 'org-a', ?)",
        [("customer-1", "Shared"), ("customer-2", "SHARED")],
    )
    connection.executemany(
        """
        INSERT INTO sites (id, organization_id, customer_id, address)
        VALUES (?, 'org-a', 'customer-1', ?)
        """,
        [("site-1", "1 Main"), ("site-2", "1 MAIN")],
    )
    connection.executemany(
        """
        INSERT INTO contacts (id, organization_id, site_id, name, phone)
        VALUES (?, 'org-a', 'site-1', ?, '0400')
        """,
        [("contact-1", "Person"), ("contact-2", "PERSON")],
    )
    connection.executemany(
        "INSERT INTO varieties (id, organization_id, name) VALUES (?, 'org-a', ?)",
        [("variety-1", "Kikuyu"), ("variety-2", "kikuyu")],
    )
    connection.executemany(
        """
        INSERT INTO transport_options (id, organization_id, name, pallet_capacity)
        VALUES (?, 'org-a', ?, 20)
        """,
        [("transport-1", "Truck"), ("transport-2", "TRUCK")],
    )
    connection.executemany(
        "INSERT INTO teams (id, organization_id, name) VALUES (?, 'org-a', ?)",
        [("team-1", "North"), ("team-2", "NORTH")],
    )
    connection.commit()

    apply_migrations(connection)

    counts = {
        "customers": connection.execute("SELECT COUNT(*) FROM customers").fetchone()[0],
        "sites": connection.execute("SELECT COUNT(*) FROM sites").fetchone()[0],
        "contacts": connection.execute("SELECT COUNT(*) FROM contacts").fetchone()[0],
        "varieties": connection.execute("SELECT COUNT(*) FROM varieties").fetchone()[0],
        "transport_options": connection.execute(
            "SELECT COUNT(*) FROM transport_options"
        ).fetchone()[0],
        "teams": connection.execute("SELECT COUNT(*) FROM teams").fetchone()[0],
    }
    assert set(counts.values()) == {2}
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_failed_migration_rolls_back_and_can_be_retried(tmp_path: Path) -> None:
    migrations_directory = tmp_path / "migrations"
    migrations_directory.mkdir()
    migration = migrations_directory / "0001_test.sql"
    migration.write_text(
        "CREATE TABLE first_partial (id TEXT); CREATE TABLE broken (",
        encoding="utf-8",
    )
    connection = connect_sqlite(tmp_path / "test.db")

    with pytest.raises(sqlite3.DatabaseError):
        apply_migrations(connection, migrations_directory=migrations_directory)

    tables_after_failure = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    assert "first_partial" not in tables_after_failure
    assert connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == 0

    migration.write_text("CREATE TABLE first_partial (id TEXT);", encoding="utf-8")
    apply_migrations(connection, migrations_directory=migrations_directory)

    assert (
        connection.execute(
            "SELECT COUNT(*) FROM schema_migrations WHERE version = ?",
            ("0001_test.sql",),
        ).fetchone()[0]
        == 1
    )
