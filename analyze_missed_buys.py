import os
import glob
import sqlite3
from price_analysis_item import PriceAnalysisItem
from filter import TradingParams
from candlestick import Candlestick
from datetime import datetime

class DummySymbolItem:
    def __init__(self, pdno):
        self.pdno = pdno

def analyze_today():
    db_files = glob.glob('cache/price_analysis/*.db')
    results = []
    
    for db in db_files:
        pdno = os.path.basename(db).split('.')[0]
        conn = sqlite3.connect(db)
        cur = conn.cursor()
        
        cur.execute("SELECT start_time, open_price, high_price, low_price, close_price, volume FROM candles ORDER BY start_time ASC")
        rows = cur.fetchall()
        conn.close()
        
        dummy = DummySymbolItem(pdno)
        item = PriceAnalysisItem(dummy, 'cache/price_analysis')
        item.candle_stick_5minute = []
        
        for row in rows:
            start_time = row[0]
            dt = datetime.fromtimestamp(start_time)
            target_date = "2026-05-12"
            
            c = Candlestick(float(row[1]), float(row[2]), float(row[3]), float(row[4]))
            c.volume = int(row[5])
            item.candle_stick_5minute.append(c)
            
            if dt.strftime("%Y-%m-%d") == target_date:
                hour = dt.hour
                min = dt.minute
                
                if hour < TradingParams.PURCHASE_START_HOUR or (hour == TradingParams.PURCHASE_START_HOUR and min < TradingParams.PURCHASE_START_MIN):
                    continue
                if (hour == TradingParams.PURCHASE_OVERTIME_HOUR and min >= TradingParams.PURCHASE_OVERTIME_MIN) or (hour >= TradingParams.FORCE_SELL_HOUR):
                    continue
                    
                closes = [x.close_price for x in item.candle_stick_5minute]
                if len(closes) < TradingParams.MIN_CANDLE_COUNT:
                    continue
                
                rsi = item._rsi(closes, 14)
                if rsi is not None and (rsi > TradingParams.RSI_UPPER_LIMIT or rsi < TradingParams.RSI_LOWER_LIMIT):
                    continue
                
                ema20 = item._ema(closes, 20)
                if ema20 is not None and (closes[-1] - ema20) / ema20 > TradingParams.EMA20_DEVIATION_MAX:
                    continue
                    
                if not item._is_purchase_trend_recommended():
                    continue
                if item._is_pullback_buy() or item._is_breakout_buy():
                    results.append((pdno, dt.strftime("%H:%M:%S"), closes[-1]))
                    break

    print(f"Total passed items: {len(results)}")
    for r in results:
        print(r)

if __name__ == "__main__":
    analyze_today()
