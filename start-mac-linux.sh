#!/usr/bin/env sh
set -e
cd "$(dirname "$0")"
python3 -m pip install -r requirements.txt
printf 'PDF Studio v2 tersedia di http://127.0.0.1:8000\n'
python3 -m uvicorn server:app --host 127.0.0.1 --port 8000
