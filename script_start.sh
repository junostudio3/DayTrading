#!/bin/bash
cd "$(dirname "$0")"

# .venv/bin/activate 활성화 (가상환경이 존재할 경우)
if [ -f "./.venv/bin/activate" ]; then
    source ./.venv/bin/activate
fi

# 기존 백그라운드 서버 종료
pkill -f "main_server.py" || true
sleep 1

# FastAPI 서버 백그라운드 구동
echo "Starting FastAPI Server..."
python3 main_server.py > ./log/server.log 2>&1 &

# 서버 로딩 대기
sleep 3

# TUI 클라이언트 실행
echo "Starting TUI Client..."
python3 main_tui.py

# TUI 종료 후 서버 종료
echo "Shutting down FastAPI Server..."
pkill -f "main_server.py" || true

