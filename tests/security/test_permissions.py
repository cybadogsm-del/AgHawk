import pytest

from turfhelm.security.context import Role
from turfhelm.security.permissions import (
    ACTIONS_BY_ROLE,
    Action,
    PermissionDenied,
    is_allowed,
    require_permission,
)

ADMIN_ACTIONS = frozenset(Action)
FARM_STAFF_ACTIONS = frozenset(
    {
        Action.SCHEDULE_READ,
        Action.ORDER_READ,
        Action.ORDER_HARVEST_UPDATE,
        Action.ORDER_TRANSPORT_UPDATE,
        Action.ORDER_PARKING_UPDATE,
    }
)
SITE_SUPERVISOR_ACTIONS = frozenset(
    {
        Action.SCHEDULE_READ,
        Action.ORDER_READ,
        Action.ORDER_INSTALL_UPDATE,
        Action.ORDER_PARKING_UPDATE,
    }
)
READ_ONLY_ACTIONS = frozenset({Action.SCHEDULE_READ, Action.ORDER_READ})


@pytest.mark.parametrize(
    ("role", "expected"),
    [
        (Role.ADMIN, ADMIN_ACTIONS),
        (Role.FARM_STAFF, FARM_STAFF_ACTIONS),
        (Role.SITE_SUPERVISOR, SITE_SUPERVISOR_ACTIONS),
        (Role.DRIVER, READ_ONLY_ACTIONS),
        (Role.INSTALLER, READ_ONLY_ACTIONS),
    ],
)
def test_role_matrix_matches_approved_permissions(
    role: Role,
    expected: frozenset[Action],
) -> None:
    allowed = frozenset(action for action in Action if is_allowed(role, action))

    assert allowed == expected
    assert ACTIONS_BY_ROLE[role] == expected


@pytest.mark.parametrize("role", list(Role))
def test_every_role_denies_unknown_action(role: Role) -> None:
    assert is_allowed(role, "order.superuser") is False

    with pytest.raises(PermissionDenied):
        require_permission(role, "order.superuser")


@pytest.mark.parametrize("action", list(Action))
def test_unknown_role_is_denied_for_every_action(action: Action) -> None:
    assert is_allowed("super_admin", action) is False

    with pytest.raises(PermissionDenied):
        require_permission("super_admin", action)


@pytest.mark.parametrize(
    ("role", "action"),
    [
        (Role.DRIVER, Action.ORDER_HARVEST_UPDATE),
        (Role.INSTALLER, Action.ORDER_INSTALL_UPDATE),
        (Role.FARM_STAFF, Action.USER_MANAGE),
        (Role.SITE_SUPERVISOR, Action.ORDER_CANCEL),
    ],
)
def test_high_risk_role_escalations_are_denied(role: Role, action: Action) -> None:
    with pytest.raises(PermissionDenied, match="permission denied"):
        require_permission(role, action)


def test_allowed_action_returns_without_error() -> None:
    require_permission(Role.FARM_STAFF, Action.ORDER_HARVEST_UPDATE)
