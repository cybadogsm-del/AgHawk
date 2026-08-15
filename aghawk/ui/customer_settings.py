from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any, Protocol

from turfhelm.customers.repository import ContactRecord, CustomerRecord, SiteRecord
from turfhelm.security.context import Role, SecurityContext
from turfhelm.ui.choice_field import ChoiceMode, ChoiceOption, render_choice_field


class CustomerSettingsService(Protocol):
    """Customer operations consumed by the settings presentation component."""

    def list_customers(self, context: SecurityContext) -> list[CustomerRecord]: ...

    def list_sites(self, context: SecurityContext, customer_id: str) -> list[SiteRecord]: ...

    def list_contacts(
        self,
        context: SecurityContext,
        customer_id: str,
        *,
        site_id: str | None = None,
    ) -> list[ContactRecord]: ...

    def create_customer(
        self,
        context: SecurityContext,
        name: str,
        *,
        correlation_id: str,
    ) -> CustomerRecord: ...

    def create_site(
        self,
        context: SecurityContext,
        customer_id: str,
        address: str,
        *,
        correlation_id: str,
    ) -> SiteRecord: ...

    def create_contact(
        self,
        context: SecurityContext,
        customer_id: str,
        name: str,
        phone: str,
        *,
        site_id: str | None = None,
        correlation_id: str,
    ) -> ContactRecord: ...

    def archive_customer(
        self,
        context: SecurityContext,
        customer_id: str,
        *,
        correlation_id: str,
    ) -> CustomerRecord: ...

    def archive_site(
        self,
        context: SecurityContext,
        customer_id: str,
        site_id: str,
        *,
        correlation_id: str,
    ) -> SiteRecord: ...

    def archive_contact(
        self,
        context: SecurityContext,
        customer_id: str,
        contact_id: str,
        *,
        correlation_id: str,
    ) -> ContactRecord: ...


class CustomerSettingsUI(Protocol):
    """Small Streamlit-compatible boundary used by customer settings."""

    def subheader(self, body: str) -> None: ...

    def caption(self, body: str) -> None: ...

    def info(self, body: str) -> None: ...

    def radio(
        self,
        label: str,
        options: Sequence[str],
        *,
        key: str,
        horizontal: bool,
    ) -> str: ...

    def selectbox(
        self,
        label: str,
        options: Sequence[Any],
        *,
        key: str,
        index: None,
        placeholder: str,
        format_func: Callable[[Any], str],
    ) -> Any | None: ...

    def text_input(self, label: str, *, key: str) -> str: ...

    def button(self, label: str, *, key: str) -> bool: ...

    def success(self, body: str) -> None: ...

    def error(self, body: str) -> None: ...


CorrelationIdFactory = Callable[[], str]
_LOAD_ERROR = "We couldn't load customer settings. Please try again."
_UPDATE_ERROR = "We couldn't update customer settings. Please try again."


def render_customer_settings(
    context: SecurityContext,
    *,
    service: CustomerSettingsService,
    ui: CustomerSettingsUI,
    correlation_id_factory: CorrelationIdFactory,
) -> None:
    """Render an organization-scoped customer, site, and contact hierarchy."""

    ui.subheader("Customers, sites, and contacts")
    try:
        customers = service.list_customers(context)
        customer_by_id = _validated_customers(customers, context.organization_id)
    except Exception:
        ui.error(_LOAD_ERROR)
        return

    key_root = f"customer-settings.{context.organization_id}"
    if not customers:
        if context.role is Role.ADMIN:
            ui.info("No customers have been configured. Add one to get started.")
        else:
            ui.info("No customers have been configured.")
            return

    customer_key = f"{key_root}.customer"
    if context.role is Role.ADMIN:
        customer_selection = render_choice_field(
            ui,
            label="Customer",
            key=customer_key,
            existing_options=_customer_options(customers),
        )
        if customer_selection.mode is ChoiceMode.ADD_NEW:
            if ui.button("Create customer", key=f"{customer_key}.create"):
                if customer_selection.value is None:
                    ui.error(_UPDATE_ERROR)
                else:
                    _create_customer(
                        context,
                        service,
                        ui,
                        str(customer_selection.value),
                        correlation_id_factory,
                    )
            return
        customer_id = _known_id(customer_selection.value, customer_by_id)
        if customer_selection.value is not None and customer_id is None:
            ui.error(_LOAD_ERROR)
            return
    else:
        customer_id = _select_existing(
            ui,
            label="Customer",
            key=f"{customer_key}.existing",
            options=_customer_options(customers),
        )
        selected_customer_id = customer_id
        customer_id = _known_id(selected_customer_id, customer_by_id)
        if selected_customer_id is not None and customer_id is None:
            ui.error(_LOAD_ERROR)
            return

    if customer_id is None:
        ui.info("Choose a customer to view its sites and contacts.")
        return

    if context.role is Role.ADMIN and ui.button(
        "Archive customer", key=f"{customer_key}.{customer_id}.archive"
    ):
        if _archive_customer(context, service, ui, customer_id, correlation_id_factory):
            return

    try:
        sites = service.list_sites(context, customer_id)
        site_by_id = _validated_sites(sites, context.organization_id, customer_id)
    except Exception:
        ui.error(_LOAD_ERROR)
        return

    if not sites:
        ui.info("No sites have been configured for this customer.")

    site_key = f"{key_root}.{customer_id}.site"
    if context.role is Role.ADMIN:
        site_selection = render_choice_field(
            ui,
            label="Site (optional for contacts)",
            key=site_key,
            existing_options=_site_options(sites),
        )
        if site_selection.mode is ChoiceMode.ADD_NEW:
            if ui.button("Create site", key=f"{site_key}.create"):
                if site_selection.value is None:
                    ui.error(_UPDATE_ERROR)
                else:
                    _create_site(
                        context,
                        service,
                        ui,
                        customer_id,
                        str(site_selection.value),
                        correlation_id_factory,
                    )
            return
        site_id = _known_id(site_selection.value, site_by_id)
        if site_selection.value is not None and site_id is None:
            ui.error(_LOAD_ERROR)
            return
    else:
        site_id = _select_existing(
            ui,
            label="Site (optional)",
            key=f"{site_key}.existing",
            options=_site_options(sites),
        )
        selected_site_id = site_id
        site_id = _known_id(selected_site_id, site_by_id)
        if selected_site_id is not None and site_id is None:
            ui.error(_LOAD_ERROR)
            return

    if (
        context.role is Role.ADMIN
        and site_id is not None
        and ui.button("Archive site", key=f"{site_key}.{site_id}.archive")
    ):
        if _archive_site(context, service, ui, customer_id, site_id, correlation_id_factory):
            return

    try:
        contacts = service.list_contacts(context, customer_id, site_id=site_id)
        contact_by_id = _validated_contacts(contacts, context.organization_id, customer_id, site_id)
    except Exception:
        ui.error(_LOAD_ERROR)
        return

    if not contacts:
        ui.info("No contacts have been configured for this selection.")

    site_scope = site_id if site_id is not None else "all"
    contact_key = f"{key_root}.{customer_id}.{site_scope}.contact"
    if context.role is not Role.ADMIN:
        for item in contacts:
            ui.caption(_contact_label(item))
        return

    contact_selection = render_choice_field(
        ui,
        label="Contact",
        key=contact_key,
        existing_options=_contact_options(contacts),
    )
    if contact_selection.mode is ChoiceMode.ADD_NEW:
        phone = ui.text_input("Phone", key=f"{contact_key}.phone").strip()
        if ui.button("Create contact", key=f"{contact_key}.create"):
            if contact_selection.value is None or not phone:
                ui.error(_UPDATE_ERROR)
            else:
                _create_contact(
                    context,
                    service,
                    ui,
                    customer_id,
                    str(contact_selection.value),
                    phone,
                    site_id,
                    correlation_id_factory,
                )
        return

    contact_id = _known_id(contact_selection.value, contact_by_id)
    if contact_selection.value is not None and contact_id is None:
        ui.error(_LOAD_ERROR)
        return
    if contact_id is not None and ui.button("Archive contact", key=f"{contact_key}.archive"):
        _archive_contact(context, service, ui, customer_id, contact_id, correlation_id_factory)


def _select_existing(
    ui: CustomerSettingsUI,
    *,
    label: str,
    key: str,
    options: Sequence[ChoiceOption[str]],
) -> str | None:
    selected = ui.selectbox(
        label,
        options,
        key=key,
        index=None,
        placeholder="Choose an option",
        format_func=lambda item: item.label,
    )
    return None if selected is None else str(selected.value)


def _known_id(value: object, records: Mapping[str, object]) -> str | None:
    if not isinstance(value, str) or value not in records:
        return None
    return value


def _validated_customers(
    records: Iterable[CustomerRecord], organization_id: str
) -> dict[str, CustomerRecord]:
    result: dict[str, CustomerRecord] = {}
    for record in records:
        if (
            record.organization_id != organization_id
            or record.status != "active"
            or record.id in result
        ):
            raise ValueError("invalid customer result")
        result[record.id] = record
    return result


def _validated_sites(
    records: Iterable[SiteRecord], organization_id: str, customer_id: str
) -> dict[str, SiteRecord]:
    result: dict[str, SiteRecord] = {}
    for record in records:
        if (
            record.organization_id != organization_id
            or record.customer_id != customer_id
            or record.status != "active"
            or record.id in result
        ):
            raise ValueError("invalid site result")
        result[record.id] = record
    return result


def _validated_contacts(
    records: Iterable[ContactRecord],
    organization_id: str,
    customer_id: str,
    site_id: str | None,
) -> dict[str, ContactRecord]:
    result: dict[str, ContactRecord] = {}
    for record in records:
        wrong_site = site_id is not None and record.site_id != site_id
        if (
            record.organization_id != organization_id
            or record.customer_id != customer_id
            or wrong_site
            or record.status != "active"
            or record.id in result
        ):
            raise ValueError("invalid contact result")
        result[record.id] = record
    return result


def _customer_options(records: Iterable[CustomerRecord]) -> tuple[ChoiceOption[str], ...]:
    return tuple(ChoiceOption(record.id, record.name) for record in records)


def _site_options(records: Iterable[SiteRecord]) -> tuple[ChoiceOption[str], ...]:
    return tuple(ChoiceOption(record.id, record.address) for record in records)


def _contact_options(records: Iterable[ContactRecord]) -> tuple[ChoiceOption[str], ...]:
    return tuple(ChoiceOption(record.id, _contact_label(record)) for record in records)


def _contact_label(record: ContactRecord) -> str:
    return f"{record.name} — {record.phone}"


def _create_customer(
    context: SecurityContext,
    service: CustomerSettingsService,
    ui: CustomerSettingsUI,
    name: str,
    correlation_id_factory: CorrelationIdFactory,
) -> None:
    try:
        service.create_customer(context, name, correlation_id=correlation_id_factory())
    except Exception:
        ui.error(_UPDATE_ERROR)
    else:
        ui.success("Customer created.")


def _create_site(
    context: SecurityContext,
    service: CustomerSettingsService,
    ui: CustomerSettingsUI,
    customer_id: str,
    address: str,
    correlation_id_factory: CorrelationIdFactory,
) -> None:
    try:
        service.create_site(
            context,
            customer_id,
            address,
            correlation_id=correlation_id_factory(),
        )
    except Exception:
        ui.error(_UPDATE_ERROR)
    else:
        ui.success("Site created.")


def _create_contact(
    context: SecurityContext,
    service: CustomerSettingsService,
    ui: CustomerSettingsUI,
    customer_id: str,
    name: str,
    phone: str,
    site_id: str | None,
    correlation_id_factory: CorrelationIdFactory,
) -> None:
    try:
        service.create_contact(
            context,
            customer_id,
            name,
            phone,
            site_id=site_id,
            correlation_id=correlation_id_factory(),
        )
    except Exception:
        ui.error(_UPDATE_ERROR)
    else:
        ui.success("Contact created.")


def _archive_customer(
    context: SecurityContext,
    service: CustomerSettingsService,
    ui: CustomerSettingsUI,
    customer_id: str,
    correlation_id_factory: CorrelationIdFactory,
) -> bool:
    try:
        service.archive_customer(context, customer_id, correlation_id=correlation_id_factory())
    except Exception:
        ui.error(_UPDATE_ERROR)
        return False
    ui.success("Customer archived.")
    return True


def _archive_site(
    context: SecurityContext,
    service: CustomerSettingsService,
    ui: CustomerSettingsUI,
    customer_id: str,
    site_id: str,
    correlation_id_factory: CorrelationIdFactory,
) -> bool:
    try:
        service.archive_site(
            context,
            customer_id,
            site_id,
            correlation_id=correlation_id_factory(),
        )
    except Exception:
        ui.error(_UPDATE_ERROR)
        return False
    ui.success("Site archived.")
    return True


def _archive_contact(
    context: SecurityContext,
    service: CustomerSettingsService,
    ui: CustomerSettingsUI,
    customer_id: str,
    contact_id: str,
    correlation_id_factory: CorrelationIdFactory,
) -> None:
    try:
        service.archive_contact(
            context,
            customer_id,
            contact_id,
            correlation_id=correlation_id_factory(),
        )
    except Exception:
        ui.error(_UPDATE_ERROR)
    else:
        ui.success("Contact archived.")
