#!/usr/bin/env bash
# SQLPilot Local Agent Launcher
set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Prefer virtual environment python if available
if [ -f "$DIR/.venv/bin/python3" ]; then
    PYTHON_BIN="$DIR/.venv/bin/python3"
elif [ -f "$DIR/.venv/bin/python" ]; then
    PYTHON_BIN="$DIR/.venv/bin/python"
elif [ -n "$VIRTUAL_ENV" ]; then
    PYTHON_BIN="$VIRTUAL_ENV/bin/python"
else
    PYTHON_BIN="python3"
fi

export PYTHONPATH="$DIR:$PYTHONPATH"
exec "$PYTHON_BIN" -m sqlpilot.agent "$@"
