from __future__ import annotations

import importlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = {".json", ".md", ".py", ".sh", ".toml", ".yaml", ".yml"}
IGNORED_PARTS = {".git", ".hermes", ".pytest_cache", ".venv", "__pycache__"}
LEGACY_NAMES = (
    "Turf" + "Worx",
    "TURF" + "WORX",
    "turf" + "worx",
    "Turf" + " Galore",
    "Turf" + "Galore",
    "Turf" + "-Galore",
)


def test_repository_contains_only_turfhelm_product_naming() -> None:
    violations: list[str] = []

    for path in ROOT.rglob("*"):
        if not path.is_file() or path.suffix not in TEXT_SUFFIXES:
            continue
        if any(part in IGNORED_PARTS for part in path.parts):
            continue
        content = path.read_text(encoding="utf-8")
        for legacy_name in LEGACY_NAMES:
            if legacy_name in content:
                violations.append(f"{path.relative_to(ROOT)}: {legacy_name}")

    assert violations == [], "\n".join(violations)


def test_turfhelm_package_is_importable() -> None:
    package = importlib.import_module("turfhelm")

    assert package.__doc__ == "TurfHelm application package."
