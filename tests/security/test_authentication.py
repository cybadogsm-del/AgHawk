from datetime import UTC, datetime, timedelta

import pytest

from turfhelm.security.authentication import (
    AuthenticationRequired,
    ExpiredIdentity,
    InvalidIdentity,
    principal_from_streamlit_user,
)

NOW = datetime(2026, 8, 4, 6, 0, tzinfo=UTC)


class FakeStreamlitUser(dict):
    def __init__(self, *, is_logged_in: bool, **claims: object) -> None:
        super().__init__(claims)
        self.is_logged_in = is_logged_in


def test_valid_streamlit_identity_returns_only_required_claims() -> None:
    expires_at = NOW + timedelta(hours=1)
    user = FakeStreamlitUser(
        is_logged_in=True,
        sub="auth0|user-1",
        exp=expires_at.timestamp(),
        email="worker@example.com",
    )
    user["unexpected_claim"] = "must-not-be-copied"

    principal = principal_from_streamlit_user(user, now=NOW)

    assert principal.oidc_subject == "auth0|user-1"
    assert principal.expires_at == expires_at
    assert not hasattr(principal, "email")
    assert "must-not-be-copied" not in repr(principal)


def test_anonymous_streamlit_user_is_rejected() -> None:
    user = FakeStreamlitUser(is_logged_in=False)

    with pytest.raises(AuthenticationRequired):
        principal_from_streamlit_user(user, now=NOW)


@pytest.mark.parametrize("subject", [None, "", "   ", 123])
def test_missing_or_invalid_subject_is_rejected(subject: object) -> None:
    user = FakeStreamlitUser(
        is_logged_in=True,
        sub=subject,
        exp=(NOW + timedelta(hours=1)).timestamp(),
    )

    with pytest.raises(InvalidIdentity, match="subject"):
        principal_from_streamlit_user(user, now=NOW)


@pytest.mark.parametrize("expiry", [None, "tomorrow", True])
def test_missing_or_invalid_expiry_is_rejected(expiry: object) -> None:
    user = FakeStreamlitUser(
        is_logged_in=True,
        sub="auth0|user-1",
        exp=expiry,
    )

    with pytest.raises(InvalidIdentity, match="expiry"):
        principal_from_streamlit_user(user, now=NOW)


@pytest.mark.parametrize("offset", [timedelta(seconds=0), timedelta(seconds=-1)])
def test_expired_identity_is_rejected(offset: timedelta) -> None:
    user = FakeStreamlitUser(
        is_logged_in=True,
        sub="auth0|user-1",
        exp=(NOW + offset).timestamp(),
    )

    with pytest.raises(ExpiredIdentity):
        principal_from_streamlit_user(user, now=NOW)
