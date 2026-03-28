@echo off
setlocal

:: 스크립트가 있는 디렉토리로 이동
cd /d "%~dp0"

:: .venv\Scripts\activate.bat 활성화 (가상환경이 존재할 경우)
if exist ".\.venv\Scripts\activate.bat" (
    call ".\.venv\Scripts\activate.bat"
)

:: 로그 폴더 생성 (없을 경우 에러 방지)
if not exist ".\log" mkdir ".\log"

:: 기존 백그라운드 서버 종료 (wmic 활용하여 main_server.py 구동 프로세스만 종료)
wmic process where "name='python.exe' and commandline like '%%main_server.py%%'" call terminate >nul 2>&1
timeout /t 1 /nobreak >nul

:: FastAPI 서버 백그라운드 구동
echo Starting FastAPI Server...
start /b "" cmd /c "python main_server.py > .\log\server.log 2>&1"

:: 서버 로딩 대기
timeout /t 3 /nobreak >nul

:: TUI 클라이언트 실행
echo Starting TUI Client...
python main_tui.py

:: TUI 종료 후 서버 종료
echo Shutting down FastAPI Server...
wmic process where "name='python.exe' and commandline like '%%main_server.py%%'" call terminate >nul 2>&1

endlocal
