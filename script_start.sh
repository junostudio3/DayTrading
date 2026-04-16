#!/bin/bash
cd "$(dirname "$0")"

# .venv/bin/activate 활성화 (가상환경이 존재할 경우)
if [ -f "./.venv/bin/activate" ]; then
    source ./.venv/bin/activate
fi

# 기존 백그라운드 서버 종료
pkill -f "main_server.py" || true
sleep 1

# 디버그 포트 설정 (기본값: 5678)
DEBUG_SERVER_PORT="${DEBUG_SERVER_PORT:-5678}"

# FastAPI 서버 구동
echo "Starting FastAPI Server... (DEBUG_PORT=${DEBUG_SERVER_PORT})"
export DEBUG_PORT="${DEBUG_SERVER_PORT}"
python3 main_server.py

