from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

import pytest

from turfhelm.customers.repository import ContactRecord, CustomerRecord, SiteRecord
from turfhelm.security.context import Role, SecurityContext
from turfhelm.ui.choice_field import ChoiceOption
from turfhelm.ui.customer_settings import render_customer_settings


def context(*, organization_id: str = "org-a", role: Role = Role.FARM_STAFF) -> SecurityContext:
    return SecurityContext._from_active_membership(
        user_id="user-a",
        oidc_subject="oidc|user-a",
        organization_id=organization_id,
        role=role,
        proof=b"sealed",
    )


def customer(customer_id: str = "customer-a", *, organization_id: str = "org-a") -> CustomerRecord:
    return CustomerRecord(customer_id, organization_id, "Acme", "active")


def site(
    site_id: str = "site-a",
    *,
    organization_id: str = "org-a",
    customer_id: str = "customer-a",
) -> SiteRecord:
    return SiteRecord(site_id, organization_id, customer_id, "10 Main St", "active")


def contact(
    contact_id: str = "contact-a",
    *,
    organization_id: str = "org-a",
    customer_id: str = "customer-a",
    site_id: str | None = "site-a",
) -> ContactRecord:
    return ContactRecord(
        contact_id, organization_id, customer_id, site_id, "Alex", "555-0100", "active"
    )


@dataclass
class FakeService:
    customers: list[CustomerRecord] = field(default_factory=list)
    sites: list[SiteRecord] = field(default_factory=list)
    contacts: list[ContactRecord] = field(default_factory=list)
    calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = field(default_factory=list)

    def list_customers(self, active_context: SecurityContext) -> list[CustomerRecord]:
        self.calls.append(("list_customers", (active_context,), {}))
        return self.customers

    def list_sites(self, active_context: SecurityContext, customer_id: str) -> list[SiteRecord]:
        self.calls.append(("list_sites", (active_context, customer_id), {}))
        return self.sites

    def list_contacts(
        self,
        active_context: SecurityContext,
        customer_id: str,
        *,
        site_id: str | None = None,
    ) -> list[ContactRecord]:
        self.calls.append(("list_contacts", (active_context, customer_id), {"site_id": site_id}))
        return self.contacts

    def create_customer(
        self, active_context: SecurityContext, name: str, *, correlation_id: str
    ) -> CustomerRecord:
        self.calls.append(
            ("create_customer", (active_context, name), {"correlation_id": correlation_id})
        )
        return customer()

    def create_site(
        self,
        active_context: SecurityContext,
        customer_id: str,
        address: str,
        *,
        correlation_id: str,
    ) -> SiteRecord:
        self.calls.append(
            (
                "create_site",
                (active_context, customer_id, address),
                {"correlation_id": correlation_id},
            )
        )
        return site()

    def create_contact(
        self,
        active_context: SecurityContext,
        customer_id: str,
        name: str,
        phone: str,
        *,
        site_id: str | None = None,
        correlation_id: str,
    ) -> ContactRecord:
        self.calls.append(
            (
                "create_contact",
                (active_context, customer_id, name, phone),
                {"site_id": site_id, "correlation_id": correlation_id},
            )
        )
        return contact(site_id=site_id)

    def archive_customer(
        self, active_context: SecurityContext, customer_id: str, *, correlation_id: str
    ) -> CustomerRecord:
        self.calls.append(
            ("archive_customer", (active_context, customer_id), {"correlation_id": correlation_id})
        )
        return customer(customer_id)

    def archive_site(
        self,
        active_context: SecurityContext,
        customer_id: str,
        site_id: str,
        *,
        correlation_id: str,
    ) -> SiteRecord:
        self.calls.append(
            (
                "archive_site",
                (active_context, customer_id, site_id),
                {"correlation_id": correlation_id},
            )
        )
        return site(site_id, customer_id=customer_id)

    def archive_contact(
        self,
        active_context: SecurityContext,
        customer_id: str,
        contact_id: str,
        *,
        correlation_id: str,
    ) -> ContactRecord:
        self.calls.append(
            (
                "archive_contact",
                (active_context, customer_id, contact_id),
                {"correlation_id": correlation_id},
            )
        )
        return contact(contact_id, customer_id=customer_id)


@dataclass
class FakeUI:
    modes: dict[str, str] = field(default_factory=dict)
    selections: dict[str, ChoiceOption[str] | None] = field(default_factory=dict)
    inputs: dict[str, str] = field(default_factory=dict)
    pressed_keys: set[str] = field(default_factory=set)
    calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = field(default_factory=list)

    def subheader(self, body: str) -> None:
        self.calls.append(("subheader", (body,), {}))

    def caption(self, body: str) -> None:
        self.calls.append(("caption", (body,), {}))

    def info(self, body: str) -> None:
        self.calls.append(("info", (body,), {}))

    def radio(
        self,
        label: str,
        options: Sequence[str],
        *,
        key: str,
        horizontal: bool,
    ) -> str:
        self.calls.append(
            ("radio", (label,), {"options": tuple(options), "key": key, "horizontal": horizontal})
        )
        return self.modes.get(key, "Choose existing")

    def selectbox(
        self,
        label: str,
        options: Sequence[ChoiceOption[str]],
        *,
        key: str,
        index: None,
        placeholder: str,
        format_func: Callable[[ChoiceOption[str]], str],
    ) -> ChoiceOption[str] | None:
        self.calls.append(
            (
                "selectbox",
                (label,),
                {
                    "options": tuple(options),
                    "labels": tuple(format_func(option) for option in options),
                    "key": key,
                    "index": index,
                    "placeholder": placeholder,
                },
            )
        )
        return self.selections.get(key)

    def text_input(self, label: str, *, key: str) -> str:
        self.calls.append(("text_input", (label,), {"key": key}))
        return self.inputs.get(key, "")

    def button(self, label: str, *, key: str) -> bool:
        self.calls.append(("button", (label,), {"key": key}))
        return key in self.pressed_keys

    def success(self, body: str) -> None:
        self.calls.append(("success", (body,), {}))

    def error(self, body: str) -> None:
        self.calls.append(("error", (body,), {}))


def test_staff_views_relationship_hierarchy_by_returned_ids_without_mutation_controls() -> None:
    active_context = context(role=Role.DRIVER)
    selected_customer = ChoiceOption("customer-a", "Acme")
    selected_site = ChoiceOption("site-a", "10 Main St")
    service = FakeService(customers=[customer()], sites=[site()], contacts=[contact()])
    ui = FakeUI(
        selections={
            "customer-settings.org-a.customer.existing": selected_customer,
            "customer-settings.org-a.customer-a.site.existing": selected_site,
        }
    )

    render_customer_settings(
        active_context, service=service, ui=ui, correlation_id_factory=lambda: "unused"
    )

    assert service.calls == [
        ("list_customers", (active_context,), {}),
        ("list_sites", (active_context, "customer-a"), {}),
        ("list_contacts", (active_context, "customer-a"), {"site_id": "site-a"}),
    ]
    assert ("caption", ("Alex — 555-0100",), {}) in ui.calls
    assert not any(name in {"radio", "text_input", "button"} for name, _args, _kw in ui.calls)


def test_admin_add_customer_shows_only_new_name_editor_and_does_not_load_children() -> None:
    active_context = context(role=Role.ADMIN)
    key = "customer-settings.org-a.customer"
    service = FakeService(customers=[customer()])
    ui = FakeUI(
        modes={f"{key}.mode": "Add new"},
        inputs={f"{key}.new": " New Customer "},
        pressed_keys={f"{key}.create"},
    )

    render_customer_settings(
        active_context,
        service=service,
        ui=ui,
        correlation_id_factory=lambda: "correlation-customer",
    )

    assert service.calls == [
        ("list_customers", (active_context,), {}),
        (
            "create_customer",
            (active_context, "New Customer"),
            {"correlation_id": "correlation-customer"},
        ),
    ]
    customer_value_calls = [
        call for call in ui.calls if call[2].get("key") in {f"{key}.existing", f"{key}.new"}
    ]
    assert [call[0] for call in customer_value_calls] == ["text_input"]


def test_admin_add_site_uses_selected_customer_and_no_duplicate_site_chooser() -> None:
    active_context = context(role=Role.ADMIN)
    customer_key = "customer-settings.org-a.customer"
    site_key = "customer-settings.org-a.customer-a.site"
    service = FakeService(customers=[customer()], sites=[site()])
    ui = FakeUI(
        modes={f"{customer_key}.mode": "Choose existing", f"{site_key}.mode": "Add new"},
        selections={f"{customer_key}.existing": ChoiceOption("customer-a", "Acme")},
        inputs={f"{site_key}.new": " 20 Broad St "},
        pressed_keys={f"{site_key}.create"},
    )

    render_customer_settings(
        active_context,
        service=service,
        ui=ui,
        correlation_id_factory=lambda: "correlation-site",
    )

    assert service.calls == [
        ("list_customers", (active_context,), {}),
        ("list_sites", (active_context, "customer-a"), {}),
        (
            "create_site",
            (active_context, "customer-a", "20 Broad St"),
            {"correlation_id": "correlation-site"},
        ),
    ]
    site_value_calls = [
        call
        for call in ui.calls
        if call[2].get("key") in {f"{site_key}.existing", f"{site_key}.new"}
    ]
    assert [call[0] for call in site_value_calls] == ["text_input"]


def test_admin_add_contact_uses_optional_returned_site_and_separate_phone_field() -> None:
    active_context = context(role=Role.ADMIN)
    customer_key = "customer-settings.org-a.customer"
    site_key = "customer-settings.org-a.customer-a.site"
    contact_key = "customer-settings.org-a.customer-a.site-a.contact"
    service = FakeService(customers=[customer()], sites=[site()], contacts=[contact()])
    ui = FakeUI(
        modes={
            f"{customer_key}.mode": "Choose existing",
            f"{site_key}.mode": "Choose existing",
            f"{contact_key}.mode": "Add new",
        },
        selections={
            f"{customer_key}.existing": ChoiceOption("customer-a", "Acme"),
            f"{site_key}.existing": ChoiceOption("site-a", "10 Main St"),
        },
        inputs={f"{contact_key}.new": " Alex Smith ", f"{contact_key}.phone": " 555-0123 "},
        pressed_keys={f"{contact_key}.create"},
    )

    render_customer_settings(
        active_context,
        service=service,
        ui=ui,
        correlation_id_factory=lambda: "correlation-contact",
    )

    assert service.calls[-1] == (
        "create_contact",
        (active_context, "customer-a", "Alex Smith", "555-0123"),
        {"site_id": "site-a", "correlation_id": "correlation-contact"},
    )
    contact_value_calls = [
        call
        for call in ui.calls
        if call[2].get("key") in {f"{contact_key}.existing", f"{contact_key}.new"}
    ]
    assert [call[0] for call in contact_value_calls] == ["text_input"]
    assert ("text_input", ("Phone",), {"key": f"{contact_key}.phone"}) in ui.calls


def test_admin_archive_targets_only_selected_records_returned_by_service() -> None:
    active_context = context(role=Role.ADMIN)
    customer_key = "customer-settings.org-a.customer"
    site_key = "customer-settings.org-a.customer-a.site"
    contact_key = "customer-settings.org-a.customer-a.site-a.contact"
    service = FakeService(customers=[customer()], sites=[site()], contacts=[contact()])
    ui = FakeUI(
        selections={
            f"{customer_key}.existing": ChoiceOption("customer-a", "Acme"),
            f"{site_key}.existing": ChoiceOption("site-a", "10 Main St"),
            f"{contact_key}.existing": ChoiceOption("contact-a", "Alex — 555-0100"),
        },
        pressed_keys={f"{contact_key}.archive"},
    )

    render_customer_settings(
        active_context,
        service=service,
        ui=ui,
        correlation_id_factory=lambda: "correlation-archive",
    )

    assert service.calls[-1] == (
        "archive_contact",
        (active_context, "customer-a", "contact-a"),
        {"correlation_id": "correlation-archive"},
    )


def test_empty_customer_state_guides_staff_and_admin_without_loading_children() -> None:
    for role, expected in [
        (Role.FARM_STAFF, "No customers have been configured."),
        (Role.ADMIN, "No customers have been configured. Add one to get started."),
    ]:
        service = FakeService()
        ui = FakeUI()
        active_context = context(role=role)

        render_customer_settings(
            active_context, service=service, ui=ui, correlation_id_factory=lambda: "unused"
        )

        assert service.calls == [("list_customers", (active_context,), {})]
        assert ("info", (expected,), {}) in ui.calls


@pytest.mark.parametrize("role", list(Role))
def test_cross_organization_customer_result_fails_closed(role: Role) -> None:
    ui = FakeUI()

    render_customer_settings(
        context(role=role),
        service=FakeService(customers=[customer(organization_id="org-b")]),
        ui=ui,
        correlation_id_factory=lambda: "unused",
    )

    assert ("error", ("We couldn't load customer settings. Please try again.",), {}) in ui.calls
    assert not any(name in {"selectbox", "text_input", "button"} for name, _a, _k in ui.calls)


@pytest.mark.parametrize("role", [Role.ADMIN, Role.DRIVER])
def test_unreturned_site_selection_fails_closed_without_loading_contacts(role: Role) -> None:
    active_context = context(role=role)
    customer_key = "customer-settings.org-a.customer"
    site_key = "customer-settings.org-a.customer-a.site"
    service = FakeService(customers=[customer()], sites=[site()])
    ui = FakeUI(
        selections={
            f"{customer_key}.existing": ChoiceOption("customer-a", "Acme"),
            f"{site_key}.existing": ChoiceOption("other-site", "Forged site"),
        }
    )

    render_customer_settings(
        active_context,
        service=service,
        ui=ui,
        correlation_id_factory=lambda: "unused",
    )

    assert [call[0] for call in service.calls] == ["list_customers", "list_sites"]
    assert ("error", ("We couldn't load customer settings. Please try again.",), {}) in ui.calls
    assert "list_contacts" not in repr(service.calls)


@pytest.mark.parametrize("role", [Role.ADMIN, Role.DRIVER])
def test_unreturned_customer_selection_fails_closed_without_loading_children(role: Role) -> None:
    active_context = context(role=role)
    service = FakeService(customers=[customer()])
    ui = FakeUI(
        selections={
            "customer-settings.org-a.customer.existing": ChoiceOption(
                "other-customer", "Forged customer"
            )
        }
    )

    render_customer_settings(
        active_context,
        service=service,
        ui=ui,
        correlation_id_factory=lambda: "unused",
    )

    assert [call[0] for call in service.calls] == ["list_customers"]
    assert ("error", ("We couldn't load customer settings. Please try again.",), {}) in ui.calls


def test_service_failure_is_generic_and_does_not_expose_details() -> None:
    class FailingService(FakeService):
        def list_customers(self, active_context: SecurityContext) -> list[CustomerRecord]:
            raise RuntimeError("SELECT secret FROM organizations")

    ui = FakeUI()

    render_customer_settings(
        context(role=Role.ADMIN),
        service=FailingService(),
        ui=ui,
        correlation_id_factory=lambda: "unused",
    )

    errors = [args[0] for name, args, _kwargs in ui.calls if name == "error"]
    assert errors == ["We couldn't load customer settings. Please try again."]
    assert "select" not in repr(errors).lower()
    assert not any(
        name in {"radio", "selectbox", "text_input", "button"} for name, _args, _kwargs in ui.calls
    )
