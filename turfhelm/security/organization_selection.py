from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from turfhelm.security.authentication import AuthenticatedPrincipal
from turfhelm.security.authority import SecurityContextAuthority
from turfhelm.security.context import Role, SecurityContext


@dataclass(frozen=True, slots=True)
class OrganizationMembershipChoice:
    organization_id: str
    display_name: str
    role: Role


class OrganizationSelectionService:
    """List selectable organizations from authoritative active memberships."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def list_for(
        self,
        principal: AuthenticatedPrincipal,
    ) -> tuple[OrganizationMembershipChoice, ...]:
        rows = self._connection.execute(
            """
            SELECT organization_memberships.organization_id,
                   organizations.name AS display_name,
                   organization_memberships.role
            FROM users
            JOIN organization_memberships
              ON organization_memberships.user_id = users.id
            JOIN organizations
              ON organizations.id = organization_memberships.organization_id
            WHERE users.oidc_subject = ?
              AND users.status = 'active'
              AND organization_memberships.status = 'active'
              AND organizations.status = 'active'
            ORDER BY organizations.name COLLATE NOCASE,
                     organization_memberships.organization_id
            """,
            (principal.oidc_subject,),
        ).fetchall()
        return tuple(
            OrganizationMembershipChoice(
                organization_id=row["organization_id"],
                display_name=row["display_name"],
                role=Role(row["role"]),
            )
            for row in rows
        )

    def resolve_selected(
        self,
        principal: AuthenticatedPrincipal,
        *,
        selected_organization_id: str,
        authority: SecurityContextAuthority,
    ) -> SecurityContext:
        """Validate a persisted choice before resolving its security context."""

        available_ids = {choice.organization_id for choice in self.list_for(principal)}
        if selected_organization_id not in available_ids:
            raise PermissionError("organization selection is not available")
        return authority.resolve(
            self._connection,
            principal=principal,
            organization_id=selected_organization_id,
        )
