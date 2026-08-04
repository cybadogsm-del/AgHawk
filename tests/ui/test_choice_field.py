from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from turfhelm.ui.choice_field import (
    ChoiceMode,
    ChoiceOption,
    deduplicate_options,
    render_choice_field,
    reset_customer_dependents,
    reset_site_dependents,
)


@dataclass
class FakeChoiceUI:
    mode: str
    existing_value: ChoiceOption[str] | None = None
    new_value: str = ""
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    def radio(
        self,
        label: str,
        options: Sequence[str],
        *,
        key: str,
        horizontal: bool,
    ) -> str:
        self.calls.append(
            (
                "radio",
                {
                    "label": label,
                    "options": tuple(options),
                    "key": key,
                    "horizontal": horizontal,
                },
            )
        )
        return self.mode

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
                {
                    "label": label,
                    "options": tuple(options),
                    "key": key,
                    "index": index,
                    "placeholder": placeholder,
                    "labels": tuple(format_func(option) for option in options),
                },
            )
        )
        return self.existing_value

    def text_input(self, label: str, *, key: str) -> str:
        self.calls.append(("text_input", {"label": label, "key": key}))
        return self.new_value


def test_existing_options_are_deduplicated_by_submitted_value() -> None:
    options = [
        ChoiceOption(value="customer-1", label="Acme"),
        ChoiceOption(value="customer-1", label="Acme duplicate"),
        ChoiceOption(value="customer-2", label="Bravo"),
    ]

    assert deduplicate_options(options) == (
        ChoiceOption(value="customer-1", label="Acme"),
        ChoiceOption(value="customer-2", label="Bravo"),
    )


def test_choose_existing_renders_one_value_control_with_stable_keys() -> None:
    selected = ChoiceOption(value="customer-1", label="Acme")
    ui = FakeChoiceUI(mode="Choose existing", existing_value=selected)

    result = render_choice_field(
        ui,
        label="Customer",
        key="order.customer",
        existing_options=(selected, selected),
    )

    assert result.mode is ChoiceMode.CHOOSE_EXISTING
    assert result.value == "customer-1"
    assert [name for name, _details in ui.calls] == ["radio", "selectbox"]
    assert ui.calls[0][1]["key"] == "order.customer.mode"
    assert ui.calls[0][1]["options"] == ("Choose existing", "Add new")
    assert ui.calls[1][1]["key"] == "order.customer.existing"
    assert ui.calls[1][1]["options"] == (selected,)
    assert ui.calls[1][1]["index"] is None


def test_unselected_existing_control_returns_none_not_a_sentinel() -> None:
    ui = FakeChoiceUI(mode="Choose existing", existing_value=None)

    result = render_choice_field(
        ui,
        label="Site",
        key="order.site",
        existing_options=(),
    )

    assert result.value is None


def test_add_new_renders_only_text_value_control() -> None:
    ui = FakeChoiceUI(mode="Add new", new_value="  New customer  ")

    result = render_choice_field(
        ui,
        label="Customer",
        key="order.customer",
        existing_options=(),
    )

    assert result.mode is ChoiceMode.ADD_NEW
    assert result.value == "New customer"
    assert [name for name, _details in ui.calls] == ["radio", "text_input"]
    assert ui.calls[1][1]["key"] == "order.customer.new"


def test_customer_change_clears_site_and_contact_choice_state() -> None:
    state = {
        "order.customer.existing": "customer-2",
        "order.site.mode": "Add new",
        "order.site.existing": "site-1",
        "order.site.new": "New site",
        "order.contact.mode": "Choose existing",
        "order.contact.existing": "contact-1",
        "order.contact.new": "New contact",
        "unrelated": "keep",
    }

    reset_customer_dependents(
        state,
        site_key="order.site",
        contact_key="order.contact",
    )

    assert state == {
        "order.customer.existing": "customer-2",
        "unrelated": "keep",
    }


def test_site_change_clears_only_contact_choice_state() -> None:
    state = {
        "order.site.existing": "site-2",
        "order.contact.mode": "Add new",
        "order.contact.existing": "contact-1",
        "order.contact.new": "New contact",
        "unrelated": "keep",
    }

    reset_site_dependents(state, contact_key="order.contact")

    assert state == {
        "order.site.existing": "site-2",
        "unrelated": "keep",
    }
