from __future__ import annotations

from collections.abc import Callable, Hashable, Iterable, MutableMapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Generic, Protocol, TypeVar

ValueT = TypeVar("ValueT", bound=Hashable)


class ChoiceMode(StrEnum):
    CHOOSE_EXISTING = "Choose existing"
    ADD_NEW = "Add new"


@dataclass(frozen=True)
class ChoiceOption(Generic[ValueT]):
    """A display label paired with its real submitted value."""

    value: ValueT
    label: str


@dataclass(frozen=True)
class ChoiceSelection(Generic[ValueT]):
    """The selected mode and sentinel-free value ready for validation."""

    mode: ChoiceMode
    value: ValueT | str | None


class ChoiceFieldUI(Protocol):
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


def deduplicate_options(
    options: Iterable[ChoiceOption[ValueT]],
) -> tuple[ChoiceOption[ValueT], ...]:
    """Keep the first option for each submitted value, preserving order."""

    seen: set[ValueT] = set()
    unique: list[ChoiceOption[ValueT]] = []
    for option in options:
        if option.value not in seen:
            seen.add(option.value)
            unique.append(option)
    return tuple(unique)


def render_choice_field(
    ui: ChoiceFieldUI,
    *,
    label: str,
    key: str,
    existing_options: Iterable[ChoiceOption[ValueT]],
) -> ChoiceSelection[ValueT]:
    """Render one existing-or-new field and return its real value."""

    mode = ChoiceMode(
        ui.radio(
            label,
            tuple(item.value for item in ChoiceMode),
            key=f"{key}.mode",
            horizontal=True,
        )
    )
    if mode is ChoiceMode.CHOOSE_EXISTING:
        option = ui.selectbox(
            "Choose existing",
            deduplicate_options(existing_options),
            key=f"{key}.existing",
            index=None,
            placeholder="Choose an option",
            format_func=lambda item: item.label,
        )
        return ChoiceSelection(mode=mode, value=None if option is None else option.value)

    new_value = ui.text_input("Add new", key=f"{key}.new")
    return ChoiceSelection(mode=mode, value=new_value.strip() or None)


def _clear_choice_field(state: MutableMapping[str, object], key: str) -> None:
    for suffix in ("mode", "existing", "new"):
        state.pop(f"{key}.{suffix}", None)


def reset_customer_dependents(
    state: MutableMapping[str, object],
    *,
    site_key: str,
    contact_key: str,
) -> None:
    """Clear site and contact widgets after the customer changes."""

    _clear_choice_field(state, site_key)
    _clear_choice_field(state, contact_key)


def reset_site_dependents(
    state: MutableMapping[str, object],
    *,
    contact_key: str,
) -> None:
    """Clear contact widgets after the site changes."""

    _clear_choice_field(state, contact_key)
