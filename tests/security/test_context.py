import pytest

import turfhelm.security.context as context_module
from turfhelm.security.context import Role, SecurityContext


def test_security_context_cannot_be_constructed_from_caller_values() -> None:
    with pytest.raises(TypeError, match="trusted persistence"):
        SecurityContext(
            user_id="attacker",
            organization_id="victim-org",
            role=Role.ADMIN,
        )


def test_context_module_has_no_public_identity_issuer() -> None:
    assert not hasattr(context_module, "issue_security_context")
    assert not hasattr(context_module, "VerifiedIdentity")
    assert not hasattr(context_module, "ActiveMembership")
    assert not hasattr(context_module, "_CONTEXT_ISSUER")


def test_roles_are_limited_to_the_approved_list() -> None:
    assert {role.value for role in Role} == {
        "admin",
        "farm_staff",
        "site_supervisor",
        "driver",
        "installer",
    }

    with pytest.raises(ValueError):
        Role("super_admin")
