from __future__ import annotations

import sqlite3
from collections.abc import MutableMapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from turfhelm.security.authentication import AuthenticatedPrincipal
from turfhelm.security.authority import SecurityContextAuthority
from turfhelm.security.context import Role, SecurityContext

ADMIN_IDLE_LIMIT = timedelta(minutes=30)
ADMIN_ABSOLUTE_LIMIT = timedelta(hours=8)
WORKER_IDLE_LIMIT = timedelta(hours=2)
WORKER_ABSOLUTE_LIMIT = timedelta(hours=12)

SENSITIVE_SESSION_KEYS = {
    "security_context",
    "authenticated_principal",
    "session_record",
    "selected_organization_id",
    "editing_order",
    "run_date",
    "logged_in",
    "current_user",
    "user_role",
}


class IdentityTokenExpired(PermissionError):
    """The identity provider's verified token has expired."""


class IdleSessionExpired(PermissionError):
    """The user has been inactive longer than the role allows."""


class AbsoluteSessionExpired(PermissionError):
    """The session has exceeded its maximum lifetime."""


class SessionClockInvalid(PermissionError):
    """Server time moved behind an accepted session timestamp."""


@dataclass(frozen=True, slots=True)
class SessionRecord:
    oidc_subject: str
    organization_id: str
    started_at: datetime
    last_activity_at: datetime

    def __post_init__(self) -> None:
        if not self.oidc_subject.strip():
            raise ValueError("session subject must be non-empty")
        if not self.organization_id.strip():
            raise ValueError("session organization must be non-empty")
        _require_aware(self.started_at, "session start")
        _require_aware(self.last_activity_at, "last activity")
        if self.last_activity_at < self.started_at:
            raise ValueError("last activity cannot precede session start")


def require_valid_session(
    *,
    connection: sqlite3.Connection,
    authority: SecurityContextAuthority,
    principal: AuthenticatedPrincipal,
    context: SecurityContext,
    session: SessionRecord,
    now: datetime,
) -> None:
    """Fail closed when identity or accepted TurfHelm session time has ended."""

    authority.require_active(connection, context)
    _require_aware(now, "current time")
    if now < session.started_at or now < session.last_activity_at:
        raise SessionClockInvalid("session clock moved backward")
    if not (
        principal.oidc_subject == context.oidc_subject == session.oidc_subject
    ):
        raise PermissionError("session identity does not match authenticated principal")
    if session.organization_id != context.organization_id:
        raise PermissionError("session organization does not match security context")
    if principal.expires_at <= now:
        raise IdentityTokenExpired("identity token has expired")

    idle_limit, absolute_limit = _limits(context.role)
    if now - session.last_activity_at > idle_limit:
        raise IdleSessionExpired("session has exceeded its idle limit")
    if now - session.started_at > absolute_limit:
        raise AbsoluteSessionExpired("session has exceeded its absolute limit")


def refresh_session_activity(session: SessionRecord, *, now: datetime) -> SessionRecord:
    """Refresh idle activity without extending the absolute session start."""

    _require_aware(now, "current time")
    if now < session.last_activity_at:
        raise ValueError("current time cannot precede last activity")
    return replace(session, last_activity_at=now)


def clear_sensitive_session_state(state: MutableMapping[str, object]) -> None:
    """Remove identity, organization, and order data during logout."""

    for key in SENSITIVE_SESSION_KEYS:
        state.pop(key, None)


def _limits(role: Role) -> tuple[timedelta, timedelta]:
    if role is Role.ADMIN:
        return ADMIN_IDLE_LIMIT, ADMIN_ABSOLUTE_LIMIT
    return WORKER_IDLE_LIMIT, WORKER_ABSOLUTE_LIMIT


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must include a timezone")
