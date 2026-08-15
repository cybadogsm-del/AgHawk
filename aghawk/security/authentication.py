from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol


class AuthenticationRequired(PermissionError):
    """No authenticated identity is present."""


class InvalidIdentity(PermissionError):
    """Authenticated identity claims are missing or malformed."""


class ExpiredIdentity(PermissionError):
    """The authenticated identity has expired."""


class StreamlitUser(Protocol):
    is_logged_in: bool

    def get(self, key: str, default: object = None) -> object: ...


@dataclass(frozen=True, slots=True)
class AuthenticatedPrincipal:
    oidc_subject: str
    expires_at: datetime


def principal_from_streamlit_user(
    user: StreamlitUser | Mapping[str, object],
    *,
    now: datetime,
) -> AuthenticatedPrincipal:
    """Extract minimal trusted claims from Streamlit's verified OIDC user."""

    if not getattr(user, "is_logged_in", False):
        raise AuthenticationRequired("login is required")

    subject = user.get("sub")
    if not isinstance(subject, str) or not subject.strip():
        raise InvalidIdentity("identity subject is missing or invalid")

    expiry = user.get("exp")
    if isinstance(expiry, bool) or not isinstance(expiry, (int, float)):
        raise InvalidIdentity("identity expiry is missing or invalid")
    try:
        expires_at = datetime.fromtimestamp(expiry, tz=UTC)
    except (OverflowError, OSError, ValueError) as error:
        raise InvalidIdentity("identity expiry is missing or invalid") from error

    if now.tzinfo is None:
        raise ValueError("current time must include a timezone")
    if expires_at <= now.astimezone(UTC):
        raise ExpiredIdentity("identity has expired")

    return AuthenticatedPrincipal(
        oidc_subject=subject.strip(),
        expires_at=expires_at,
    )
