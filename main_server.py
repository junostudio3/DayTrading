import logging
import sys
import traceback
import io
import os
import zipfile
import urllib.request
from contextlib import asynccontextmanager

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

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from day_trading_bot import DayTradingBot
from trading_engine import TradingEngine
from telegram_sender import send_telegram_message
from telegram_sender import send_telegram_server_power_log

# 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 크래시 로거 설정
crash_logger = logging.getLogger("crash_logger")
crash_logger.setLevel(logging.ERROR)
crash_handler = logging.FileHandler("log/server_crash.log")
crash_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
crash_logger.addHandler(crash_handler)

def handle_exception(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    logger.error("Uncaught exception", exc_info=(exc_type, exc_value, exc_traceback))
    crash_logger.error("Uncaught exception", exc_info=(exc_type, exc_value, exc_traceback))
    
    tb_str = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    send_telegram_message(f"🚨 <b>[서버 크래시 발생 - Uncaught]</b>\n<pre>{tb_str[:3800]}</pre>")

sys.excepthook = handle_exception

# 전역 변수
bot = None
engine = None

def download_and_extract_master_files():
    base_url = "https://new.real.download.dws.co.kr/common/master/"
    files = ["kospi_code.mst", "kosdaq_code.mst"]
    info_dir = "./information"
    os.makedirs(info_dir, exist_ok=True)
    
    for file_name in files:
        zip_url = f"{base_url}{file_name}.zip"
        logger.info(f"Downloading {zip_url}...")
        try:
            req = urllib.request.Request(zip_url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req) as response:
                with zipfile.ZipFile(io.BytesIO(response.read())) as z:
                    z.extract(file_name, path=info_dir)
                    logger.info(f"Extracted {file_name} to {info_dir}")
        except Exception as e:
            logger.error(f"Failed to download or extract {file_name}: {e}")
            crash_logger.error(f"Failed to download or extract {file_name}: {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    global bot, engine
    logger.info("Initializing DayTradingBot and TradingEngine...")
    
    # 서버 기동 시 마스터 파일 다운로드 및 압축 해제
    download_and_extract_master_files()
    
    bot = DayTradingBot()
    engine = TradingEngine(bot, interval_seconds=1)
    engine.start()
    logger.info("TradingEngine started.")
    send_telegram_server_power_log("🟢 <b>[서버 시작]</b> Day Trading Bot 트레이딩 엔진이 기동되었습니다.")
    
    yield  # 서버 실행 중
    
    logger.info("Shutting down TradingEngine...")
    if engine:
        engine.stop()
    logger.info("Shutdown complete.")
    send_telegram_server_power_log("🔴 <b>[서버 종료]</b> Day Trading Bot 서버가 안전하게 종료되었습니다.", sync=True)


app = FastAPI(title="Day Trading Bot API", lifespan=lifespan)

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Global exception: {exc}", exc_info=True)
    crash_logger.error(f"Global exception on {request.url.path}: {exc}", exc_info=True)
    
    tb_str = "".join(traceback.format_exception_only(type(exc), exc))
    send_telegram_message(f"🚨 <b>[API 서버 내부 오류]</b>\n경로: {request.url.path}\n<pre>{tb_str[:3800]}</pre>")
    
    return JSONResponse(status_code=500, content={"detail": "Internal Server Error"})


class OrderRequest(BaseModel):
    side: str
    pdno: str
    quantity: int


@app.get("/snapshot")
async def get_snapshot():
    if not engine:
        raise HTTPException(status_code=503, detail="TradingEngine not initialized")
    return engine.get_snapshot()

@app.get("/candles/{pdno}")
async def get_candles(pdno: str):
    if not engine:
        raise HTTPException(status_code=503, detail="TradingEngine not initialized")
    item = engine.bot.price_analysis.items.get(pdno)
    if not item or not item.candle_stick_5minute:
        return []
    
    # 최근 50개 캔들만 전송
    candles = item.candle_stick_5minute[-50:]
    return [{
        "end_time": c.end_time,
        "open_price": c.open_price,
        "high_price": c.high_price,
        "low_price": c.low_price,
        "close_price": c.close_price
    } for c in candles]

@app.post("/order")
async def submit_order(order: OrderRequest):
    if not engine:
        raise HTTPException(status_code=503, detail="TradingEngine not initialized")
    if order.side not in ("buy", "sell"):
        raise HTTPException(status_code=400, detail="Invalid side. Must be 'buy' or 'sell'")
    
    engine.submit_order(side=order.side, pdno=order.pdno, quantity=order.quantity)
    return {"status": "ok", "message": f"{order.side} command submitted for {order.pdno} ({order.quantity})"}


if __name__ == "__main__":
    uvicorn.run("main_server:app", host="0.0.0.0", port=1530, reload=False)
