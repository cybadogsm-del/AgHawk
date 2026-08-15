from __future__ import annotations

from turfhelm.branding.images import validate_logo
from turfhelm.branding.repository import BrandAsset, BrandingRepository, OrganizationBranding
from turfhelm.security.context import SecurityContext


class BrandingService:
    """Application boundary for validated organization logo operations."""

    def __init__(self, repository: BrandingRepository) -> None:
        self._repository = repository

    def get_active(self, context: SecurityContext) -> OrganizationBranding:
        return self._repository.get_active(context)

    def get_asset(self, context: SecurityContext, asset_id: str) -> BrandAsset | None:
        return self._repository.get_asset(context, asset_id)

    def replace_logo(
        self,
        context: SecurityContext,
        payload: bytes,
        *,
        expected_version: int,
        correlation_id: str,
    ) -> OrganizationBranding:
        self._repository.require_manage(context)
        image = validate_logo(payload)
        return self._repository.replace(
            context,
            image,
            expected_version=expected_version,
            correlation_id=correlation_id,
        )

    def reset_logo(
        self,
        context: SecurityContext,
        *,
        expected_version: int,
        correlation_id: str,
    ) -> OrganizationBranding:
        return self._repository.reset(
            context,
            expected_version=expected_version,
            correlation_id=correlation_id,
        )
