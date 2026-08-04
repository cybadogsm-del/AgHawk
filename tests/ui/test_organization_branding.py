from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import pytest

from turfhelm.branding.repository import BrandAsset, OrganizationBranding
from turfhelm.security.context import Role, SecurityContext
from turfhelm.ui.organization_branding import render_organization_branding


def context(*, organization_id: str = "org-a", role: Role = Role.FARM_STAFF) -> SecurityContext:
    return SecurityContext._from_active_membership(
        user_id="user-a",
        oidc_subject="oidc|user-a",
        organization_id=organization_id,
        role=role,
        proof=b"sealed",
    )


def branding(
    *,
    organization_id: str = "org-a",
    version: int = 7,
    logo: bytes | None = None,
) -> OrganizationBranding:
    asset = None
    if logo is not None:
        asset = BrandAsset(
            id="asset-a",
            organization_id=organization_id,
            content_type="image/png",
            byte_size=len(logo),
            width=10,
            height=8,
            sha256="a" * 64,
            canonical_bytes=logo,
            status="active",
        )
    return OrganizationBranding(organization_id=organization_id, version=version, asset=asset)


@dataclass(frozen=True)
class FakeUpload:
    payload: bytes

    def getvalue(self) -> bytes:
        return self.payload


@dataclass
class FakeService:
    current: OrganizationBranding
    calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = field(default_factory=list)

    def get_active(self, active_context: SecurityContext) -> OrganizationBranding:
        self.calls.append(("get_active", (active_context,), {}))
        return self.current

    def replace_logo(
        self,
        active_context: SecurityContext,
        payload: bytes,
        *,
        expected_version: int,
        correlation_id: str,
    ) -> OrganizationBranding:
        self.calls.append(
            (
                "replace_logo",
                (active_context, payload),
                {"expected_version": expected_version, "correlation_id": correlation_id},
            )
        )
        return self.current

    def reset_logo(
        self,
        active_context: SecurityContext,
        *,
        expected_version: int,
        correlation_id: str,
    ) -> OrganizationBranding:
        self.calls.append(
            (
                "reset_logo",
                (active_context,),
                {"expected_version": expected_version, "correlation_id": correlation_id},
            )
        )
        return self.current


@dataclass
class FakeUI:
    upload: FakeUpload | None = None
    pressed_keys: set[str] = field(default_factory=set)
    calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = field(default_factory=list)

    def subheader(self, body: str) -> None:
        self.calls.append(("subheader", (body,), {}))

    def image(self, image: bytes, *, caption: str) -> None:
        self.calls.append(("image", (image,), {"caption": caption}))

    def markdown(self, body: str) -> None:
        self.calls.append(("markdown", (body,), {}))

    def caption(self, body: str) -> None:
        self.calls.append(("caption", (body,), {}))

    def file_uploader(
        self, label: str, *, type: Sequence[str], key: str
    ) -> FakeUpload | None:
        self.calls.append(("file_uploader", (label,), {"type": type, "key": key}))
        return self.upload

    def button(self, label: str, *, key: str) -> bool:
        self.calls.append(("button", (label,), {"key": key}))
        return key in self.pressed_keys

    def success(self, body: str) -> None:
        self.calls.append(("success", (body,), {}))

    def error(self, body: str) -> None:
        self.calls.append(("error", (body,), {}))


def test_displays_authoritative_organization_name_and_own_canonical_logo() -> None:
    logo = b"canonical-png"
    active_context = context()
    service = FakeService(branding(logo=logo))
    ui = FakeUI()

    render_organization_branding(
        active_context,
        organization_display_name="Persisted Farm A",
        service=service,
        ui=ui,
        correlation_id_factory=lambda: "unused",
    )

    assert service.calls == [("get_active", (active_context,), {})]
    assert ("subheader", ("Persisted Farm A",), {}) in ui.calls
    assert ("image", (logo,), {"caption": "Persisted Farm A logo"}) in ui.calls
    assert ("caption", ("Powered by TurfHelm",), {}) in ui.calls


def test_missing_logo_uses_text_turfhelm_fallback_without_external_url() -> None:
    ui = FakeUI()

    render_organization_branding(
        context(),
        organization_display_name="Farm A",
        service=FakeService(branding()),
        ui=ui,
        correlation_id_factory=lambda: "unused",
    )

    assert ("markdown", ("🌱 **TurfHelm**",), {}) in ui.calls
    assert not any(name == "image" for name, _args, _kwargs in ui.calls)
    rendered = repr(ui.calls).lower()
    assert "turf galore" not in rendered
    assert "http://" not in rendered
    assert "https://" not in rendered


def test_admin_replace_passes_exact_context_version_bytes_and_correlation_id() -> None:
    active_context = context(role=Role.ADMIN)
    payload = b"uploaded-png-input"
    service = FakeService(branding(version=12, logo=b"old-canonical-logo"))
    ui = FakeUI(
        upload=FakeUpload(payload),
        pressed_keys={"branding.org-a.logo.replace"},
    )

    render_organization_branding(
        active_context,
        organization_display_name="Farm A",
        service=service,
        ui=ui,
        correlation_id_factory=lambda: "correlation-replace",
    )

    assert service.calls == [
        ("get_active", (active_context,), {}),
        (
            "replace_logo",
            (active_context, payload),
            {"expected_version": 12, "correlation_id": "correlation-replace"},
        ),
    ]
    uploader = next(call for call in ui.calls if call[0] == "file_uploader")
    assert uploader[2] == {
        "type": ("png", "jpg", "jpeg"),
        "key": "branding.org-a.logo.upload",
    }


def test_admin_reset_passes_exact_context_version_and_correlation_id() -> None:
    active_context = context(role=Role.ADMIN)
    service = FakeService(branding(version=4, logo=b"old-canonical-logo"))
    ui = FakeUI(pressed_keys={"branding.org-a.logo.reset"})

    render_organization_branding(
        active_context,
        organization_display_name="Farm A",
        service=service,
        ui=ui,
        correlation_id_factory=lambda: "correlation-reset",
    )

    assert service.calls == [
        ("get_active", (active_context,), {}),
        (
            "reset_logo",
            (active_context,),
            {"expected_version": 4, "correlation_id": "correlation-reset"},
        ),
    ]


def test_mutation_failure_is_generic_and_preserves_rendered_old_logo() -> None:
    class FailingService(FakeService):
        def replace_logo(
            self,
            active_context: SecurityContext,
            payload: bytes,
            *,
            expected_version: int,
            correlation_id: str,
        ) -> OrganizationBranding:
            raise sqlite3.DatabaseError("SELECT secret FROM users; internal stack detail")

    old_logo = b"old-canonical-logo"
    ui = FakeUI(
        upload=FakeUpload(b"new-input"),
        pressed_keys={"branding.org-a.logo.replace"},
    )

    render_organization_branding(
        context(role=Role.ADMIN),
        organization_display_name="Farm A",
        service=FailingService(branding(logo=old_logo)),
        ui=ui,
        correlation_id_factory=lambda: "correlation-failure",
    )

    assert ("image", (old_logo,), {"caption": "Farm A logo"}) in ui.calls
    errors = [args[0] for name, args, _kwargs in ui.calls if name == "error"]
    assert errors == ["We couldn't update the organization logo. Please try again."]
    assert "secret" not in repr(errors).lower()
    assert "select" not in repr(errors).lower()


@pytest.mark.parametrize("role", [role for role in Role if role is not Role.ADMIN])
def test_non_admin_roles_have_no_mutation_widgets(role: Role) -> None:
    ui = FakeUI()

    render_organization_branding(
        context(role=role),
        organization_display_name="Farm A",
        service=FakeService(branding(logo=b"own-logo")),
        ui=ui,
        correlation_id_factory=lambda: "unused",
    )

    assert not any(name in {"file_uploader", "button"} for name, _args, _kwargs in ui.calls)


def test_widget_keys_and_logo_bytes_are_isolated_by_organization() -> None:
    ui_a = FakeUI()
    ui_b = FakeUI()

    render_organization_branding(
        context(organization_id="org-a", role=Role.ADMIN),
        organization_display_name="Farm A",
        service=FakeService(branding(organization_id="org-a", logo=b"logo-a")),
        ui=ui_a,
        correlation_id_factory=lambda: "unused-a",
    )
    render_organization_branding(
        context(organization_id="org-b", role=Role.ADMIN),
        organization_display_name="Farm B",
        service=FakeService(branding(organization_id="org-b", logo=b"logo-b")),
        ui=ui_b,
        correlation_id_factory=lambda: "unused-b",
    )

    keys_a = {kwargs["key"] for _name, _args, kwargs in ui_a.calls if "key" in kwargs}
    keys_b = {kwargs["key"] for _name, _args, kwargs in ui_b.calls if "key" in kwargs}
    assert keys_a == {
        "branding.org-a.logo.upload",
        "branding.org-a.logo.replace",
        "branding.org-a.logo.reset",
    }
    assert keys_b == {
        "branding.org-b.logo.upload",
        "branding.org-b.logo.replace",
        "branding.org-b.logo.reset",
    }
    assert keys_a.isdisjoint(keys_b)
    assert ("image", (b"logo-a",), {"caption": "Farm A logo"}) in ui_a.calls
    assert ("image", (b"logo-b",), {"caption": "Farm B logo"}) in ui_b.calls
    assert b"logo-b" not in repr(ui_a.calls).encode()
    assert b"logo-a" not in repr(ui_b.calls).encode()


def test_branding_read_failure_shows_safe_fallback_without_internal_details() -> None:
    class FailingReadService(FakeService):
        def get_active(self, active_context: SecurityContext) -> OrganizationBranding:
            raise sqlite3.DatabaseError("SELECT canonical_bytes FROM brand_assets")

    ui = FakeUI()

    render_organization_branding(
        context(role=Role.ADMIN),
        organization_display_name="Farm A",
        service=FailingReadService(branding()),
        ui=ui,
        correlation_id_factory=lambda: "unused",
    )

    assert ("subheader", ("Farm A",), {}) in ui.calls
    assert ("markdown", ("🌱 **TurfHelm**",), {}) in ui.calls
    assert ("caption", ("Powered by TurfHelm",), {}) in ui.calls
    assert not any(name in {"image", "file_uploader", "button"} for name, _args, _kw in ui.calls)
    errors = [args[0] for name, args, _kwargs in ui.calls if name == "error"]
    assert errors == ["We couldn't load the organization logo. Please try again."]
    assert "select" not in repr(errors).lower()


def test_mismatched_service_organization_fails_closed_without_displaying_logo() -> None:
    ui = FakeUI()

    render_organization_branding(
        context(organization_id="org-a", role=Role.ADMIN),
        organization_display_name="Farm A",
        service=FakeService(branding(organization_id="org-b", logo=b"other-org-logo")),
        ui=ui,
        correlation_id_factory=lambda: "unused",
    )

    assert not any(name == "image" for name, _args, _kwargs in ui.calls)
    assert b"other-org-logo" not in repr(ui.calls).encode()
    assert ("markdown", ("🌱 **TurfHelm**",), {}) in ui.calls
    assert not any(name in {"file_uploader", "button"} for name, _args, _kw in ui.calls)
    assert ("error", ("We couldn't load the organization logo. Please try again.",), {}) in ui.calls
