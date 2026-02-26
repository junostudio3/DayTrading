import os
import time
import sqlite3
from Candlestick import Candlestick
import json

class PriceAnalysisItem:
    def __init__(self, symbol, name, cache_dir):
        self.symbol = symbol
        self.name = name
        self.candle_stick_5minute: list[Candlestick] = []
        # path to SQLite file for this symbol
        self.db_path = os.path.join(cache_dir, f"{symbol}.db")
        self._ensure_db()
        self._load_from_db()

    def _ensure_db(self):
        # create database file and table if missing
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute(
            """CREATE TABLE IF NOT EXISTS candles(
                start_time REAL PRIMARY KEY,
                end_time REAL,
                open_price REAL,
                high_price REAL,
                low_price REAL,
                close_price REAL
            )"""
        )
        conn.commit()
        conn.close()

    def _db_connect(self):
        return sqlite3.connect(self.db_path)

    def _load_from_db(self):
        # load all rows sorted by time
        conn = self._db_connect()
        c = conn.cursor()
        for row in c.execute(
            "SELECT start_time, end_time, open_price, high_price, low_price, close_price "
            "FROM candles ORDER BY start_time"
        ):
            candle = Candlestick(row[2], row[3], row[4], row[5])
            candle.start_time = row[0]
            candle.end_time = row[1]
            self.candle_stick_5minute.append(candle)
        conn.close()

    def _insert_candle(self, candle: Candlestick):
        conn = self._db_connect()
        c = conn.cursor()
        c.execute(
            "INSERT OR REPLACE INTO candles(start_time, end_time, open_price, high_price, low_price, close_price) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                candle.start_time,
                candle.end_time,
                candle.open_price,
                candle.high_price,
                candle.low_price,
                candle.close_price,
            ),
        )
        conn.commit()
        conn.close()

    def _delete_candle(self, start_time: float):
        conn = self._db_connect()
        c = conn.cursor()
        c.execute("DELETE FROM candles WHERE start_time = ?", (start_time,))
        conn.commit()
        conn.close()

    def add_price(self, price):
        timestamp = time.time()
        if not self.candle_stick_5minute or timestamp - self.candle_stick_5minute[-1].start_time >= 300:
            # 새로운 캔들스틱 생성
            new_candle = Candlestick(price, price, price, price)
            new_candle.start_time = timestamp
            new_candle.end_time = timestamp
            self.candle_stick_5minute.append(new_candle)
            self._insert_candle(new_candle)
            if len(self.candle_stick_5minute) > 200:  # 메모리 관리를 위해 오래된 캔들스틱 제거
                oldest = self.candle_stick_5minute.pop(0)
                self._delete_candle(oldest.start_time)
        else:
            # 기존 캔들스틱 업데이트
            current_candle = self.candle_stick_5minute[-1]
            current_candle.end_time = timestamp
            current_candle.close_price = price
            current_candle.high_price = max(current_candle.high_price, price)
            current_candle.low_price = min(current_candle.low_price, price)
            self._insert_candle(current_candle)
        
    def is_purchase_recommended(self):
        # 구매 추천 로직

        if self._is_purchase_trend_recommended():
            return True

        return False

    # 구매 추세 조건    
    def _is_purchase_trend_recommended(self):
        # 구매 추세 추천 로직

        if len(self.candle_stick_5minute) < 60:
            return False

        # 5분봉이 5시간 이상 쌓였을 때 분석 시작
        average_20 = sum(c.close_price for c in self.candle_stick_5minute[-20:]) / 20
        average_60 = sum(c.close_price for c in self.candle_stick_5minute[-60:]) / 60
        if average_20 < average_60:
            return False

        # 20이평 > 60이평 이면
        if self.candle_stick_5minute[-1].close_price < average_20:
            return False

        # 현재가 > 20이평 이면
        # 최근 3봉 중 2봉 이상 양봉이면
        recent_candles = self.candle_stick_5minute[-3:]
        bullish_count = sum(1 for c in recent_candles if c.is_bullish())
        if bullish_count < 2:
            return False

        # 상승 추세라고 판단하여 구매 추천
        return True
    
    def is_sell_recommended(self, purchase_price):
        # 판매 추천 로직
        timestamp = time.time()

        # 익절 로직
        # 마지막 캔들스틱의 종가를 기준으로 purchase_price 대비 2% 이상 상승했을 때 판매 추천
        if self.candle_stick_5minute and self.candle_stick_5minute[-1].close_price >= purchase_price * 1.02:
            return True

        return False
    
    def is_sell_stop_loss_recommended(self, purchase_price):
        # 손절 추천 로직
        timestamp = time.time()

        # 장마감시간이 15:30이므로, 15:00 이후에는 어찌 되었든 판매 추천
        if time.localtime(timestamp).tm_hour == 15 and time.localtime(timestamp).tm_min >= 0:
            return True
        
        # -1% 손절 로직
        if self.candle_stick_5minute and self.candle_stick_5minute[-1].close_price <= purchase_price * 0.99:
            return True

        return False

class PriceAnalysis:
    def __init__(self, cache_file):
        # cache_file originally pointed to a json file; we treat its dirname as
        # the directory that will contain per-symbol databases.
        self.cache_file = cache_file
        self.cache_dir = os.path.dirname(cache_file) or "."
        os.makedirs(self.cache_dir, exist_ok=True)
        self.items: dict[str, PriceAnalysisItem] = {}

        # load any existing symbol databases
        self._load_cache()

    def _load_cache(self):
        # load per-symbol databases
        for fname in os.listdir(self.cache_dir):
            if not fname.endswith(".db"):
                continue
            symbol = fname[:-3]
            if symbol in self.items:
                # already loaded via migration
                continue
            item = PriceAnalysisItem(symbol, symbol, self.cache_dir)
            self.items[symbol] = item

    def add_price(self, symbol, price):
        if symbol not in self.items:
            self.items[symbol] = PriceAnalysisItem(symbol, symbol, self.cache_dir)  # 이름은 심볼로 초기화
        self.items[symbol].add_price(price)

    def is_purchase_recommended(self, symbol):
        if symbol in self.items:
            return self.items[symbol].is_purchase_recommended()
        return False
    
    def is_sell_recommended(self, symbol, purchase_price):
        if symbol in self.items:
            return self.items[symbol].is_sell_recommended(purchase_price)
        return False

    def is_sell_stop_loss_recommended(self, symbol, purchase_price):
        if symbol in self.items:
            return self.items[symbol].is_sell_stop_loss_recommended(purchase_price)
        return False

    # legacy save/load methods are retained for backward compatibility
    def save_cache(self):
        # no-op for new per-symbol sqlite storage; data written incrementally
        pass

    # keep old method name around but unused
    def load_cache(self):
        # kept for compatibility; actual loading is done in __init__
        self._load_cache()
