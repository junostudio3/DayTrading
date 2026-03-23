import asyncio
import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from day_trading_bot import DayTradingBot
from trading_engine import TradingEngine

# 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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
    uvicorn.run("main_server:app", host="0.0.0.0", port=8000, reload=False)
