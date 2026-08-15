from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import date

from turfhelm.security.authority import SecurityContextAuthority
from turfhelm.security.context import Role, SecurityContext
from turfhelm.security.permissions import Action, require_permission

_ASSIGNMENT_SCOPED_ROLES = frozenset(
    {Role.SITE_SUPERVISOR, Role.DRIVER, Role.INSTALLER}
)
_MAXIMUM_EXPECTED_VERSION = 9_223_372_036_854_775_806


@dataclass(frozen=True, slots=True)
class OrderRecord:
    id: str
    organization_id: str
    status: str
    m2_area: int


@dataclass(frozen=True, slots=True)
class CreateOrderInput:
    customer_id: str
    site_id: str
    site_contact_id: str | None
    service_type_id: str
    variety_id: str
    pallet_size_id: str
    transport_option_id: str | None
    team_id: str | None
    purchase_order: str
    special_instructions: str
    parking_pin: str
    m2_area: int
    harvest_date: str | None
    install_date: str | None


class OrderSelectionNotFound(RuntimeError):
    """One or more selected IDs are not active in the organization."""


class OrderConflict(RuntimeError):
    """The order could not be safely persisted."""


class TransactionOwnershipError(RuntimeError):
    """Order creation requires a connection without an ambient transaction."""


class OrderRepository:
    def __init__(
        self,
        connection: sqlite3.Connection,
        authority: SecurityContextAuthority,
    ) -> None:
        self._connection = connection
        self._authority = authority

    def create(
        self,
        context: SecurityContext,
        values: CreateOrderInput,
        *,
        correlation_id: str,
    ) -> OrderRecord:
        self._authority.require_active(self._connection, context)
        require_permission(context.role, Action.ORDER_CREATE)
        self._validate_create_input(values, correlation_id)
        if self._connection.in_transaction:
            raise TransactionOwnershipError("order write cannot join an active transaction")

        order_id = str(uuid.uuid4())
        audit_id = str(uuid.uuid4())
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            # Authorization and every selected relationship are checked after taking
            # the write lock so revocation/archive races cannot cross this boundary.
            self._authority.require_active(self._connection, context)
            require_permission(context.role, Action.ORDER_CREATE)
            selected = self._active_selections(context, values)
            if selected is None:
                raise OrderSelectionNotFound("one or more order selections are unavailable")

            full_pallets, loose_rolls = divmod(values.m2_area, selected["pallet_size"])
            status = "scheduled" if values.harvest_date is not None else "pending"
            self._connection.execute(
                """
                INSERT INTO orders (
                    id, organization_id, customer_id, site_id, site_contact_id,
                    purchase_order, special_instructions, service_type,
                    transport_option_id, team_id, parking_pin, variety_id,
                    m2_area, pallet_size, full_pallets, loose_rolls,
                    harvest_date, install_date, status, remaining_balance
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    order_id,
                    context.organization_id,
                    values.customer_id,
                    values.site_id,
                    values.site_contact_id,
                    values.purchase_order,
                    values.special_instructions,
                    selected["service_type"],
                    values.transport_option_id,
                    values.team_id,
                    values.parking_pin,
                    values.variety_id,
                    values.m2_area,
                    selected["pallet_size"],
                    full_pallets,
                    loose_rolls,
                    values.harvest_date,
                    values.install_date,
                    status,
                    values.m2_area,
                ),
            )
            self._connection.execute(
                """
                INSERT INTO order_catalog_references (
                    order_id, organization_id, service_type_id, pallet_size_id
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    order_id,
                    context.organization_id,
                    values.service_type_id,
                    values.pallet_size_id,
                ),
            )
            after = json.dumps(
                {
                    "customer_id": values.customer_id,
                    "m2_area": values.m2_area,
                    "pallet_size_id": values.pallet_size_id,
                    "service_type_id": values.service_type_id,
                    "site_id": values.site_id,
                    "status": status,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            self._connection.execute(
                """
                INSERT INTO audit_events (
                    id, organization_id, actor_user_id, action, object_type,
                    object_id, before_summary, after_summary, outcome, correlation_id
                ) VALUES (?, ?, ?, 'order.created', 'order', ?, NULL, ?, 'success', ?)
                """,
                (
                    audit_id,
                    context.organization_id,
                    context.user_id,
                    order_id,
                    after,
                    correlation_id,
                ),
            )
            self._connection.commit()
        except sqlite3.IntegrityError:
            self._connection.rollback()
            raise OrderConflict("order could not be created") from None
        except Exception:
            self._connection.rollback()
            raise

        return OrderRecord(order_id, context.organization_id, status, values.m2_area)

    def _active_selections(
        self,
        context: SecurityContext,
        values: CreateOrderInput,
    ) -> sqlite3.Row | None:
        return self._connection.execute(
            """
            SELECT service_types.name AS service_type, pallet_sizes.size AS pallet_size
            FROM customers
            JOIN sites
              ON sites.organization_id = customers.organization_id
             AND sites.customer_id = customers.id
             AND sites.id = ?
             AND sites.status = 'active'
            JOIN service_types
              ON service_types.organization_id = customers.organization_id
             AND service_types.id = ?
             AND service_types.status = 'active'
            JOIN varieties
              ON varieties.organization_id = customers.organization_id
             AND varieties.id = ?
             AND varieties.status = 'active'
            JOIN pallet_sizes
              ON pallet_sizes.organization_id = customers.organization_id
             AND pallet_sizes.id = ?
             AND pallet_sizes.status = 'active'
            LEFT JOIN contacts
              ON contacts.organization_id = customers.organization_id
             AND contacts.customer_id = customers.id
             AND contacts.site_id = sites.id
             AND contacts.id = ?
             AND contacts.status = 'active'
            LEFT JOIN transport_options
              ON transport_options.organization_id = customers.organization_id
             AND transport_options.id = ?
             AND transport_options.status = 'active'
            LEFT JOIN teams
              ON teams.organization_id = customers.organization_id
             AND teams.id = ?
             AND teams.status = 'active'
            WHERE customers.id = ?
              AND customers.organization_id = ?
              AND customers.status = 'active'
              AND (? IS NULL OR contacts.id IS NOT NULL)
              AND (? IS NULL OR transport_options.id IS NOT NULL)
              AND (? IS NULL OR teams.id IS NOT NULL)
            """,
            (
                values.site_id,
                values.service_type_id,
                values.variety_id,
                values.pallet_size_id,
                values.site_contact_id,
                values.transport_option_id,
                values.team_id,
                values.customer_id,
                context.organization_id,
                values.site_contact_id,
                values.transport_option_id,
                values.team_id,
            ),
        ).fetchone()

    @classmethod
    def _validate_create_input(cls, values: CreateOrderInput, correlation_id: str) -> None:
        for field in (
            "customer_id",
            "site_id",
            "service_type_id",
            "variety_id",
            "pallet_size_id",
        ):
            cls._validate_text(getattr(values, field), field, 100, allow_empty=False)
        for field in ("site_contact_id", "transport_option_id", "team_id"):
            value = getattr(values, field)
            if value is not None:
                cls._validate_text(value, field, 100, allow_empty=False)
        cls._validate_text(values.purchase_order, "purchase_order", 100, allow_empty=True)
        cls._validate_text(
            values.special_instructions, "special_instructions", 2000, allow_empty=True
        )
        cls._validate_text(values.parking_pin, "parking_pin", 500, allow_empty=True)
        cls._validate_text(correlation_id, "correlation_id", 100, allow_empty=False)
        if isinstance(values.m2_area, bool) or not isinstance(values.m2_area, int):
            raise ValueError("m2_area must be a positive integer")
        if values.m2_area <= 0:
            raise ValueError("m2_area must be a positive integer")
        if values.m2_area > 9_223_372_036_854_775_807:
            raise ValueError("m2_area exceeds SQLite integer maximum")
        if (values.harvest_date is None) != (values.install_date is None):
            raise ValueError("harvest and install dates must both be present or absent")
        if values.harvest_date is not None and values.install_date is not None:
            harvest = cls._iso_date(values.harvest_date, "harvest_date")
            install = cls._iso_date(values.install_date, "install_date")
            if harvest > install:
                raise ValueError("harvest_date must not be after install_date")

    @staticmethod
    def _validate_text(
        value: object,
        field: str,
        maximum: int,
        *,
        allow_empty: bool,
    ) -> None:
        if not isinstance(value, str) or value != " ".join(value.split()):
            raise ValueError(f"normalized {field} is invalid")
        if (not allow_empty and not value) or len(value) > maximum:
            raise ValueError(f"normalized {field} is invalid")

    @staticmethod
    def _iso_date(value: object, field: str) -> date:
        if not isinstance(value, str):
            raise ValueError(f"{field} must be an ISO date")
        try:
            parsed = date.fromisoformat(value)
        except ValueError:
            raise ValueError(f"{field} must be an ISO date") from None
        if parsed.isoformat() != value:
            raise ValueError(f"{field} must be an ISO date")
        return parsed

    def get_by_id(self, context: SecurityContext, order_id: str) -> OrderRecord | None:
        self._authority.require_active(self._connection, context)
        require_permission(context.role, Action.ORDER_READ)
        if context.role in _ASSIGNMENT_SCOPED_ROLES:
            row = self._connection.execute(
                """
                SELECT orders.id, orders.organization_id, orders.status, orders.m2_area
                FROM orders
                WHERE orders.id = ?
                  AND orders.organization_id = ?
                  AND (
                      EXISTS (
                          SELECT 1
                          FROM order_assignments
                          WHERE order_assignments.order_id = orders.id
                            AND order_assignments.organization_id = orders.organization_id
                            AND order_assignments.user_id = ?
                            AND order_assignments.assignment_role = ?
                            AND order_assignments.status = 'active'
                      )
                      OR EXISTS (
                          SELECT 1
                          FROM team_memberships
                          WHERE team_memberships.team_id = orders.team_id
                            AND team_memberships.organization_id = orders.organization_id
                            AND team_memberships.user_id = ?
                            AND team_memberships.membership_role = ?
                            AND team_memberships.status = 'active'
                      )
                  )
                """,
                (
                    order_id,
                    context.organization_id,
                    context.user_id,
                    context.role.value,
                    context.user_id,
                    context.role.value,
                ),
            ).fetchone()
        else:
            row = self._connection.execute(
                """
                SELECT id, organization_id, status, m2_area
                FROM orders
                WHERE id = ? AND organization_id = ?
                """,
                (order_id, context.organization_id),
            ).fetchone()
        if row is None:
            return None
        return OrderRecord(
            id=row["id"],
            organization_id=row["organization_id"],
            status=row["status"],
            m2_area=row["m2_area"],
        )

    def update_status(
        self,
        context: SecurityContext,
        order_id: str,
        status: str,
        *,
        expected_version: int,
        correlation_id: str,
    ) -> bool:
        self._authority.require_active(self._connection, context)
        require_permission(context.role, Action.ORDER_CANCEL)
        self._validate_text(order_id, "order_id", 100, allow_empty=False)
        self._validate_text(correlation_id, "correlation_id", 100, allow_empty=False)
        if status != "cancelled":
            raise ValueError("target status is invalid")
        if (
            isinstance(expected_version, bool)
            or not isinstance(expected_version, int)
            or expected_version <= 0
            or expected_version > _MAXIMUM_EXPECTED_VERSION
        ):
            raise ValueError("expected_version must be a bounded positive integer")
        if self._connection.in_transaction:
            raise TransactionOwnershipError("order write cannot join an active transaction")

        self._connection.execute("BEGIN IMMEDIATE")
        try:
            self._authority.require_active(self._connection, context)
            require_permission(context.role, Action.ORDER_CANCEL)
            row = self._connection.execute(
                """
                SELECT status, version
                FROM orders
                WHERE id = ? AND organization_id = ? AND version = ?
                """,
                (order_id, context.organization_id, expected_version),
            ).fetchone()
            if row is None or row["status"] not in {"pending", "scheduled"}:
                raise OrderConflict("order status update conflict")

            next_version = expected_version + 1
            cursor = self._connection.execute(
                """
                UPDATE orders
                SET status = ?, version = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND organization_id = ? AND version = ?
                  AND status IN ('pending', 'scheduled')
                """,
                (
                    status,
                    next_version,
                    order_id,
                    context.organization_id,
                    expected_version,
                ),
            )
            if cursor.rowcount != 1:
                raise OrderConflict("order status update conflict")

            before = json.dumps(
                {"status": row["status"], "version": expected_version},
                sort_keys=True,
                separators=(",", ":"),
            )
            after = json.dumps(
                {"status": status, "version": next_version},
                sort_keys=True,
                separators=(",", ":"),
            )
            self._connection.execute(
                """
                INSERT INTO audit_events (
                    id, organization_id, actor_user_id, action, object_type,
                    object_id, before_summary, after_summary, outcome, correlation_id
                ) VALUES (?, ?, ?, 'order.status.updated', 'order', ?, ?, ?, 'success', ?)
                """,
                (
                    str(uuid.uuid4()),
                    context.organization_id,
                    context.user_id,
                    order_id,
                    before,
                    after,
                    correlation_id,
                ),
            )
            self._connection.commit()
            return True
        except sqlite3.IntegrityError:
            self._connection.rollback()
            raise OrderConflict("order status update conflict") from None
        except Exception:
            self._connection.rollback()
            raise
