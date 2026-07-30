#!/usr/bin/env bash
# Terminal chat. Pass a bot slug to skip the picker:  ./run.sh athar
cd "$(dirname "$0")"
export GEMINI_API_KEY="${GEMINI_API_KEY:?Error: Set GEMINI_API_KEY env var}"
exec .venv/bin/python cli.py "$@"
