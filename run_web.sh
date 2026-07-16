#!/usr/bin/env bash
cd "$(dirname "$0")"
export GEMINI_API_KEY="${GEMINI_API_KEY:?Error: Set GEMINI_API_KEY env var}"
echo "Lissa is at  http://localhost:8000"
exec .venv/bin/uvicorn app:app --host 127.0.0.1 --port 8000
