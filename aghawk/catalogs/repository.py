from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass, replace
from enum import StrEnum

from turfhelm.security.authority import SecurityContextAuthority
from turfhelm.security.context import SecurityContext
from turfhelm.security.permissions import Action, require_permission


class CatalogConflict(RuntimeError):
    """A catalog value is duplicate or changed since it was selected."""


class CatalogNotFound(RuntimeError):
    """A catalog ID is not visible in the active organization."""


class TransactionOwnershipError(RuntimeError):
    """Catalog writes require a connection without an ambient transaction."""


class CatalogKind(StrEnum):
    VARIETY = "variety"
    PALLET_SIZE = "pallet_size"
    TRANSPORT_OPTION = "transport_option"
    TEAM = "team"
    SERVICE_TYPE = "service_type"


@dataclass(frozen=True, slots=True)
class NamedCatalogRecord:
    id: str
    organization_id: str
    name: str
    status: str


@dataclass(frozen=True, slots=True)
class PalletSizeRecord:
    id: str
    organization_id: str
    size: int
    status: str


@dataclass(frozen=True, slots=True)
class TransportOptionRecord:
    id: str
    organization_id: str
    name: str
    pallet_capacity: int
    status: str


CatalogRecord = NamedCatalogRecord | PalletSizeRecord | TransportOptionRecord


@dataclass(frozen=True, slots=True)
class _CatalogSpec:
    permission: Action
    fields: tuple[str, ...]
    list_sql: str
    insert_sql: str
    select_sql: str
    archive_sql: str
    names_sql: str | None = None


_SPECS = {
    CatalogKind.VARIETY: _CatalogSpec(
        Action.SETTINGS_MANAGE,
        ("name",),
        "SELECT * FROM varieties WHERE organization_id = ? AND status = 'active' "
        "ORDER BY name COLLATE NOCASE",
        "INSERT INTO varieties (id, organization_id, name) VALUES (?, ?, ?)",
        "SELECT * FROM varieties WHERE id = ? AND organization_id = ?",
        "UPDATE varieties SET status = 'archived' "
        "WHERE id = ? AND organization_id = ? AND status = 'active'",
        "SELECT name FROM varieties WHERE organization_id = ?",
    ),
    CatalogKind.PALLET_SIZE: _CatalogSpec(
        Action.SETTINGS_MANAGE,
        ("size",),
        "SELECT * FROM pallet_sizes WHERE organization_id = ? AND status = 'active' ORDER BY size",
        "INSERT INTO pallet_sizes (id, organization_id, size) VALUES (?, ?, ?)",
        "SELECT * FROM pallet_sizes WHERE id = ? AND organization_id = ?",
        "UPDATE pallet_sizes SET status = 'archived' "
        "WHERE id = ? AND organization_id = ? AND status = 'active'",
    ),
    CatalogKind.TRANSPORT_OPTION: _CatalogSpec(
        Action.FLEET_MANAGE,
        ("name", "pallet_capacity"),
        "SELECT * FROM transport_options WHERE organization_id = ? AND status = 'active' "
        "ORDER BY name COLLATE NOCASE",
        "INSERT INTO transport_options "
        "(id, organization_id, name, pallet_capacity) VALUES (?, ?, ?, ?)",
        "SELECT * FROM transport_options WHERE id = ? AND organization_id = ?",
        "UPDATE transport_options SET status = 'archived' "
        "WHERE id = ? AND organization_id = ? AND status = 'active'",
        "SELECT name FROM transport_options WHERE organization_id = ?",
    ),
    CatalogKind.TEAM: _CatalogSpec(
        Action.TEAM_MANAGE,
        ("name",),
        "SELECT * FROM teams WHERE organization_id = ? AND status = 'active' "
        "ORDER BY name COLLATE NOCASE",
        "INSERT INTO teams (id, organization_id, name) VALUES (?, ?, ?)",
        "SELECT * FROM teams WHERE id = ? AND organization_id = ?",
        "UPDATE teams SET status = 'archived' "
        "WHERE id = ? AND organization_id = ? AND status = 'active'",
        "SELECT name FROM teams WHERE organization_id = ?",
    ),
    CatalogKind.SERVICE_TYPE: _CatalogSpec(
        Action.SETTINGS_MANAGE,
        ("name",),
        "SELECT * FROM service_types WHERE organization_id = ? AND status = 'active' "
        "ORDER BY name COLLATE NOCASE",
        "INSERT INTO service_types (id, organization_id, name) VALUES (?, ?, ?)",
        "SELECT * FROM service_types WHERE id = ? AND organization_id = ?",
        "UPDATE service_types SET status = 'archived' "
        "WHERE id = ? AND organization_id = ? AND status = 'active'",
        "SELECT name FROM service_types WHERE organization_id = ?",
    ),
}


class CatalogRepository:
    """Tenant-scoped catalog persistence with owned atomic audit writes."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        authority: SecurityContextAuthority,
    ) -> None:
        self._connection = connection
        self._authority = authority

    def require_manage(self, context: SecurityContext, kind: CatalogKind) -> None:
        self._authority.require_active(self._connection, context)
        require_permission(context.role, _SPECS[kind].permission)

    def list_active(self, context: SecurityContext, kind: CatalogKind) -> list[CatalogRecord]:
        self._authority.require_active(self._connection, context)
        spec = _SPECS[kind]
        rows = self._connection.execute(spec.list_sql, (context.organization_id,)).fetchall()
        return [self._record(kind, row) for row in rows]

    def create(
        self,
        context: SecurityContext,
        kind: CatalogKind,
        values: dict[str, object],
        *,
        correlation_id: str,
    ) -> CatalogRecord:
        self.require_manage(context, kind)
        self._reject_ambient_transaction()
        record_id = str(uuid.uuid4())
        event_id = str(uuid.uuid4())
        spec = _SPECS[kind]
        if tuple(values) != spec.fields:
            raise ValueError("unexpected catalog fields")
        self._validate_values(kind, values)
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            self.require_manage(context, kind)
            self._reject_duplicate(context, kind, values)
            self._connection.execute(
                spec.insert_sql,
                (
                    record_id,
                    context.organization_id,
                    *(values[column] for column in spec.fields),
                ),
            )
            self._insert_audit(
                event_id=event_id,
                context=context,
                action=f"catalog.{kind.value}.created",
                object_type=kind.value,
                object_id=record_id,
                before=None,
                after={**values, "status": "active"},
                correlation_id=correlation_id,
            )
            row = self._connection.execute(
                spec.select_sql, (record_id, context.organization_id)
            ).fetchone()
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise
        return self._record(kind, row)

    def archive(
        self,
        context: SecurityContext,
        kind: CatalogKind,
        record_id: str,
        *,
        correlation_id: str,
    ) -> CatalogRecord:
        self.require_manage(context, kind)
        self._reject_ambient_transaction()
        event_id = str(uuid.uuid4())
        spec = _SPECS[kind]
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            self.require_manage(context, kind)
            row = self._connection.execute(
                spec.select_sql, (record_id, context.organization_id)
            ).fetchone()
            if row is None:
                raise CatalogNotFound("catalog value not found")
            record = self._record(kind, row)
            if record.status == "archived":
                raise CatalogConflict("catalog value is already archived")
            updated = self._connection.execute(
                spec.archive_sql, (record_id, context.organization_id)
            )
            if updated.rowcount != 1:
                raise CatalogConflict("catalog value changed before archive")
            self._insert_audit(
                event_id=event_id,
                context=context,
                action=f"catalog.{kind.value}.archived",
                object_type=kind.value,
                object_id=record_id,
                before={"status": "active"},
                after={"status": "archived"},
                correlation_id=correlation_id,
            )
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise
        return replace(record, status="archived")

    def _reject_ambient_transaction(self) -> None:
        if self._connection.in_transaction:
            raise TransactionOwnershipError("catalog write cannot join an active transaction")

    @staticmethod
    def _validate_values(kind: CatalogKind, values: dict[str, object]) -> None:
        if kind is CatalogKind.PALLET_SIZE:
            size = values["size"]
            if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
                raise ValueError("pallet size must be a positive integer")
            return

        name = values["name"]
        if not isinstance(name, str):
            raise ValueError("normalized name must be text")
        if not name or name != " ".join(name.split()) or len(name) > 100:
            raise ValueError("normalized name must contain between 1 and 100 characters")
        if kind is CatalogKind.TRANSPORT_OPTION:
            capacity = values["pallet_capacity"]
            if isinstance(capacity, bool) or not isinstance(capacity, int) or capacity < 0:
                raise ValueError("pallet capacity must be a non-negative integer")

    def _reject_duplicate(
        self,
        context: SecurityContext,
        kind: CatalogKind,
        values: dict[str, object],
    ) -> None:
        spec = _SPECS[kind]
        if kind is CatalogKind.PALLET_SIZE:
            duplicate = self._connection.execute(
                """
                SELECT 1 FROM pallet_sizes
                WHERE organization_id = ? AND size = ?
                """,
                (context.organization_id, values["size"]),
            ).fetchone()
        else:
            if spec.names_sql is None:
                raise RuntimeError("named catalog query is missing")
            rows = self._connection.execute(
                spec.names_sql, (context.organization_id,)
            ).fetchall()
            wanted = str(values["name"]).casefold()
            duplicate = next((row for row in rows if row["name"].casefold() == wanted), None)
        if duplicate is not None:
            raise CatalogConflict("catalog value already exists")

    def _insert_audit(
        self,
        *,
        event_id: str,
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
                event_id,
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
    def _summary(value: dict[str, object]) -> str:
        return json.dumps(value, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _record(kind: CatalogKind, row: sqlite3.Row) -> CatalogRecord:
        common = {
            "id": row["id"],
            "organization_id": row["organization_id"],
            "status": row["status"],
        }
        if kind is CatalogKind.PALLET_SIZE:
            return PalletSizeRecord(size=row["size"], **common)
        if kind is CatalogKind.TRANSPORT_OPTION:
            return TransportOptionRecord(
                name=row["name"], pallet_capacity=row["pallet_capacity"], **common
            )
        return NamedCatalogRecord(name=row["name"], **common)
