#!/bin/sh
# Pierwsze uruchomienie instaluje biblioteki do lokalnego środowiska .venv
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt || exit 1
fi
exec .venv/bin/python pilotdesk.py "$@"
