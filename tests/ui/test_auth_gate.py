from dataclasses import dataclass, field

import pytest

from turfhelm.ui.auth_gate import render_secure_entry


class ExecutionStopped(RuntimeError):
    pass


@dataclass
class FakeUser:
    is_logged_in: bool


@dataclass
class FakeStreamlit:
    logged_in: bool
    login_clicked: bool = False
    calls: list[tuple[str, object]] = field(default_factory=list)

    @property
    def user(self) -> FakeUser:
        return FakeUser(is_logged_in=self.logged_in)

    def title(self, value: str) -> None:
        self.calls.append(("title", value))

    def write(self, value: str) -> None:
        self.calls.append(("write", value))

    def info(self, value: str) -> None:
        self.calls.append(("info", value))

    def button(self, label: str, *, type: str) -> bool:
        self.calls.append(("button", (label, type)))
        return self.login_clicked

    def login(self, provider: str) -> None:
        self.calls.append(("login", provider))

    def stop(self) -> None:
        self.calls.append(("stop", None))
        raise ExecutionStopped


def test_anonymous_user_sees_managed_login_and_execution_stops() -> None:
    ui = FakeStreamlit(logged_in=False)

    with pytest.raises(ExecutionStopped):
        render_secure_entry(ui)

    assert ("button", ("Log in securely", "primary")) in ui.calls
    assert not any(name == "login" for name, _value in ui.calls)
    assert ui.calls[-1] == ("stop", None)


def test_login_button_uses_auth0_and_execution_stops() -> None:
    ui = FakeStreamlit(logged_in=False, login_clicked=True)

    with pytest.raises(ExecutionStopped):
        render_secure_entry(ui)

    assert ("login", "auth0") in ui.calls
    assert ui.calls[-1] == ("stop", None)


def test_authenticated_user_cannot_fall_through_to_legacy_application() -> None:
    ui = FakeStreamlit(logged_in=True)

    with pytest.raises(ExecutionStopped):
        render_secure_entry(ui)

    assert ("info", "Secure read-only workspace is being connected.") in ui.calls
    assert not any(name in {"button", "login"} for name, _value in ui.calls)
    assert ui.calls[-1] == ("stop", None)
