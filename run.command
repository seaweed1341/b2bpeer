#!/bin/zsh
set -e
cd "${0:A:h}"
PYTHON_BIN="/Users/mac_from_magok/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"
if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="python3"
fi
"$PYTHON_BIN" server.py
