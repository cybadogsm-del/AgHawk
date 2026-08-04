from pathlib import Path


def test_devcontainer_keeps_streamlit_browser_protections_enabled() -> None:
    project_root = Path(__file__).resolve().parents[2]
    config = (project_root / ".devcontainer" / "devcontainer.json").read_text(
        encoding="utf-8"
    )

    assert "--server.enableCORS false" not in config
    assert "--server.enableXsrfProtection false" not in config


def test_prototype_does_not_build_sql_with_f_strings() -> None:
    project_root = Path(__file__).resolve().parents[2]
    source = (project_root / "app.py").read_text(encoding="utf-8")

    assert "read_sql_query(f" not in source
