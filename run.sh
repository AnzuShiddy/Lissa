#!/usr/bin/env bash
cd "$(dirname "$0")"
export GEMINI_API_KEY="${GEMINI_API_KEY:?Error: Set GEMINI_API_KEY env var}"
exec .venv/bin/python lissa.py
