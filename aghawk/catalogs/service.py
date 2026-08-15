from __future__ import annotations

from turfhelm.catalogs.repository import (
    CatalogKind,
    CatalogRepository,
    NamedCatalogRecord,
    PalletSizeRecord,
    TransportOptionRecord,
)
from turfhelm.security.context import SecurityContext

_MAX_NAME_LENGTH = 100


class CatalogService:
    """Validated application boundary for operational setup catalogs."""

    def __init__(self, repository: CatalogRepository) -> None:
        self._repository = repository

    def list_varieties(self, context: SecurityContext) -> list[NamedCatalogRecord]:
        return self._named_list(context, CatalogKind.VARIETY)

    def create_variety(
        self, context: SecurityContext, name: str, *, correlation_id: str
    ) -> NamedCatalogRecord:
        return self._create_named(context, CatalogKind.VARIETY, name, correlation_id)

    def archive_variety(
        self, context: SecurityContext, record_id: str, *, correlation_id: str
    ) -> NamedCatalogRecord:
        return self._archive_named(context, CatalogKind.VARIETY, record_id, correlation_id)

    def list_pallet_sizes(self, context: SecurityContext) -> list[PalletSizeRecord]:
        records = self._repository.list_active(context, CatalogKind.PALLET_SIZE)
        return [record for record in records if isinstance(record, PalletSizeRecord)]

    def create_pallet_size(
        self, context: SecurityContext, size: object, *, correlation_id: str
    ) -> PalletSizeRecord:
        self._repository.require_manage(context, CatalogKind.PALLET_SIZE)
        if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
            raise ValueError("pallet size must be a positive integer")
        record = self._repository.create(
            context, CatalogKind.PALLET_SIZE, {"size": size}, correlation_id=correlation_id
        )
        if not isinstance(record, PalletSizeRecord):
            raise RuntimeError("unexpected catalog record type")
        return record

    def archive_pallet_size(
        self, context: SecurityContext, record_id: str, *, correlation_id: str
    ) -> PalletSizeRecord:
        record = self._repository.archive(
            context, CatalogKind.PALLET_SIZE, record_id, correlation_id=correlation_id
        )
        if not isinstance(record, PalletSizeRecord):
            raise RuntimeError("unexpected catalog record type")
        return record

    def list_transport_options(self, context: SecurityContext) -> list[TransportOptionRecord]:
        records = self._repository.list_active(context, CatalogKind.TRANSPORT_OPTION)
        return [record for record in records if isinstance(record, TransportOptionRecord)]

    def create_transport_option(
        self,
        context: SecurityContext,
        name: str,
        *,
        pallet_capacity: object,
        correlation_id: str,
    ) -> TransportOptionRecord:
        self._repository.require_manage(context, CatalogKind.TRANSPORT_OPTION)
        normalized = self._normalize_name(name)
        if (
            isinstance(pallet_capacity, bool)
            or not isinstance(pallet_capacity, int)
            or pallet_capacity < 0
        ):
            raise ValueError("pallet capacity must be a non-negative integer")
        record = self._repository.create(
            context,
            CatalogKind.TRANSPORT_OPTION,
            {"name": normalized, "pallet_capacity": pallet_capacity},
            correlation_id=correlation_id,
        )
        if not isinstance(record, TransportOptionRecord):
            raise RuntimeError("unexpected catalog record type")
        return record

    def archive_transport_option(
        self, context: SecurityContext, record_id: str, *, correlation_id: str
    ) -> TransportOptionRecord:
        record = self._repository.archive(
            context, CatalogKind.TRANSPORT_OPTION, record_id, correlation_id=correlation_id
        )
        if not isinstance(record, TransportOptionRecord):
            raise RuntimeError("unexpected catalog record type")
        return record

    def list_teams(self, context: SecurityContext) -> list[NamedCatalogRecord]:
        return self._named_list(context, CatalogKind.TEAM)

    def create_team(
        self, context: SecurityContext, name: str, *, correlation_id: str
    ) -> NamedCatalogRecord:
        return self._create_named(context, CatalogKind.TEAM, name, correlation_id)

    def archive_team(
        self, context: SecurityContext, record_id: str, *, correlation_id: str
    ) -> NamedCatalogRecord:
        return self._archive_named(context, CatalogKind.TEAM, record_id, correlation_id)

    def list_service_types(self, context: SecurityContext) -> list[NamedCatalogRecord]:
        return self._named_list(context, CatalogKind.SERVICE_TYPE)

    def create_service_type(
        self, context: SecurityContext, name: str, *, correlation_id: str
    ) -> NamedCatalogRecord:
        return self._create_named(context, CatalogKind.SERVICE_TYPE, name, correlation_id)

    def archive_service_type(
        self, context: SecurityContext, record_id: str, *, correlation_id: str
    ) -> NamedCatalogRecord:
        return self._archive_named(context, CatalogKind.SERVICE_TYPE, record_id, correlation_id)

    def _named_list(
        self, context: SecurityContext, kind: CatalogKind
    ) -> list[NamedCatalogRecord]:
        records = self._repository.list_active(context, kind)
        return [record for record in records if isinstance(record, NamedCatalogRecord)]

    def _create_named(
        self,
        context: SecurityContext,
        kind: CatalogKind,
        name: str,
        correlation_id: str,
    ) -> NamedCatalogRecord:
        self._repository.require_manage(context, kind)
        normalized = self._normalize_name(name)
        record = self._repository.create(
            context, kind, {"name": normalized}, correlation_id=correlation_id
        )
        if not isinstance(record, NamedCatalogRecord):
            raise RuntimeError("unexpected catalog record type")
        return record

    def _archive_named(
        self,
        context: SecurityContext,
        kind: CatalogKind,
        record_id: str,
        correlation_id: str,
    ) -> NamedCatalogRecord:
        record = self._repository.archive(
            context, kind, record_id, correlation_id=correlation_id
        )
        if not isinstance(record, NamedCatalogRecord):
            raise RuntimeError("unexpected catalog record type")
        return record

    @staticmethod
    def _normalize_name(name: str) -> str:
        if not isinstance(name, str):
            raise ValueError("name must be text")
        normalized = " ".join(name.split())
        if not normalized:
            raise ValueError("name is required")
        if len(normalized) > _MAX_NAME_LENGTH:
            raise ValueError(f"name must contain at most {_MAX_NAME_LENGTH} characters")
        return normalized
