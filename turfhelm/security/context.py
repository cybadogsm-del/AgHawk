from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class Role(StrEnum):
    ADMIN = "admin"
    FARM_STAFF = "farm_staff"
    SITE_SUPERVISOR = "site_supervisor"
    DRIVER = "driver"
    INSTALLER = "installer"


@dataclass(frozen=True, slots=True, init=False)
class SecurityContext:
    """Authorization values sealed by the trusted context authority."""

    user_id: str
    oidc_subject: str
    organization_id: str
    role: Role
    proof: bytes = field(repr=False)

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("SecurityContext must be resolved from trusted persistence")

    @classmethod
    def _from_active_membership(
        cls,
        *,
        user_id: str,
        oidc_subject: str,
        organization_id: str,
        role: Role,
        proof: bytes,
    ) -> SecurityContext:
        context = object.__new__(cls)
        object.__setattr__(context, "user_id", user_id)
        object.__setattr__(context, "oidc_subject", oidc_subject)
        object.__setattr__(context, "organization_id", organization_id)
        object.__setattr__(context, "role", role)
        object.__setattr__(context, "proof", proof)
        return context
