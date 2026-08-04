from pathlib import Path

from streamlit.testing.v1 import AppTest


def test_anonymous_visitor_sees_managed_login_without_database_access(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    app_path = Path(__file__).resolve().parents[1] / "app.py"

    app = AppTest.from_file(str(app_path), default_timeout=20).run()

    assert len(app.exception) == 0
    assert [field.label for field in app.text_input] == []
    assert [button.label for button in app.button] == ["Log in securely"]
    assert list(tmp_path.glob("*.db")) == []
