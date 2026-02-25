#!/bin/bash
# .venv/bin/activate 활성화
cd "$(dirname "$0")"
source ./.venv/bin/activate
python3 main_tui.py
