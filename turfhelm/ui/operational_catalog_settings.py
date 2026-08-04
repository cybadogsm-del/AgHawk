from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Protocol, TypeVar

from turfhelm.catalogs.repository import (
    NamedCatalogRecord,
    PalletSizeRecord,
    TransportOptionRecord,
)
from turfhelm.security.context import Role, SecurityContext


class CatalogServiceUI(Protocol):
    """Operational catalog operations consumed by the settings component."""

    def list_varieties(self, context: SecurityContext) -> list[NamedCatalogRecord]: ...

    def create_variety(
        self, context: SecurityContext, name: str, *, correlation_id: str
    ) -> NamedCatalogRecord: ...

    def archive_variety(
        self, context: SecurityContext, record_id: str, *, correlation_id: str
    ) -> NamedCatalogRecord: ...

    def list_pallet_sizes(self, context: SecurityContext) -> list[PalletSizeRecord]: ...

    def create_pallet_size(
        self, context: SecurityContext, size: object, *, correlation_id: str
    ) -> PalletSizeRecord: ...

    def archive_pallet_size(
        self, context: SecurityContext, record_id: str, *, correlation_id: str
    ) -> PalletSizeRecord: ...

    def list_transport_options(self, context: SecurityContext) -> list[TransportOptionRecord]: ...

    def create_transport_option(
        self,
        context: SecurityContext,
        name: str,
        *,
        pallet_capacity: object,
        correlation_id: str,
    ) -> TransportOptionRecord: ...

    def archive_transport_option(
        self, context: SecurityContext, record_id: str, *, correlation_id: str
    ) -> TransportOptionRecord: ...

    def list_teams(self, context: SecurityContext) -> list[NamedCatalogRecord]: ...

    def create_team(
        self, context: SecurityContext, name: str, *, correlation_id: str
    ) -> NamedCatalogRecord: ...

    def archive_team(
        self, context: SecurityContext, record_id: str, *, correlation_id: str
    ) -> NamedCatalogRecord: ...

    def list_service_types(self, context: SecurityContext) -> list[NamedCatalogRecord]: ...

    def create_service_type(
        self, context: SecurityContext, name: str, *, correlation_id: str
    ) -> NamedCatalogRecord: ...

    def archive_service_type(
        self, context: SecurityContext, record_id: str, *, correlation_id: str
    ) -> NamedCatalogRecord: ...


class CatalogSettingsUI(Protocol):
    """Small Streamlit-compatible rendering boundary."""

    def subheader(self, body: str) -> None: ...

    def write(self, body: str) -> None: ...

    def info(self, body: str) -> None: ...

    def text_input(self, label: str, *, key: str) -> str: ...

    def number_input(
        self,
        label: str,
        *,
        min_value: int,
        step: int,
        value: None,
        key: str,
    ) -> int | None: ...

    def selectbox(
        self,
        label: str,
        options: Sequence[str],
        *,
        format_func: Callable[[str], str],
        index: None,
        placeholder: str,
        key: str,
    ) -> str | None: ...

    def button(self, label: str, *, key: str) -> bool: ...

    def success(self, body: str) -> None: ...

    def error(self, body: str) -> None: ...


CorrelationIdFactory = Callable[[], str]
CatalogRecordT = TypeVar("CatalogRecordT")
_READ_ERROR = "We couldn't load this catalog. Please try again."
_WRITE_ERROR = "We couldn't update this catalog. Please try again."


def render_operational_catalog_settings(
    context: SecurityContext,
    *,
    service: CatalogServiceUI,
    ui: CatalogSettingsUI,
    correlation_id_factory: CorrelationIdFactory,
) -> None:
    """Render active values from the sealed organization context without shared caching."""

    _render_named(
        context,
        service=service,
        ui=ui,
        kind="variety",
        heading="Varieties",
        empty="No active varieties.",
        list_values=service.list_varieties,
        create=service.create_variety,
        archive=service.archive_variety,
        correlation_id_factory=correlation_id_factory,
    )
    _render_pallet_sizes(
        context,
        service=service,
        ui=ui,
        correlation_id_factory=correlation_id_factory,
    )
    _render_transport_options(
        context,
        service=service,
        ui=ui,
        correlation_id_factory=correlation_id_factory,
    )
    _render_named(
        context,
        service=service,
        ui=ui,
        kind="team",
        heading="Teams",
        empty="No active teams.",
        list_values=service.list_teams,
        create=service.create_team,
        archive=service.archive_team,
        correlation_id_factory=correlation_id_factory,
    )
    _render_named(
        context,
        service=service,
        ui=ui,
        kind="service_type",
        heading="Service types",
        empty="No active service types.",
        list_values=service.list_service_types,
        create=service.create_service_type,
        archive=service.archive_service_type,
        correlation_id_factory=correlation_id_factory,
    )


def _load_owned(
    context: SecurityContext,
    ui: CatalogSettingsUI,
    list_values: Callable[[SecurityContext], Sequence[CatalogRecordT]],
) -> list[CatalogRecordT] | None:
    try:
        records = list(list_values(context))
    except Exception:
        ui.error(_READ_ERROR)
        return None
    if any(
        getattr(record, "organization_id", None) != context.organization_id
        or getattr(record, "status", None) != "active"
        for record in records
    ):
        ui.error(_READ_ERROR)
        return None
    return records


def _render_named(
    context: SecurityContext,
    *,
    service: CatalogServiceUI,
    ui: CatalogSettingsUI,
    kind: str,
    heading: str,
    empty: str,
    list_values: Callable[[SecurityContext], list[NamedCatalogRecord]],
    create: Callable[..., NamedCatalogRecord],
    archive: Callable[..., NamedCatalogRecord],
    correlation_id_factory: CorrelationIdFactory,
) -> None:
    del service
    ui.subheader(heading)
    loaded = _load_owned(context, ui, list_values)
    if loaded is None:
        return
    records = [record for record in loaded if isinstance(record, NamedCatalogRecord)]
    if records:
        for record in records:
            ui.write(record.name)
    else:
        ui.info(empty)
    if context.role is not Role.ADMIN:
        return

    prefix = f"catalog.{context.organization_id}.{kind}"
    name = ui.text_input(f"New {heading.removesuffix('s').lower()} name", key=f"{prefix}.name")
    if ui.button("Create", key=f"{prefix}.create"):
        _mutate(ui, lambda: create(context, name, correlation_id=correlation_id_factory()))
    _render_archive(
        context,
        ui=ui,
        prefix=prefix,
        records=records,
        labels={record.id: record.name for record in records},
        archive=archive,
        correlation_id_factory=correlation_id_factory,
    )


def _render_pallet_sizes(
    context: SecurityContext,
    *,
    service: CatalogServiceUI,
    ui: CatalogSettingsUI,
    correlation_id_factory: CorrelationIdFactory,
) -> None:
    ui.subheader("Pallet sizes")
    loaded = _load_owned(context, ui, service.list_pallet_sizes)
    if loaded is None:
        return
    records = [record for record in loaded if isinstance(record, PalletSizeRecord)]
    if records:
        for record in records:
            ui.write(f"{record.size} pallets")
    else:
        ui.info("No active pallet sizes.")
    if context.role is not Role.ADMIN:
        return

    prefix = f"catalog.{context.organization_id}.pallet_size"
    size = ui.number_input(
        "New pallet size",
        min_value=1,
        step=1,
        value=None,
        key=f"{prefix}.size",
    )
    if ui.button("Create", key=f"{prefix}.create"):
        _mutate(
            ui,
            lambda: service.create_pallet_size(
                context, size, correlation_id=correlation_id_factory()
            ),
        )
    _render_archive(
        context,
        ui=ui,
        prefix=prefix,
        records=records,
        labels={record.id: f"{record.size} pallets" for record in records},
        archive=service.archive_pallet_size,
        correlation_id_factory=correlation_id_factory,
    )


def _render_transport_options(
    context: SecurityContext,
    *,
    service: CatalogServiceUI,
    ui: CatalogSettingsUI,
    correlation_id_factory: CorrelationIdFactory,
) -> None:
    ui.subheader("Transport options")
    loaded = _load_owned(context, ui, service.list_transport_options)
    if loaded is None:
        return
    records = [record for record in loaded if isinstance(record, TransportOptionRecord)]
    if records:
        for record in records:
            ui.write(f"{record.name} — {record.pallet_capacity} pallets")
    else:
        ui.info("No active transport options.")
    if context.role is not Role.ADMIN:
        return

    prefix = f"catalog.{context.organization_id}.transport_option"
    name = ui.text_input("New transport option name", key=f"{prefix}.name")
    capacity = ui.number_input(
        "Pallet capacity",
        min_value=0,
        step=1,
        value=None,
        key=f"{prefix}.pallet_capacity",
    )
    if ui.button("Create", key=f"{prefix}.create"):
        _mutate(
            ui,
            lambda: service.create_transport_option(
                context,
                name,
                pallet_capacity=capacity,
                correlation_id=correlation_id_factory(),
            ),
        )
    _render_archive(
        context,
        ui=ui,
        prefix=prefix,
        records=records,
        labels={
            record.id: f"{record.name} — {record.pallet_capacity} pallets" for record in records
        },
        archive=service.archive_transport_option,
        correlation_id_factory=correlation_id_factory,
    )


def _render_archive(
    context: SecurityContext,
    *,
    ui: CatalogSettingsUI,
    prefix: str,
    records: Sequence[object],
    labels: dict[str, str],
    archive: Callable[..., object],
    correlation_id_factory: CorrelationIdFactory,
) -> None:
    if not records:
        return
    allowed_ids = tuple(record.id for record in records)  # type: ignore[attr-defined]
    selected = ui.selectbox(
        "Active value to archive",
        allowed_ids,
        format_func=labels.__getitem__,
        index=None,
        placeholder="Select an active value",
        key=f"{prefix}.archive_id",
    )
    if ui.button("Archive", key=f"{prefix}.archive"):
        if selected not in allowed_ids:
            ui.error(_WRITE_ERROR)
            return
        _mutate(
            ui,
            lambda: archive(
                context,
                selected,
                correlation_id=correlation_id_factory(),
            ),
        )


def _mutate(ui: CatalogSettingsUI, operation: Callable[[], object]) -> None:
    try:
        operation()
    except Exception:
        ui.error(_WRITE_ERROR)
    else:
        ui.success("Catalog updated.")
