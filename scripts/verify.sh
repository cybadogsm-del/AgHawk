#!/usr/bin/env bash
set -euo pipefail

PYTHON="${PYTHON:-python3}"
TOOL_DIR="$("$PYTHON" -c 'import pathlib, sys; print(pathlib.Path(sys.executable).parent)')"

bash -n scripts/verify.sh
"$PYTHON" -m py_compile app.py
"$PYTHON" -m json.tool .devcontainer/devcontainer.json >/dev/null
"$PYTHON" -m pytest -q
"$PYTHON" -m ruff check .
"$PYTHON" -m bandit -q -r app.py turfhelm scripts

mapfile -d '' source_files < <(git ls-files -z --cached --others --exclude-standard)
"$TOOL_DIR/detect-secrets-hook" --baseline .secrets.baseline "${source_files[@]}"

"$PYTHON" -m pip_audit -r requirements.txt --progress-spinner off
"$PYTHON" -m pip_audit -r requirements-dev.txt --progress-spinner off

echo "All TurfHelm verification checks passed."
