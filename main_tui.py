import os

# debugpy 설정 - DEBUG_PORT 환경변수가 설정되면 디버거 활성화
DEBUG_PORT = os.getenv("DEBUG_PORT")
if DEBUG_PORT:
    try:
        import debugpy
        debugpy.listen(("0.0.0.0", int(DEBUG_PORT)))
        print(f"[DEBUG] debugpy listener started on port {DEBUG_PORT}")
    except ImportError:
        print("[WARNING] debugpy is not installed. Install it with: pip install debugpy")
    except Exception as e:
        print(f"[WARNING] Failed to start debugpy: {e}")

from day_trading_tui import DayTradingTUI

if __name__ == "__main__":
    app = DayTradingTUI()
    app.run()

