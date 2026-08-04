import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from turfhelm.security.authentication import AuthenticatedPrincipal
from turfhelm.security.authority import SecurityContextAuthority
from turfhelm.security.context import Role, SecurityContext
from turfhelm.security.sessions import (
    AbsoluteSessionExpired,
    IdentityTokenExpired,
    IdleSessionExpired,
    SessionClockInvalid,
    SessionRecord,
    clear_sensitive_session_state,
    refresh_session_activity,
    require_valid_session,
)

START = datetime(2026, 8, 4, 6, 0, tzinfo=UTC)
AUTHORITY = SecurityContextAuthority(signing_key=b"session-test-key-" + (b"x" * 32))


def principal(*, expires_in: timedelta = timedelta(hours=24)) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        oidc_subject="auth0|user-1",
        expires_at=START + expires_in,
    )


def session(*, last_activity: timedelta = timedelta()) -> SessionRecord:
    return SessionRecord(
        oidc_subject="auth0|user-1",
        organization_id="org-1",
        started_at=START,
        last_activity_at=START + last_activity,
    )


def context(
    *,
    role: Role = Role.ADMIN,
    oidc_subject: str = "auth0|user-1",
    organization_id: str = "org-1",
) -> tuple[sqlite3.Connection, SecurityContext]:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        CREATE TABLE organizations (id TEXT PRIMARY KEY, status TEXT NOT NULL);
        CREATE TABLE users (
            id TEXT PRIMARY KEY, oidc_subject TEXT NOT NULL, status TEXT NOT NULL
        );
        CREATE TABLE organization_memberships (
            organization_id TEXT NOT NULL, user_id TEXT NOT NULL,
            role TEXT NOT NULL, status TEXT NOT NULL
        );
        """
    )
    connection.execute("INSERT INTO organizations VALUES (?, 'active')", (organization_id,))
    connection.execute("INSERT INTO users VALUES ('user-1', ?, 'active')", (oidc_subject,))
    connection.execute(
        "INSERT INTO organization_memberships VALUES (?, 'user-1', ?, 'active')",
        (organization_id, role.value),
    )
    checked_context = AUTHORITY.resolve(
        connection,
        principal=AuthenticatedPrincipal(
            oidc_subject=oidc_subject,
            expires_at=START + timedelta(days=1),
        ),
        organization_id=organization_id,
    )
    return connection, checked_context


def test_active_administrator_session_is_accepted() -> None:
    connection, checked_context = context()
    require_valid_session(
        connection=connection,
        authority=AUTHORITY,
        principal=principal(),
        context=checked_context,
        session=session(last_activity=timedelta(minutes=10)),
        now=START + timedelta(minutes=20),
    )


def test_expired_identity_token_is_rejected() -> None:
    connection, checked_context = context()
    with pytest.raises(IdentityTokenExpired):
        require_valid_session(
            connection=connection,
            authority=AUTHORITY,
            principal=principal(expires_in=timedelta(hours=1)),
            context=checked_context,
            session=session(last_activity=timedelta(minutes=20)),
            now=START + timedelta(hours=1),
        )


@pytest.mark.parametrize(
    ("role", "idle_for"),
    [
        (Role.ADMIN, timedelta(minutes=30, seconds=1)),
        (Role.DRIVER, timedelta(hours=2, seconds=1)),
        (Role.FARM_STAFF, timedelta(hours=2, seconds=1)),
    ],
)
def test_idle_session_is_rejected(role: Role, idle_for: timedelta) -> None:
    current = START + idle_for
    connection, checked_context = context(role=role)

    with pytest.raises(IdleSessionExpired):
        require_valid_session(
            connection=connection,
            authority=AUTHORITY,
            principal=principal(),
            context=checked_context,
            session=session(),
            now=current,
        )


@pytest.mark.parametrize(
    ("role", "duration"),
    [
        (Role.ADMIN, timedelta(hours=8, seconds=1)),
        (Role.SITE_SUPERVISOR, timedelta(hours=12, seconds=1)),
        (Role.INSTALLER, timedelta(hours=12, seconds=1)),
    ],
)
def test_absolute_session_limit_is_enforced(role: Role, duration: timedelta) -> None:
    current = START + duration
    connection, checked_context = context(role=role)

    with pytest.raises(AbsoluteSessionExpired):
        require_valid_session(
            connection=connection,
            authority=AUTHORITY,
            principal=principal(expires_in=timedelta(days=2)),
            context=checked_context,
            session=session(last_activity=duration - timedelta(minutes=1)),
            now=current,
        )


def test_activity_refresh_does_not_change_absolute_start_time() -> None:
    existing = session(last_activity=timedelta(minutes=10))
    refreshed = refresh_session_activity(existing, now=START + timedelta(minutes=20))

    assert refreshed.started_at == START
    assert refreshed.last_activity_at == START + timedelta(minutes=20)
    assert refreshed.oidc_subject == existing.oidc_subject
    assert refreshed.organization_id == existing.organization_id


def test_session_subject_must_match_authenticated_principal() -> None:
    connection, checked_context = context()
    wrong_principal = AuthenticatedPrincipal(
        oidc_subject="auth0|attacker",
        expires_at=START + timedelta(hours=1),
    )

    with pytest.raises(PermissionError, match="does not match"):
        require_valid_session(
            connection=connection,
            authority=AUTHORITY,
            principal=wrong_principal,
            context=checked_context,
            session=session(),
            now=START + timedelta(minutes=1),
        )


@pytest.mark.parametrize(
    ("now", "expected_error"),
    [
        (START - timedelta(seconds=1), SessionClockInvalid),
        (START + timedelta(minutes=9), SessionClockInvalid),
    ],
)
def test_validation_time_cannot_precede_session_timestamps(
    now: datetime,
    expected_error: type[PermissionError],
) -> None:
    existing = session(last_activity=timedelta(minutes=10))
    connection, checked_context = context()

    with pytest.raises(expected_error):
        require_valid_session(
            connection=connection,
            authority=AUTHORITY,
            principal=principal(),
            context=checked_context,
            session=existing,
            now=now,
        )


def test_worker_role_cannot_be_substituted_for_admin_context_limits() -> None:
    connection, checked_context = context(role=Role.ADMIN)
    with pytest.raises(IdleSessionExpired):
        require_valid_session(
            connection=connection,
            authority=AUTHORITY,
            principal=principal(),
            context=checked_context,
            session=session(),
            now=START + timedelta(minutes=30, seconds=1),
        )


def test_forged_worker_context_is_rejected_before_worker_session_limits_apply() -> None:
    connection, checked_context = context()
    forged_context = SecurityContext._from_active_membership(
        user_id=checked_context.user_id,
        oidc_subject=checked_context.oidc_subject,
        organization_id=checked_context.organization_id,
        role=Role.DRIVER,
        proof=b"forged-proof",
    )

    with pytest.raises(PermissionError, match="proof is invalid"):
        require_valid_session(
            connection=connection,
            authority=AUTHORITY,
            principal=principal(),
            context=forged_context,
            session=session(),
            now=START + timedelta(minutes=30, seconds=1),
        )


@pytest.mark.parametrize(
    "deactivation_sql",
    [
        "UPDATE organization_memberships SET status = 'disabled' WHERE user_id = 'user-1'",
        "UPDATE users SET status = 'disabled' WHERE id = 'user-1'",
        "UPDATE organizations SET status = 'disabled' WHERE id = 'org-1'",
    ],
    ids=["membership", "user", "organization"],
)
def test_formerly_valid_context_is_rejected_after_deactivation(
    deactivation_sql: str,
) -> None:
    connection, checked_context = context()
    connection.execute(deactivation_sql)
    connection.commit()

    with pytest.raises(PermissionError, match="no longer active"):
        require_valid_session(
            connection=connection,
            authority=AUTHORITY,
            principal=principal(),
            context=checked_context,
            session=session(),
            now=START + timedelta(minutes=1),
        )


def test_context_subject_must_match_principal_and_session() -> None:
    connection, checked_context = context(oidc_subject="auth0|other")
    with pytest.raises(PermissionError, match="does not match"):
        require_valid_session(
            connection=connection,
            authority=AUTHORITY,
            principal=principal(),
            context=checked_context,
            session=session(),
            now=START + timedelta(minutes=1),
        )


def test_cross_organization_session_reuse_is_denied() -> None:
    connection, checked_context = context(organization_id="org-2")
    with pytest.raises(PermissionError, match="organization"):
        require_valid_session(
            connection=connection,
            authority=AUTHORITY,
            principal=principal(),
            context=checked_context,
            session=session(),
            now=START + timedelta(minutes=1),
        )


def test_logout_cleanup_removes_sensitive_state_only() -> None:
    state = {
        "security_context": object(),
        "authenticated_principal": object(),
        "session_record": object(),
        "selected_organization_id": "org-1",
        "editing_order": "order-1",
        "run_date": "2026-08-04",
        "theme": "dark",
    }

    clear_sensitive_session_state(state)

    assert state == {"theme": "dark"}
