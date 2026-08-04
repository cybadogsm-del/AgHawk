from __future__ import annotations

from enum import StrEnum
from types import MappingProxyType

from turfhelm.security.context import Role


class Action(StrEnum):
    SCHEDULE_READ = "schedule.read"
    ORDER_READ = "order.read"
    ORDER_CREATE = "order.create"
    ORDER_CORE_UPDATE = "order.core.update"
    ORDER_HARVEST_UPDATE = "order.harvest.update"
    ORDER_TRANSPORT_UPDATE = "order.transport.update"
    ORDER_INSTALL_UPDATE = "order.install.update"
    ORDER_PARKING_UPDATE = "order.parking.update"
    ORDER_CANCEL = "order.cancel"
    CUSTOMER_MANAGE = "customer.manage"
    FLEET_MANAGE = "fleet.manage"
    TEAM_MANAGE = "team.manage"
    SETTINGS_MANAGE = "settings.manage"
    USER_MANAGE = "user.manage"
    AUDIT_READ = "audit.read"


class PermissionDenied(PermissionError):
    """The active role does not permit the requested action."""


_ADMIN_ACTIONS = frozenset(Action)
_FARM_STAFF_ACTIONS = frozenset(
    {
        Action.SCHEDULE_READ,
        Action.ORDER_READ,
        Action.ORDER_HARVEST_UPDATE,
        Action.ORDER_TRANSPORT_UPDATE,
        Action.ORDER_PARKING_UPDATE,
    }
)
_SITE_SUPERVISOR_ACTIONS = frozenset(
    {
        Action.SCHEDULE_READ,
        Action.ORDER_READ,
        Action.ORDER_INSTALL_UPDATE,
        Action.ORDER_PARKING_UPDATE,
    }
)
_READ_ONLY_ACTIONS = frozenset({Action.SCHEDULE_READ, Action.ORDER_READ})

ACTIONS_BY_ROLE = MappingProxyType(
    {
        Role.ADMIN: _ADMIN_ACTIONS,
        Role.FARM_STAFF: _FARM_STAFF_ACTIONS,
        Role.SITE_SUPERVISOR: _SITE_SUPERVISOR_ACTIONS,
        Role.DRIVER: _READ_ONLY_ACTIONS,
        Role.INSTALLER: _READ_ONLY_ACTIONS,
    }
)


def is_allowed(role: object, action: object) -> bool:
    """Return False for every unknown role or action."""

    if not isinstance(role, Role) or not isinstance(action, Action):
        return False
    return action in ACTIONS_BY_ROLE.get(role, frozenset())


def require_permission(role: object, action: object) -> None:
    """Fail closed unless the role explicitly permits the named action."""

    if not is_allowed(role, action):
        raise PermissionDenied("permission denied")
