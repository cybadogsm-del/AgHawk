from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import TypeVar

from turfhelm.security.authority import SecurityContextAuthority
from turfhelm.security.context import SecurityContext
from turfhelm.security.permissions import Action, require_permission


class CustomerConflict(RuntimeError):
    """A duplicate, dependency, or stale customer configuration conflict."""


class CustomerNotFound(RuntimeError):
    """A customer configuration ID is not visible in the active organization."""


class TransactionOwnershipError(RuntimeError):
    """Customer writes require a connection without an ambient transaction."""


@dataclass(frozen=True, slots=True)
class CustomerRecord:
    id: str
    organization_id: str
    name: str
    status: str


@dataclass(frozen=True, slots=True)
class SiteRecord:
    id: str
    organization_id: str
    customer_id: str
    address: str
    status: str


@dataclass(frozen=True, slots=True)
class ContactRecord:
    id: str
    organization_id: str
    customer_id: str
    site_id: str | None
    name: str
    phone: str
    status: str


_Record = TypeVar("_Record", CustomerRecord, SiteRecord, ContactRecord)


class CustomerRepository:
    """Relationship-aware, organization-scoped customer persistence."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        authority: SecurityContextAuthority,
    ) -> None:
        self._connection = connection
        self._authority = authority

    def require_manage(self, context: SecurityContext) -> None:
        self._authority.require_active(self._connection, context)
        require_permission(context.role, Action.CUSTOMER_MANAGE)

    def list_customers(self, context: SecurityContext) -> list[CustomerRecord]:
        self._authority.require_active(self._connection, context)
        rows = self._connection.execute(
            """
            SELECT id, organization_id, name, status
            FROM customers
            WHERE organization_id = ? AND status = 'active'
            ORDER BY name COLLATE NOCASE, id
            """,
            (context.organization_id,),
        ).fetchall()
        return [self._customer(row) for row in rows]

    def list_sites(self, context: SecurityContext, customer_id: str) -> list[SiteRecord]:
        self._authority.require_active(self._connection, context)
        self._require_active_customer(context, customer_id)
        rows = self._connection.execute(
            """
            SELECT id, organization_id, customer_id, address, status
            FROM sites
            WHERE organization_id = ? AND customer_id = ? AND status = 'active'
            ORDER BY address COLLATE NOCASE, id
            """,
            (context.organization_id, customer_id),
        ).fetchall()
        return [self._site(row) for row in rows]

    def list_contacts(
        self,
        context: SecurityContext,
        customer_id: str,
        *,
        site_id: str | None = None,
    ) -> list[ContactRecord]:
        self._authority.require_active(self._connection, context)
        self._require_active_customer(context, customer_id)
        if site_id is not None:
            self._require_active_site(context, customer_id, site_id)
            rows = self._connection.execute(
                """
                SELECT id, organization_id, customer_id, site_id, name, phone, status
                FROM contacts
                WHERE organization_id = ? AND customer_id = ? AND site_id = ?
                  AND status = 'active'
                ORDER BY name COLLATE NOCASE, id
                """,
                (context.organization_id, customer_id, site_id),
            ).fetchall()
        else:
            rows = self._connection.execute(
                """
                SELECT id, organization_id, customer_id, site_id, name, phone, status
                FROM contacts
                WHERE organization_id = ? AND customer_id = ? AND status = 'active'
                ORDER BY name COLLATE NOCASE, id
                """,
                (context.organization_id, customer_id),
            ).fetchall()
        return [self._contact(row) for row in rows]

    def create_customer(
        self,
        context: SecurityContext,
        name: str,
        *,
        correlation_id: str,
    ) -> CustomerRecord:
        self._validate_text(name, "name", 100)
        record_id = str(uuid.uuid4())

        def write() -> CustomerRecord:
            if self._connection.execute(
                "SELECT 1 FROM customers WHERE organization_id = ? AND name = ? COLLATE NOCASE",
                (context.organization_id, name),
            ).fetchone():
                raise CustomerConflict("customer already exists")
            self._connection.execute(
                "INSERT INTO customers (id, organization_id, name) VALUES (?, ?, ?)",
                (record_id, context.organization_id, name),
            )
            self._audit(
                context,
                "customer.created",
                "customer",
                record_id,
                None,
                {"name": name, "status": "active"},
                correlation_id,
            )
            return CustomerRecord(record_id, context.organization_id, name, "active")

        return self._owned_write(context, write)

    def create_site(
        self,
        context: SecurityContext,
        customer_id: str,
        address: str,
        *,
        correlation_id: str,
    ) -> SiteRecord:
        self._validate_text(address, "address", 200)
        record_id = str(uuid.uuid4())

        def write() -> SiteRecord:
            self._require_active_customer(context, customer_id)
            if self._connection.execute(
                """
                SELECT 1 FROM sites
                WHERE organization_id = ? AND customer_id = ? AND address = ? COLLATE NOCASE
                """,
                (context.organization_id, customer_id, address),
            ).fetchone():
                raise CustomerConflict("site already exists")
            self._connection.execute(
                """
                INSERT INTO sites (id, organization_id, customer_id, address)
                VALUES (?, ?, ?, ?)
                """,
                (record_id, context.organization_id, customer_id, address),
            )
            self._audit(
                context,
                "site.created",
                "site",
                record_id,
                None,
                {"customer_id": customer_id, "address": address, "status": "active"},
                correlation_id,
            )
            return SiteRecord(record_id, context.organization_id, customer_id, address, "active")

        return self._owned_write(context, write)

    def create_contact(
        self,
        context: SecurityContext,
        customer_id: str,
        name: str,
        phone: str,
        *,
        site_id: str | None,
        correlation_id: str,
    ) -> ContactRecord:
        self._validate_text(name, "name", 100)
        self._validate_text(phone, "phone", 40)
        record_id = str(uuid.uuid4())

        def write() -> ContactRecord:
            self._require_active_customer(context, customer_id)
            if site_id is not None:
                self._require_active_site(context, customer_id, site_id)
            duplicate = self._connection.execute(
                """
                SELECT 1 FROM contacts
                WHERE organization_id = ? AND customer_id = ?
                  AND ((site_id = ?) OR (site_id IS NULL AND ? IS NULL))
                  AND name = ? COLLATE NOCASE
                """,
                (context.organization_id, customer_id, site_id, site_id, name),
            ).fetchone()
            if duplicate:
                raise CustomerConflict("contact already exists")
            self._connection.execute(
                """
                INSERT INTO contacts (
                    id, organization_id, customer_id, site_id, name, phone
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (record_id, context.organization_id, customer_id, site_id, name, phone),
            )
            self._audit(
                context,
                "contact.created",
                "contact",
                record_id,
                None,
                {
                    "customer_id": customer_id,
                    "site_id": site_id,
                    "name": name,
                    "phone": phone,
                    "status": "active",
                },
                correlation_id,
            )
            return ContactRecord(
                record_id,
                context.organization_id,
                customer_id,
                site_id,
                name,
                phone,
                "active",
            )

        return self._owned_write(context, write)

    def archive_customer(
        self,
        context: SecurityContext,
        customer_id: str,
        *,
        correlation_id: str,
    ) -> CustomerRecord:
        def write() -> CustomerRecord:
            row = self._connection.execute(
                "SELECT * FROM customers WHERE id = ? AND organization_id = ?",
                (customer_id, context.organization_id),
            ).fetchone()
            if row is None:
                raise CustomerNotFound("customer not found")
            record = self._customer(row)
            if record.status != "active":
                raise CustomerConflict("customer is already archived")
            dependency = self._connection.execute(
                """
                SELECT 1 FROM sites
                WHERE organization_id = ? AND customer_id = ? AND status = 'active'
                UNION ALL
                SELECT 1 FROM contacts
                WHERE organization_id = ? AND customer_id = ? AND status = 'active'
                LIMIT 1
                """,
                (context.organization_id, customer_id, context.organization_id, customer_id),
            ).fetchone()
            if dependency is not None:
                raise CustomerConflict("customer has active sites or contacts")
            updated = self._connection.execute(
                """
                UPDATE customers SET status = 'archived'
                WHERE id = ? AND organization_id = ? AND status = 'active'
                """,
                (customer_id, context.organization_id),
            )
            if updated.rowcount != 1:
                raise CustomerConflict("customer changed before archive")
            self._audit(
                context,
                "customer.archived",
                "customer",
                customer_id,
                {"status": "active"},
                {"status": "archived"},
                correlation_id,
            )
            return replace(record, status="archived")

        return self._owned_write(context, write)

    def archive_site(
        self,
        context: SecurityContext,
        customer_id: str,
        site_id: str,
        *,
        correlation_id: str,
    ) -> SiteRecord:
        def write() -> SiteRecord:
            self._require_active_customer(context, customer_id)
            row = self._connection.execute(
                """
                SELECT * FROM sites
                WHERE id = ? AND organization_id = ? AND customer_id = ?
                """,
                (site_id, context.organization_id, customer_id),
            ).fetchone()
            if row is None:
                raise CustomerNotFound("site not found")
            record = self._site(row)
            if record.status != "active":
                raise CustomerConflict("site is already archived")
            dependency = self._connection.execute(
                """
                SELECT 1 FROM contacts
                WHERE organization_id = ? AND customer_id = ? AND site_id = ?
                  AND status = 'active'
                """,
                (context.organization_id, customer_id, site_id),
            ).fetchone()
            if dependency is not None:
                raise CustomerConflict("site has active contacts")
            updated = self._connection.execute(
                """
                UPDATE sites SET status = 'archived'
                WHERE id = ? AND organization_id = ? AND customer_id = ? AND status = 'active'
                """,
                (site_id, context.organization_id, customer_id),
            )
            if updated.rowcount != 1:
                raise CustomerConflict("site changed before archive")
            self._audit(
                context,
                "site.archived",
                "site",
                site_id,
                {"status": "active"},
                {"status": "archived"},
                correlation_id,
            )
            return replace(record, status="archived")

        return self._owned_write(context, write)

    def archive_contact(
        self,
        context: SecurityContext,
        customer_id: str,
        contact_id: str,
        *,
        correlation_id: str,
    ) -> ContactRecord:
        def write() -> ContactRecord:
            self._require_active_customer(context, customer_id)
            row = self._connection.execute(
                """
                SELECT * FROM contacts
                WHERE id = ? AND organization_id = ? AND customer_id = ?
                """,
                (contact_id, context.organization_id, customer_id),
            ).fetchone()
            if row is None:
                raise CustomerNotFound("contact not found")
            record = self._contact(row)
            if record.status != "active":
                raise CustomerConflict("contact is already archived")
            updated = self._connection.execute(
                """
                UPDATE contacts SET status = 'archived'
                WHERE id = ? AND organization_id = ? AND customer_id = ? AND status = 'active'
                """,
                (contact_id, context.organization_id, customer_id),
            )
            if updated.rowcount != 1:
                raise CustomerConflict("contact changed before archive")
            self._audit(
                context,
                "contact.archived",
                "contact",
                contact_id,
                {"status": "active"},
                {"status": "archived"},
                correlation_id,
            )
            return replace(record, status="archived")

        return self._owned_write(context, write)

    def _owned_write(
        self,
        context: SecurityContext,
        operation: Callable[[], _Record],
    ) -> _Record:
        self.require_manage(context)
        if self._connection.in_transaction:
            raise TransactionOwnershipError("customer write cannot join an active transaction")
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            self.require_manage(context)
            result = operation()
            self._connection.commit()
            return result
        except Exception:
            self._connection.rollback()
            raise

    def _require_active_customer(self, context: SecurityContext, customer_id: str) -> None:
        row = self._connection.execute(
            """
            SELECT 1 FROM customers
            WHERE id = ? AND organization_id = ? AND status = 'active'
            """,
            (customer_id, context.organization_id),
        ).fetchone()
        if row is None:
            raise CustomerNotFound("customer not found")

    def _require_active_site(
        self,
        context: SecurityContext,
        customer_id: str,
        site_id: str,
    ) -> None:
        row = self._connection.execute(
            """
            SELECT 1 FROM sites
            WHERE id = ? AND organization_id = ? AND customer_id = ? AND status = 'active'
            """,
            (site_id, context.organization_id, customer_id),
        ).fetchone()
        if row is None:
            raise CustomerNotFound("site not found")

    def _audit(
        self,
        context: SecurityContext,
        action: str,
        object_type: str,
        object_id: str,
        before: dict[str, object] | None,
        after: dict[str, object],
        correlation_id: str,
    ) -> None:
        self._connection.execute(
            """
            INSERT INTO audit_events (
                id, organization_id, actor_user_id, action, object_type,
                object_id, before_summary, after_summary, outcome, correlation_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'success', ?)
            """,
            (
                str(uuid.uuid4()),
                context.organization_id,
                context.user_id,
                action,
                object_type,
                object_id,
                None if before is None else self._summary(before),
                self._summary(after),
                correlation_id,
            ),
        )

    @staticmethod
    def _validate_text(value: object, field: str, maximum: int) -> None:
        if not isinstance(value, str) or not value or value != " ".join(value.split()):
            raise ValueError(f"normalized {field} is invalid")
        if len(value) > maximum:
            raise ValueError(f"normalized {field} is too long")

    @staticmethod
    def _summary(value: dict[str, object]) -> str:
        return json.dumps(value, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _customer(row: sqlite3.Row) -> CustomerRecord:
        return CustomerRecord(row["id"], row["organization_id"], row["name"], row["status"])

    @staticmethod
    def _site(row: sqlite3.Row) -> SiteRecord:
        return SiteRecord(
            row["id"], row["organization_id"], row["customer_id"], row["address"], row["status"]
        )

    @staticmethod
    def _contact(row: sqlite3.Row) -> ContactRecord:
        return ContactRecord(
            row["id"],
            row["organization_id"],
            row["customer_id"],
            row["site_id"],
            row["name"],
            row["phone"],
            row["status"],
        )
