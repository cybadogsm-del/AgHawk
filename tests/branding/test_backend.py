from __future__ import annotations

import io
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest
from PIL import Image

from turfhelm.branding.repository import BrandingRepository, VersionConflict
from turfhelm.branding.service import BrandingService
from turfhelm.db.connection import connect_sqlite
from turfhelm.db.migrations import apply_migrations
from turfhelm.security.authentication import AuthenticatedPrincipal
from turfhelm.security.authority import SecurityContextAuthority
from turfhelm.security.permissions import PermissionDenied

AUTHORITY = SecurityContextAuthority(signing_key=b"branding-test-signing-key-" + b"x" * 32)


def logo_bytes(color: str = "green") -> bytes:
    output = io.BytesIO()
    Image.new("RGBA", (12, 8), color).save(output, format="PNG")
    return output.getvalue()


def principal(subject: str) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        oidc_subject=subject,
        expires_at=datetime.max.replace(tzinfo=UTC),
    )


def seed(connection: sqlite3.Connection) -> dict[str, object]:
    connection.executemany(
        "INSERT INTO organizations (id, name, slug) VALUES (?, ?, ?)",
        [("org-a", "Farm A", "farm-a"), ("org-b", "Farm B", "farm-b")],
    )
    users = [
        ("admin-a", "oidc|admin-a", "Admin A", "org-a", "admin"),
        ("staff-a", "oidc|staff-a", "Staff A", "org-a", "farm_staff"),
        ("admin-b", "oidc|admin-b", "Admin B", "org-b", "admin"),
    ]
    for user_id, subject, name, organization_id, role in users:
        connection.execute(
            "INSERT INTO users (id, oidc_subject, display_name) VALUES (?, ?, ?)",
            (user_id, subject, name),
        )
        connection.execute(
            """
            INSERT INTO organization_memberships (organization_id, user_id, role)
            VALUES (?, ?, ?)
            """,
            (organization_id, user_id, role),
        )
    connection.commit()
    return {
        "admin_a": AUTHORITY.resolve(
            connection, principal=principal("oidc|admin-a"), organization_id="org-a"
        ),
        "staff_a": AUTHORITY.resolve(
            connection, principal=principal("oidc|staff-a"), organization_id="org-a"
        ),
        "admin_b": AUTHORITY.resolve(
            connection, principal=principal("oidc|admin-b"), organization_id="org-b"
        ),
    }


def setup(tmp_path: Path) -> tuple[sqlite3.Connection, BrandingService, dict[str, object]]:
    connection = connect_sqlite(tmp_path / "test.db")
    apply_migrations(connection)
    contexts = seed(connection)
    return connection, BrandingService(BrandingRepository(connection, AUTHORITY)), contexts


def test_active_member_can_read_only_own_default_branding(tmp_path: Path) -> None:
    _, service, contexts = setup(tmp_path)

    branding = service.get_active(contexts["staff_a"])

    assert branding.organization_id == "org-a"
    assert branding.version == 1
    assert branding.asset is None


def test_administrator_replaces_logo_and_audit_is_created_atomically(tmp_path: Path) -> None:
    connection, service, contexts = setup(tmp_path)

    branding = service.replace_logo(
        contexts["admin_a"],
        logo_bytes(),
        expected_version=1,
        correlation_id="request-1",
    )

    assert branding.version == 2
    assert branding.asset is not None
    assert branding.asset.id
    assert branding.asset.organization_id == "org-a"
    assert branding.asset.content_type == "image/png"
    assert branding.asset.canonical_bytes != logo_bytes()
    event = connection.execute(
        "SELECT * FROM audit_events WHERE organization_id = ?", ("org-a",)
    ).fetchone()
    assert event["action"] == "branding.logo.replaced"
    assert event["object_id"] == branding.asset.id
    assert event["actor_user_id"] == "admin-a"
    assert event["correlation_id"] == "request-1"


def test_non_administrator_cannot_replace_logo(tmp_path: Path) -> None:
    connection, service, contexts = setup(tmp_path)

    with pytest.raises(PermissionDenied):
        service.replace_logo(
            contexts["staff_a"], logo_bytes(), expected_version=1, correlation_id="denied"
        )
    with pytest.raises(PermissionDenied):
        service.replace_logo(
            contexts["staff_a"], b"not an image", expected_version=1, correlation_id="denied-2"
        )

    assert connection.execute("SELECT COUNT(*) FROM brand_assets").fetchone()[0] == 0
    assert connection.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0] == 0


def test_cross_tenant_asset_reads_and_links_fail_closed(tmp_path: Path) -> None:
    connection, service, contexts = setup(tmp_path)
    org_b_branding = service.replace_logo(
        contexts["admin_b"], logo_bytes("blue"), expected_version=1, correlation_id="b"
    )
    asset_id = org_b_branding.asset.id

    assert service.get_asset(contexts["admin_a"], asset_id) is None
    assert service.get_active(contexts["admin_a"]).asset is None
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "UPDATE organization_branding SET active_asset_id = ? WHERE organization_id = ?",
            (asset_id, "org-a"),
        )


def test_reset_archives_prior_asset_and_creates_audit(tmp_path: Path) -> None:
    connection, service, contexts = setup(tmp_path)
    replaced = service.replace_logo(
        contexts["admin_a"], logo_bytes(), expected_version=1, correlation_id="replace"
    )

    reset = service.reset_logo(
        contexts["admin_a"], expected_version=2, correlation_id="reset"
    )

    assert reset.version == 3
    assert reset.asset is None
    archived = connection.execute(
        "SELECT status, archived_at FROM brand_assets WHERE id = ?", (replaced.asset.id,)
    ).fetchone()
    assert tuple(archived) == ("archived", archived["archived_at"])
    assert archived["archived_at"] is not None
    assert connection.execute(
        "SELECT COUNT(*) FROM audit_events WHERE action = 'branding.logo.reset'"
    ).fetchone()[0] == 1
    with pytest.raises(sqlite3.IntegrityError, match="archived"):
        connection.execute("DELETE FROM brand_assets WHERE id = ?", (replaced.asset.id,))


def test_version_conflict_preserves_active_logo_without_audit(tmp_path: Path) -> None:
    connection, service, contexts = setup(tmp_path)
    original = service.replace_logo(
        contexts["admin_a"], logo_bytes(), expected_version=1, correlation_id="first"
    )

    with pytest.raises(VersionConflict):
        service.replace_logo(
            contexts["admin_a"],
            logo_bytes("red"),
            expected_version=1,
            correlation_id="stale",
        )

    current = service.get_active(contexts["admin_a"])
    assert current.asset.id == original.asset.id
    assert current.version == 2
    assert connection.execute("SELECT COUNT(*) FROM brand_assets").fetchone()[0] == 1
    assert connection.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0] == 1


def test_audit_failure_rolls_back_asset_pointer_and_archive(tmp_path: Path) -> None:
    connection, service, contexts = setup(tmp_path)
    original = service.replace_logo(
        contexts["admin_a"], logo_bytes(), expected_version=1, correlation_id="first"
    )
    connection.execute(
        """
        CREATE TRIGGER reject_branding_audit
        BEFORE INSERT ON audit_events
        WHEN NEW.action = 'branding.logo.replaced'
        BEGIN
            SELECT RAISE(ABORT, 'forced audit failure');
        END
        """
    )
    connection.commit()

    with pytest.raises(sqlite3.IntegrityError, match="forced audit failure"):
        service.replace_logo(
            contexts["admin_a"],
            logo_bytes("red"),
            expected_version=2,
            correlation_id="second",
        )

    current = service.get_active(contexts["admin_a"])
    assert current.asset.id == original.asset.id
    assert current.version == 2
    assert connection.execute(
        "SELECT status FROM brand_assets WHERE id = ?", (original.asset.id,)
    ).fetchone()[0] == "active"
    assert connection.execute("SELECT COUNT(*) FROM brand_assets").fetchone()[0] == 1


def test_revoked_context_cannot_read_or_write(tmp_path: Path) -> None:
    connection, service, contexts = setup(tmp_path)
    connection.execute(
        """
        UPDATE organization_memberships SET status = 'disabled'
        WHERE organization_id = 'org-a' AND user_id = 'admin-a'
        """
    )
    connection.commit()

    with pytest.raises(PermissionError, match="no longer active"):
        service.get_active(contexts["admin_a"])
    with pytest.raises(PermissionError, match="no longer active"):
        service.reset_logo(contexts["admin_a"], expected_version=1, correlation_id="revoked")


def test_revocation_rechecked_inside_owned_write_transaction(tmp_path: Path) -> None:
    connection = connect_sqlite(tmp_path / "test.db")
    apply_migrations(connection)
    contexts = seed(connection)

    class RevokeOnPostLockCheck:
        def __init__(self) -> None:
            self.calls = 0

        def require_active(self, active_connection, context) -> None:
            self.calls += 1
            if self.calls == 3:
                active_connection.execute(
                    """
                    UPDATE organization_memberships SET status = 'disabled'
                    WHERE organization_id = ? AND user_id = ?
                    """,
                    (context.organization_id, context.user_id),
                )
            AUTHORITY.require_active(active_connection, context)

    service = BrandingService(BrandingRepository(connection, RevokeOnPostLockCheck()))

    with pytest.raises(PermissionError, match="no longer active"):
        service.replace_logo(
            contexts["admin_a"], logo_bytes(), expected_version=1, correlation_id="race"
        )

    assert connection.execute(
        "SELECT version FROM organization_branding WHERE organization_id = 'org-a'"
    ).fetchone()[0] == 1
    assert connection.execute("SELECT COUNT(*) FROM brand_assets").fetchone()[0] == 0
    assert connection.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0] == 0


def test_branding_rejects_ambient_transaction_without_rolling_it_back(tmp_path: Path) -> None:
    connection, service, contexts = setup(tmp_path)
    connection.execute(
        "INSERT INTO system_config (organization_id, key, value) VALUES (?, ?, ?)",
        ("org-a", "pending-setting", "keep-me"),
    )

    with pytest.raises(RuntimeError, match="active transaction"):
        service.replace_logo(
            contexts["admin_a"], logo_bytes(), expected_version=1, correlation_id="ambient"
        )

    assert connection.in_transaction is True
    assert connection.execute(
        "SELECT value FROM system_config WHERE organization_id = ? AND key = ?",
        ("org-a", "pending-setting"),
    ).fetchone()[0] == "keep-me"


def test_brand_asset_content_and_archive_history_are_immutable(tmp_path: Path) -> None:
    connection, service, contexts = setup(tmp_path)
    replaced = service.replace_logo(
        contexts["admin_a"], logo_bytes(), expected_version=1, correlation_id="replace"
    )

    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        connection.execute(
            """
            UPDATE brand_assets
            SET canonical_bytes = ?, byte_size = ?, sha256 = ?
            WHERE id = ?
            """,
            (b"forged", len(b"forged"), "0" * 64, replaced.asset.id),
        )
    connection.rollback()

    service.reset_logo(
        contexts["admin_a"], expected_version=2, correlation_id="reset"
    )
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        connection.execute(
            "UPDATE brand_assets SET status = 'active', archived_at = NULL WHERE id = ?",
            (replaced.asset.id,),
        )
