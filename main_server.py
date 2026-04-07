import logging
import sys
import traceback
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from day_trading_bot import DayTradingBot
from trading_engine import TradingEngine

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

sys.excepthook = handle_exception

# 전역 변수
bot = None
engine = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global bot, engine
    logger.info("Initializing DayTradingBot and TradingEngine...")
    bot = DayTradingBot()
    engine = TradingEngine(bot, interval_seconds=1)
    engine.start()
    logger.info("TradingEngine started.")
    
    yield  # 서버 실행 중
    
    logger.info("Shutting down TradingEngine...")
    if engine:
        engine.stop()
    logger.info("Shutdown complete.")


app = FastAPI(title="Day Trading Bot API", lifespan=lifespan)

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Global exception: {exc}", exc_info=True)
    crash_logger.error(f"Global exception on {request.url.path}: {exc}", exc_info=True)
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
