#!/bin/sh
set -eu

PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$PROJECT_DIR"

if [ -n "${DEVOPS_COPILOT_PYTHON:-}" ]; then
    PYTHON=$DEVOPS_COPILOT_PYTHON
elif [ -x "$PROJECT_DIR/venv/bin/python" ]; then
    PYTHON="$PROJECT_DIR/venv/bin/python"
else
    PYTHON=python3
fi

"$PYTHON" -m unittest discover -s tests -v
"$PYTHON" main.py terraform-analyze examples/terraform-json
if "$PYTHON" -c 'import hcl2' >/dev/null 2>&1; then
    "$PYTHON" main.py terraform-analyze examples/terraform-hcl
else
    echo "HCL example skipped: install the optional parser with python3 -m pip install '.[terraform]'"
fi
