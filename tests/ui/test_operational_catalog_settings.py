from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

import pytest

from turfhelm.catalogs.repository import (
    NamedCatalogRecord,
    PalletSizeRecord,
    TransportOptionRecord,
)
from turfhelm.security.context import Role, SecurityContext
from turfhelm.ui.operational_catalog_settings import render_operational_catalog_settings


def context(*, organization_id: str = "org-a", role: Role = Role.FARM_STAFF) -> SecurityContext:
    return SecurityContext._from_active_membership(
        user_id="user-a",
        oidc_subject="oidc|user-a",
        organization_id=organization_id,
        role=role,
        proof=b"sealed",
    )


@dataclass
class FakeService:
    organization_id: str = "org-a"
    calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = field(default_factory=list)
    varieties: list[NamedCatalogRecord] = field(default_factory=list)
    pallet_sizes: list[PalletSizeRecord] = field(default_factory=list)
    transport_options: list[TransportOptionRecord] = field(default_factory=list)
    teams: list[NamedCatalogRecord] = field(default_factory=list)
    service_types: list[NamedCatalogRecord] = field(default_factory=list)

    def _list(self, method: str, active_context: SecurityContext) -> list[Any]:
        self.calls.append((method, (active_context,), {}))
        return getattr(self, method.removeprefix("list_"))

    def list_varieties(self, active_context: SecurityContext) -> list[NamedCatalogRecord]:
        return self._list("list_varieties", active_context)

    def list_pallet_sizes(self, active_context: SecurityContext) -> list[PalletSizeRecord]:
        return self._list("list_pallet_sizes", active_context)

    def list_transport_options(
        self, active_context: SecurityContext
    ) -> list[TransportOptionRecord]:
        return self._list("list_transport_options", active_context)

    def list_teams(self, active_context: SecurityContext) -> list[NamedCatalogRecord]:
        return self._list("list_teams", active_context)

    def list_service_types(self, active_context: SecurityContext) -> list[NamedCatalogRecord]:
        return self._list("list_service_types", active_context)

    def __getattr__(self, name: str) -> Callable[..., Any]:
        if name.startswith(("create_", "archive_")):

            def mutation(*args: Any, **kwargs: Any) -> None:
                self.calls.append((name, args, kwargs))

            return mutation
        raise AttributeError(name)


@dataclass
class FakeUI:
    pressed_keys: set[str] = field(default_factory=set)
    text_values: dict[str, str] = field(default_factory=dict)
    number_values: dict[str, int | None] = field(default_factory=dict)
    selected_values: dict[str, str | None] = field(default_factory=dict)
    calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = field(default_factory=list)

    def subheader(self, body: str) -> None:
        self.calls.append(("subheader", (body,), {}))

    def write(self, body: str) -> None:
        self.calls.append(("write", (body,), {}))

    def info(self, body: str) -> None:
        self.calls.append(("info", (body,), {}))

    def text_input(self, label: str, *, key: str) -> str:
        self.calls.append(("text_input", (label,), {"key": key}))
        return self.text_values.get(key, "")

    def number_input(
        self, label: str, *, min_value: int, step: int, value: None, key: str
    ) -> int | None:
        self.calls.append(
            (
                "number_input",
                (label,),
                {"min_value": min_value, "step": step, "value": value, "key": key},
            )
        )
        return self.number_values.get(key)

    def selectbox(
        self,
        label: str,
        options: Sequence[str],
        *,
        format_func: Callable[[str], str],
        index: None,
        placeholder: str,
        key: str,
    ) -> str | None:
        self.calls.append(
            (
                "selectbox",
                (label, tuple(options)),
                {
                    "format_func": format_func,
                    "index": index,
                    "placeholder": placeholder,
                    "key": key,
                },
            )
        )
        return self.selected_values.get(key)

    def button(self, label: str, *, key: str) -> bool:
        self.calls.append(("button", (label,), {"key": key}))
        return key in self.pressed_keys

    def success(self, body: str) -> None:
        self.calls.append(("success", (body,), {}))

    def error(self, body: str) -> None:
        self.calls.append(("error", (body,), {}))


def named(record_id: str, name: str, *, organization_id: str = "org-a") -> NamedCatalogRecord:
    return NamedCatalogRecord(record_id, organization_id, name, "active")


def test_all_active_roles_view_each_catalog_and_empty_sections_without_mutation_widgets() -> None:
    active_context = context(role=Role.DRIVER)
    service = FakeService(
        varieties=[named("var-1", "Rye")],
        pallet_sizes=[PalletSizeRecord("pal-1", "org-a", 24, "active")],
        transport_options=[TransportOptionRecord("tr-1", "org-a", "Rigid", 0, "active")],
    )
    ui = FakeUI()

    render_operational_catalog_settings(
        active_context,
        service=service,
        ui=ui,
        correlation_id_factory=lambda: "unused",
    )

    assert [call[0] for call in service.calls] == [
        "list_varieties",
        "list_pallet_sizes",
        "list_transport_options",
        "list_teams",
        "list_service_types",
    ]
    rendered = [
        args[0] for name, args, _kwargs in ui.calls if name in {"subheader", "write", "info"}
    ]
    assert "Varieties" in rendered
    assert "Rye" in rendered
    assert "24 pallets" in rendered
    assert "Rigid — 0 pallets" in rendered
    assert "No active teams." in rendered
    assert "No active service types." in rendered
    assert not any(
        name in {"text_input", "number_input", "selectbox", "button"}
        for name, _args, _kwargs in ui.calls
    )


@pytest.mark.parametrize("role", [role for role in Role if role is not Role.ADMIN])
def test_every_non_admin_role_has_read_only_catalogs(role: Role) -> None:
    ui = FakeUI()

    render_operational_catalog_settings(
        context(role=role),
        service=FakeService(),
        ui=ui,
        correlation_id_factory=lambda: "unused",
    )

    assert not any(
        name in {"text_input", "number_input", "selectbox", "button"}
        for name, _args, _kwargs in ui.calls
    )


def test_admin_create_controls_pass_raw_fixed_fields_context_and_fresh_correlation_ids() -> None:
    active_context = context(role=Role.ADMIN)
    pressed = {
        f"catalog.org-a.{kind}.create"
        for kind in ("variety", "pallet_size", "transport_option", "team", "service_type")
    }
    ui = FakeUI(
        pressed_keys=pressed,
        text_values={
            "catalog.org-a.variety.name": "  Rye  ",
            "catalog.org-a.transport_option.name": "Rigid",
            "catalog.org-a.team.name": "North",
            "catalog.org-a.service_type.name": "Install",
        },
        number_values={
            "catalog.org-a.pallet_size.size": 24,
            "catalog.org-a.transport_option.pallet_capacity": 0,
        },
    )
    correlations = iter(f"correlation-{number}" for number in range(1, 6))
    service = FakeService()

    render_operational_catalog_settings(
        active_context,
        service=service,
        ui=ui,
        correlation_id_factory=lambda: next(correlations),
    )

    mutations = [call for call in service.calls if call[0].startswith("create_")]
    assert mutations == [
        ("create_variety", (active_context, "  Rye  "), {"correlation_id": "correlation-1"}),
        ("create_pallet_size", (active_context, 24), {"correlation_id": "correlation-2"}),
        (
            "create_transport_option",
            (active_context, "Rigid"),
            {"pallet_capacity": 0, "correlation_id": "correlation-3"},
        ),
        ("create_team", (active_context, "North"), {"correlation_id": "correlation-4"}),
        ("create_service_type", (active_context, "Install"), {"correlation_id": "correlation-5"}),
    ]
    number_calls = [call for call in ui.calls if call[0] == "number_input"]
    assert number_calls[0][2] == {
        "min_value": 1,
        "step": 1,
        "value": None,
        "key": "catalog.org-a.pallet_size.size",
    }
    assert number_calls[1][2] == {
        "min_value": 0,
        "step": 1,
        "value": None,
        "key": "catalog.org-a.transport_option.pallet_capacity",
    }
    assert len([call for call in ui.calls if call[0] == "success"]) == 5


def test_archive_options_and_selected_id_come_only_from_returned_records() -> None:
    active_context = context(role=Role.ADMIN)
    service = FakeService(varieties=[named("var-1", "Rye"), named("var-2", "Fescue")])
    ui = FakeUI(
        pressed_keys={"catalog.org-a.variety.archive"},
        selected_values={"catalog.org-a.variety.archive_id": "var-2"},
    )

    render_operational_catalog_settings(
        active_context,
        service=service,
        ui=ui,
        correlation_id_factory=lambda: "archive-correlation",
    )

    select = next(call for call in ui.calls if call[0] == "selectbox")
    assert select[1][1] == ("var-1", "var-2")
    assert select[2]["format_func"]("var-2") == "Fescue"
    assert (
        "archive_variety",
        (active_context, "var-2"),
        {"correlation_id": "archive-correlation"},
    ) in service.calls


def test_unreturned_archive_id_is_rejected_before_service_and_correlation_factory() -> None:
    service = FakeService(varieties=[named("var-1", "Rye")])
    ui = FakeUI(
        pressed_keys={"catalog.org-a.variety.archive"},
        selected_values={"catalog.org-a.variety.archive_id": "other-org-id"},
    )
    correlation_requested = False

    def correlation_id() -> str:
        nonlocal correlation_requested
        correlation_requested = True
        return "must-not-be-used"

    render_operational_catalog_settings(
        context(role=Role.ADMIN),
        service=service,
        ui=ui,
        correlation_id_factory=correlation_id,
    )

    assert not any(call[0] == "archive_variety" for call in service.calls)
    assert correlation_requested is False
    assert ("error", ("We couldn't update this catalog. Please try again.",), {}) in ui.calls


def test_mismatched_organization_record_fails_closed_for_section() -> None:
    ui = FakeUI()

    render_operational_catalog_settings(
        context(role=Role.ADMIN),
        service=FakeService(varieties=[named("other-id", "Secret", organization_id="org-b")]),
        ui=ui,
        correlation_id_factory=lambda: "unused",
    )

    assert "Secret" not in repr(ui.calls)
    assert not any(
        kwargs.get("key", "").startswith("catalog.org-a.variety")
        for _name, _args, kwargs in ui.calls
    )
    assert ("error", ("We couldn't load this catalog. Please try again.",), {}) in ui.calls


def test_widget_keys_are_disjoint_between_organizations_and_include_catalog_kind() -> None:
    ui_a = FakeUI()
    ui_b = FakeUI()

    render_operational_catalog_settings(
        context(organization_id="org-a", role=Role.ADMIN),
        service=FakeService(organization_id="org-a"),
        ui=ui_a,
        correlation_id_factory=lambda: "unused-a",
    )
    render_operational_catalog_settings(
        context(organization_id="org-b", role=Role.ADMIN),
        service=FakeService(organization_id="org-b"),
        ui=ui_b,
        correlation_id_factory=lambda: "unused-b",
    )

    keys_a = {kwargs["key"] for _name, _args, kwargs in ui_a.calls if "key" in kwargs}
    keys_b = {kwargs["key"] for _name, _args, kwargs in ui_b.calls if "key" in kwargs}
    assert keys_a
    assert keys_b
    assert all(key.startswith("catalog.org-a.") for key in keys_a)
    assert all(key.startswith("catalog.org-b.") for key in keys_b)
    assert keys_a.isdisjoint(keys_b)


def test_service_failures_show_only_generic_safe_errors() -> None:
    class FailingService(FakeService):
        def list_varieties(self, active_context: SecurityContext) -> list[NamedCatalogRecord]:
            raise RuntimeError("SELECT secret FROM memberships")

        def create_team(self, *args: Any, **kwargs: Any) -> None:
            raise RuntimeError("duplicate internal row team_private")

    ui = FakeUI(pressed_keys={"catalog.org-a.team.create"})

    render_operational_catalog_settings(
        context(role=Role.ADMIN),
        service=FailingService(),
        ui=ui,
        correlation_id_factory=lambda: "correlation",
    )

    errors = [args[0] for name, args, _kwargs in ui.calls if name == "error"]
    assert errors == [
        "We couldn't load this catalog. Please try again.",
        "We couldn't update this catalog. Please try again.",
    ]
    assert "secret" not in repr(errors).lower()
    assert "select" not in repr(errors).lower()
