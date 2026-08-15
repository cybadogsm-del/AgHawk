from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3

from turfhelm.security.authentication import AuthenticatedPrincipal
from turfhelm.security.context import Role, SecurityContext


class SecurityContextAuthority:
    """Resolve and verify authorization context using a secret HMAC seal."""

    def __init__(self, *, signing_key: bytes) -> None:
        if len(signing_key) < 32:
            raise ValueError("context signing key must contain at least 32 bytes")
        self.__signing_key = signing_key

    def resolve(
        self,
        connection: sqlite3.Connection,
        *,
        principal: AuthenticatedPrincipal,
        organization_id: str,
    ) -> SecurityContext:
        """Resolve a context from the OIDC subject authenticated by Streamlit."""

        row = connection.execute(
            """
            SELECT users.id AS user_id,
                   users.oidc_subject,
                   organization_memberships.organization_id,
                   organization_memberships.role
            FROM users
            JOIN organization_memberships
              ON organization_memberships.user_id = users.id
            JOIN organizations
              ON organizations.id = organization_memberships.organization_id
            WHERE users.oidc_subject = ?
              AND organization_memberships.organization_id = ?
              AND users.status = 'active'
              AND organization_memberships.status = 'active'
              AND organizations.status = 'active'
            """,
            (principal.oidc_subject, organization_id),
        ).fetchone()
        if row is None:
            raise PermissionError("identity has no active organization membership")

        role = Role(row["role"])
        proof = self.__proof(
            user_id=row["user_id"],
            oidc_subject=row["oidc_subject"],
            organization_id=row["organization_id"],
            role=role,
        )
        return SecurityContext._from_active_membership(
            user_id=row["user_id"],
            oidc_subject=row["oidc_subject"],
            organization_id=row["organization_id"],
            role=role,
            proof=proof,
        )

    def require_active(
        self,
        connection: sqlite3.Connection,
        context: SecurityContext,
    ) -> None:
        """Verify the seal and recheck current identity, membership, and role."""

        expected_proof = self.__proof(
            user_id=context.user_id,
            oidc_subject=context.oidc_subject,
            organization_id=context.organization_id,
            role=context.role,
        )
        if not hmac.compare_digest(context.proof, expected_proof):
            raise PermissionError("security context proof is invalid")

        active = connection.execute(
            """
            SELECT 1
            FROM users
            JOIN organization_memberships
              ON organization_memberships.user_id = users.id
            JOIN organizations
              ON organizations.id = organization_memberships.organization_id
            WHERE users.id = ?
              AND users.oidc_subject = ?
              AND organization_memberships.organization_id = ?
              AND organization_memberships.role = ?
              AND users.status = 'active'
              AND organization_memberships.status = 'active'
              AND organizations.status = 'active'
            """,
            (
                context.user_id,
                context.oidc_subject,
                context.organization_id,
                context.role.value,
            ),
        ).fetchone()
        if active is None:
            raise PermissionError("security context is no longer active")

    def __proof(
        self,
        *,
        user_id: str,
        oidc_subject: str,
        organization_id: str,
        role: Role,
    ) -> bytes:
        message = json.dumps(
            [user_id, oidc_subject, organization_id, role.value],
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        return hmac.new(self.__signing_key, message, hashlib.sha256).digest()
