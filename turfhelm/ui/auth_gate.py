from __future__ import annotations

from typing import NoReturn, Protocol


class _User(Protocol):
    is_logged_in: bool


class StreamlitAuthUI(Protocol):
    user: _User

    def title(self, value: str) -> None: ...

    def write(self, value: str) -> None: ...

    def info(self, value: str) -> None: ...

    def button(self, label: str, *, type: str) -> bool: ...

    def login(self, provider: str) -> None: ...

    def stop(self) -> NoReturn: ...


def render_secure_entry(ui: StreamlitAuthUI) -> NoReturn:
    """Fail closed until the authenticated read-only workspace is complete."""

    if not getattr(ui.user, "is_logged_in", False):
        ui.title("TurfHelm")
        ui.write("Sign in with your organization account to continue.")
        if ui.button("Log in securely", type="primary"):
            ui.login("auth0")
        ui.stop()

    ui.info("Secure read-only workspace is being connected.")
    ui.stop()
