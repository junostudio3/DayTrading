import logging
import sys
import traceback
import os
from contextlib import asynccontextmanager
from KisKey import API_SECRET_TOKEN # 보안 토큰 설정 (하드코딩)
from KisKey import mysql_host
from KisKey import mysql_port
from KisKey import mysql_user
from KisKey import mysql_password
from KisKey import mysql_database

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
from fastapi import FastAPI, HTTPException, Query, Request, Depends, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from trade_bot import TradeBot
from trade_engine import TradeEngine
from telegram import Telegram

# 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

security = HTTPBearer()

def verify_token(credentials: HTTPAuthorizationCredentials = Security(security)):
    if credentials.credentials != API_SECRET_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid authorization token")
    return credentials.credentials

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
    Telegram.send_message(f"🚨 <b>[서버 크래시 발생 - Uncaught]</b>\n<pre>{tb_str[:3800]}</pre>")

sys.excepthook = handle_exception

# 전역 변수
bot = None
engine = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global bot, engine
    logger.info("Initializing DayTradingBot and TradingEngine...")
    
    bot = TradeBot()
    engine = TradeEngine(bot, interval_seconds=1)
    engine.start()
    logger.info("TradingEngine started.")
    Telegram.send_power_log_message("🟢 <b>[서버 시작]</b> Day Trading Bot 트레이딩 엔진이 기동되었습니다.")
    
    yield  # 서버 실행 중
    
    logger.info("Shutting down TradingEngine...")
    if engine:
        engine.stop()
    logger.info("Shutdown complete.")
    Telegram.send_power_log_message("🔴 <b>[서버 종료]</b> Day Trading Bot 서버가 안전하게 종료되었습니다.", sync=True)


from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Day Trading Bot API", lifespan=lifespan, dependencies=[Depends(verify_token)])

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Global exception: {exc}", exc_info=True)
    crash_logger.error(f"Global exception on {request.url.path}: {exc}", exc_info=True)
    
    tb_str = "".join(traceback.format_exception_only(type(exc), exc))
    Telegram.send_message(f"🚨 <b>[API 서버 내부 오류]</b>\n경로: {request.url.path}\n<pre>{tb_str[:3800]}</pre>")
    
    return JSONResponse(status_code=500, content={"detail": "Internal Server Error"})


class OrderRequest(BaseModel):
    app_id: str
    side: str
    pdno: str
    quantity: int


@app.get("/users")
async def get_users():
    if not engine:
        raise HTTPException(status_code=503, detail="TradingEngine not initialized")
    return engine.get_user_ids()

@app.get("/snapshot")
async def get_snapshot(app_id: str = Query(..., description="User app ID")):
    if not engine:
        raise HTTPException(status_code=503, detail="TradingEngine not initialized")
    return engine.get_snapshot(app_id)

@app.get("/candles/{pdno}")
async def get_candles(pdno: str):
    if not engine:
        raise HTTPException(status_code=503, detail="TradingEngine not initialized")
    item = engine.bot.price_analysis_items(pdno)
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
    
    engine.submit_order(app_id=order.app_id, side=order.side, pdno=order.pdno, quantity=order.quantity)
    return {"status": "ok", "message": f"{order.side} command submitted for {order.pdno} ({order.quantity})"}

@app.get("/account_history")
async def get_account_history(app_id: str = Query(..., description="User app ID")):
    import pymysql
    try:
        connection = pymysql.connect(
            host=mysql_host,
            port=mysql_port,
            user=mysql_user,
            password=mysql_password,
            database=mysql_database,
            cursorclass=pymysql.cursors.DictCursor
        )
        try:
            with connection.cursor() as cursor:
                sql = """
                    SELECT id, app_id, tot_evlu_amt, dnca_tot_amt, nxdy_excc_amt, prvs_rcdl_excc_amt, DATE_FORMAT(time, '%%Y-%%m-%%d %%H:%%i:%%s') as time
                    FROM `pulsetrade.accounthistory`
                    WHERE app_id = %s
                    AND time >= DATE_SUB(NOW(), INTERVAL 30 DAY)
                    ORDER BY time ASC
                """
                cursor.execute(sql, (app_id,))
                result = cursor.fetchall()
                return result
        finally:
            connection.close()
    except Exception as e:
        logger.error(f"Failed to fetch account history: {e}")
        raise HTTPException(status_code=500, detail="Database connection failed")

@app.get("/profit_history")
async def get_profit_history(app_id: str = Query(..., description="User app ID")):
    import pymysql
    try:
        connection = pymysql.connect(
            host=mysql_host,
            port=mysql_port,
            user=mysql_user,
            password=mysql_password,
            database=mysql_database,
            cursorclass=pymysql.cursors.DictCursor
        )
        try:
            with connection.cursor() as cursor:
                sql = """
                    SELECT 
                        a.id, 
                        a.app_id, 
                        a.tot_evlu_amt,
                        COALESCE((
                            SELECT d.deposit 
                            FROM `pulsetrade.deposit` d 
                            WHERE d.app_id = a.app_id AND d.time <= a.time 
                            ORDER BY d.time DESC LIMIT 1
                        ), 0) as deposit,
                        a.tot_evlu_amt - COALESCE((
                            SELECT d.deposit 
                            FROM `pulsetrade.deposit` d 
                            WHERE d.app_id = a.app_id AND d.time <= a.time 
                            ORDER BY d.time DESC LIMIT 1
                        ), 0) as profit,
                        DATE_FORMAT(a.time, '%%Y-%%m-%%d %%H:%%i:%%s') as time
                    FROM `pulsetrade.accounthistory` a
                    WHERE a.app_id = %s
                    AND a.time >= DATE_SUB(NOW(), INTERVAL 30 DAY)
                    ORDER BY a.time ASC
                """
                cursor.execute(sql, (app_id,))
                result = cursor.fetchall()
                return result
        finally:
            connection.close()
    except Exception as e:
        logger.error(f"Failed to fetch profit history: {e}")
        raise HTTPException(status_code=500, detail="Database connection failed")

if __name__ == "__main__":
    access_log = False # uvicorn의 기본 access log는 너무 많은 로그를 생성하므로 비활성화
    uvicorn.run("main_server:app", host="0.0.0.0", port=1530, reload=False, access_log=access_log)
