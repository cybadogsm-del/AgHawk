from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Protocol

from turfhelm.branding.repository import OrganizationBranding
from turfhelm.security.context import Role, SecurityContext


class UploadedLogo(Protocol):
    def getvalue(self) -> bytes: ...


class BrandingServiceUI(Protocol):
    """Branding operations consumed by the presentation component."""

    def get_active(self, context: SecurityContext) -> OrganizationBranding: ...

    def replace_logo(
        self,
        context: SecurityContext,
        payload: bytes,
        *,
        expected_version: int,
        correlation_id: str,
    ) -> OrganizationBranding: ...

    def reset_logo(
        self,
        context: SecurityContext,
        *,
        expected_version: int,
        correlation_id: str,
    ) -> OrganizationBranding: ...


class BrandingUI(Protocol):
    """Small Streamlit-compatible boundary used by the branding component."""

    def subheader(self, body: str) -> None: ...

    def image(self, image: bytes, *, caption: str) -> None: ...

    def markdown(self, body: str) -> None: ...

    def caption(self, body: str) -> None: ...

    def file_uploader(
        self,
        label: str,
        *,
        type: Sequence[str],
        key: str,
    ) -> UploadedLogo | None: ...

    def button(self, label: str, *, key: str) -> bool: ...

    def success(self, body: str) -> None: ...

    def error(self, body: str) -> None: ...


CorrelationIdFactory = Callable[[], str]


def render_organization_branding(
    context: SecurityContext,
    *,
    organization_display_name: str,
    service: BrandingServiceUI,
    ui: BrandingUI,
    correlation_id_factory: CorrelationIdFactory,
) -> None:
    """Render persisted organization branding for the sealed active context."""

    ui.subheader(organization_display_name)
    try:
        current = service.get_active(context)
    except Exception:
        ui.markdown("🌱 **TurfHelm**")
        ui.caption("Powered by TurfHelm")
        ui.error("We couldn't load the organization logo. Please try again.")
        return
    if current.organization_id != context.organization_id:
        ui.markdown("🌱 **TurfHelm**")
        ui.caption("Powered by TurfHelm")
        ui.error("We couldn't load the organization logo. Please try again.")
        return
    if current.asset is not None:
        ui.image(current.asset.canonical_bytes, caption=f"{organization_display_name} logo")
    else:
        ui.markdown("🌱 **TurfHelm**")
    ui.caption("Powered by TurfHelm")

    if context.role is not Role.ADMIN:
        return

    key_prefix = f"branding.{context.organization_id}.logo"
    upload = ui.file_uploader(
        "Upload organization logo (PNG or JPEG, maximum 2 MiB)",
        type=("png", "jpg", "jpeg"),
        key=f"{key_prefix}.upload",
    )
    if ui.button("Replace logo", key=f"{key_prefix}.replace") and upload is not None:
        try:
            service.replace_logo(
                context,
                upload.getvalue(),
                expected_version=current.version,
                correlation_id=correlation_id_factory(),
            )
        except Exception:
            ui.error("We couldn't update the organization logo. Please try again.")
        else:
            ui.success("Organization logo updated.")
    if ui.button("Reset logo", key=f"{key_prefix}.reset"):
        try:
            service.reset_logo(
                context,
                expected_version=current.version,
                correlation_id=correlation_id_factory(),
            )
        except Exception:
            ui.error("We couldn't update the organization logo. Please try again.")
        else:
            ui.success("Organization logo reset.")
