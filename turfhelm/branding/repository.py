from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass

from turfhelm.branding.images import ValidatedImage
from turfhelm.security.authority import SecurityContextAuthority
from turfhelm.security.context import SecurityContext
from turfhelm.security.permissions import Action, require_permission


class VersionConflict(RuntimeError):
    """Branding changed after the caller loaded its optimistic version."""


class TransactionOwnershipError(RuntimeError):
    """Branding writes require a connection without an ambient transaction."""


@dataclass(frozen=True, slots=True)
class BrandAsset:
    id: str
    organization_id: str
    content_type: str
    byte_size: int
    width: int
    height: int
    sha256: str
    canonical_bytes: bytes
    status: str


@dataclass(frozen=True, slots=True)
class OrganizationBranding:
    organization_id: str
    version: int
    asset: BrandAsset | None


class BrandingRepository:
    """Organization-scoped persistence boundary for branding and local blobs."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        authority: SecurityContextAuthority,
    ) -> None:
        self._connection = connection
        self._authority = authority

    def require_manage(self, context: SecurityContext) -> None:
        """Authorize a mutation before potentially expensive image decoding."""

        self._authority.require_active(self._connection, context)
        require_permission(context.role, Action.SETTINGS_MANAGE)

    def get_active(self, context: SecurityContext) -> OrganizationBranding:
        self._authority.require_active(self._connection, context)
        row = self._connection.execute(
            """
            SELECT branding.organization_id, branding.version,
                   assets.id AS asset_id, assets.content_type, assets.byte_size,
                   assets.width, assets.height, assets.sha256,
                   assets.canonical_bytes, assets.status
            FROM organization_branding AS branding
            LEFT JOIN brand_assets AS assets
              ON assets.id = branding.active_asset_id
             AND assets.organization_id = branding.organization_id
             AND assets.status = 'active'
            WHERE branding.organization_id = ?
            """,
            (context.organization_id,),
        ).fetchone()
        if row is None:
            raise RuntimeError("organization branding record is missing")
        return OrganizationBranding(
            organization_id=row["organization_id"],
            version=row["version"],
            asset=self._asset_from_row(row),
        )

    def get_asset(self, context: SecurityContext, asset_id: str) -> BrandAsset | None:
        self._authority.require_active(self._connection, context)
        row = self._connection.execute(
            """
            SELECT id AS asset_id, organization_id, content_type, byte_size,
                   width, height, sha256, canonical_bytes, status
            FROM brand_assets
            WHERE id = ? AND organization_id = ?
            """,
            (asset_id, context.organization_id),
        ).fetchone()
        return None if row is None else self._asset_from_row(row)

    def replace(
        self,
        context: SecurityContext,
        image: ValidatedImage,
        *,
        expected_version: int,
        correlation_id: str,
    ) -> OrganizationBranding:
        self._authority.require_active(self._connection, context)
        require_permission(context.role, Action.SETTINGS_MANAGE)
        asset_id = uuid.uuid4().hex
        event_id = uuid.uuid4().hex
        if self._connection.in_transaction:
            raise TransactionOwnershipError("branding write cannot join an active transaction")
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            self._authority.require_active(self._connection, context)
            require_permission(context.role, Action.SETTINGS_MANAGE)
            previous_asset_id = self._require_version(context, expected_version)
            self._connection.execute(
                """
                INSERT INTO brand_assets (
                    id, organization_id, content_type, byte_size, width, height,
                    sha256, canonical_bytes, uploaded_by_user_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    asset_id,
                    context.organization_id,
                    image.content_type,
                    image.byte_size,
                    image.width,
                    image.height,
                    image.sha256,
                    image.data,
                    context.user_id,
                ),
            )
            updated = self._connection.execute(
                """
                UPDATE organization_branding
                SET active_asset_id = ?, version = version + 1,
                    updated_by_user_id = ?, updated_at = CURRENT_TIMESTAMP
                WHERE organization_id = ? AND version = ?
                """,
                (asset_id, context.user_id, context.organization_id, expected_version),
            )
            if updated.rowcount != 1:
                raise VersionConflict("branding version conflict")
            self._archive(context.organization_id, previous_asset_id)
            self._insert_audit(
                event_id=event_id,
                context=context,
                action="branding.logo.replaced",
                object_id=asset_id,
                before={"active_asset_id": previous_asset_id, "version": expected_version},
                after={"active_asset_id": asset_id, "version": expected_version + 1},
                correlation_id=correlation_id,
            )
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise
        return self.get_active(context)

    def reset(
        self,
        context: SecurityContext,
        *,
        expected_version: int,
        correlation_id: str,
    ) -> OrganizationBranding:
        self._authority.require_active(self._connection, context)
        require_permission(context.role, Action.SETTINGS_MANAGE)
        event_id = uuid.uuid4().hex
        if self._connection.in_transaction:
            raise TransactionOwnershipError("branding write cannot join an active transaction")
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            self._authority.require_active(self._connection, context)
            require_permission(context.role, Action.SETTINGS_MANAGE)
            previous_asset_id = self._require_version(context, expected_version)
            updated = self._connection.execute(
                """
                UPDATE organization_branding
                SET active_asset_id = NULL, version = version + 1,
                    updated_by_user_id = ?, updated_at = CURRENT_TIMESTAMP
                WHERE organization_id = ? AND version = ?
                """,
                (context.user_id, context.organization_id, expected_version),
            )
            if updated.rowcount != 1:
                raise VersionConflict("branding version conflict")
            self._archive(context.organization_id, previous_asset_id)
            self._insert_audit(
                event_id=event_id,
                context=context,
                action="branding.logo.reset",
                object_id=previous_asset_id or context.organization_id,
                before={"active_asset_id": previous_asset_id, "version": expected_version},
                after={"active_asset_id": None, "version": expected_version + 1},
                correlation_id=correlation_id,
            )
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise
        return self.get_active(context)

    def _require_version(self, context: SecurityContext, expected_version: int) -> str | None:
        row = self._connection.execute(
            """
            SELECT active_asset_id FROM organization_branding
            WHERE organization_id = ? AND version = ?
            """,
            (context.organization_id, expected_version),
        ).fetchone()
        if row is None:
            raise VersionConflict("branding version conflict")
        return row["active_asset_id"]

    def _archive(self, organization_id: str, asset_id: str | None) -> None:
        if asset_id is not None:
            self._connection.execute(
                """
                UPDATE brand_assets
                SET status = 'archived', archived_at = CURRENT_TIMESTAMP
                WHERE id = ? AND organization_id = ? AND status = 'active'
                """,
                (asset_id, organization_id),
            )

    def _insert_audit(
        self,
        *,
        event_id: str,
        context: SecurityContext,
        action: str,
        object_id: str,
        before: dict[str, object],
        after: dict[str, object],
        correlation_id: str,
    ) -> None:
        self._connection.execute(
            """
            INSERT INTO audit_events (
                id, organization_id, actor_user_id, action, object_type,
                object_id, before_summary, after_summary, outcome, correlation_id
            ) VALUES (?, ?, ?, ?, 'organization_branding', ?, ?, ?, 'success', ?)
            """,
            (
                event_id,
                context.organization_id,
                context.user_id,
                action,
                object_id,
                json.dumps(before, sort_keys=True, separators=(",", ":")),
                json.dumps(after, sort_keys=True, separators=(",", ":")),
                correlation_id,
            ),
        )

    @staticmethod
    def _asset_from_row(row: sqlite3.Row) -> BrandAsset | None:
        if row["asset_id"] is None:
            return None
        return BrandAsset(
            id=row["asset_id"],
            organization_id=row["organization_id"],
            content_type=row["content_type"],
            byte_size=row["byte_size"],
            width=row["width"],
            height=row["height"],
            sha256=row["sha256"],
            canonical_bytes=row["canonical_bytes"],
            status=row["status"],
        )
