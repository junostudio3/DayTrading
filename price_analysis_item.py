import os
import time
import sqlite3
from datetime import datetime
from candlestick import Candlestick
from candlestick import CandlestickMerger
from common_structure import SymbolItem

class PriceAnalysisItem:
    def __init__(self, symbol_item: SymbolItem, cache_dir):
        self.symbol_item = symbol_item
        self.candle_stick_5minute: list[Candlestick] = []
        self.candle_merger = CandlestickMerger()
        # path to SQLite file for this pdno
        self.db_path = os.path.join(cache_dir, f"{self.symbol_item.pdno}.db")
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
                close_price REAL,
                volume INTEGER DEFAULT 0
            )"""
        )

        c.execute("PRAGMA table_info(candles)")
        columns = [row[1] for row in c.fetchall()]
        if "volume" not in columns:
            c.execute("ALTER TABLE candles ADD COLUMN volume INTEGER DEFAULT 0")

        conn.commit()
        conn.close()

    def _db_connect(self):
        return sqlite3.connect(self.db_path)

    def _load_from_db(self):
        # load all rows sorted by time
        conn = self._db_connect()
        c = conn.cursor()
        for row in c.execute(
            "SELECT start_time, end_time, open_price, high_price, low_price, close_price, volume "
            "FROM candles ORDER BY start_time"
        ):
            candle = Candlestick(row[2], row[3], row[4], row[5], row[6] if row[6] is not None else 0)
            candle.start_time = row[0]
            candle.end_time = row[1]
            self.candle_stick_5minute.append(candle)

        conn.close()

    def _insert_candle(self, candle: Candlestick):
        conn = self._db_connect()
        c = conn.cursor()
        c.execute(
            "INSERT OR REPLACE INTO candles(start_time, end_time, open_price, high_price, low_price, close_price, volume) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                candle.start_time,
                candle.end_time,
                candle.open_price,
                candle.high_price,
                candle.low_price,
                candle.close_price,
                int(candle.volume),
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

    def _get_5min_bucket(self, ts: float):
        return ts - (ts % 300)

    def add_price(self, one_candle : Candlestick) -> bool:
        bucket = self._get_5min_bucket(one_candle.start_time)

        if not self.candle_stick_5minute:
            # 새로운 캔들스틱 생성
            self._add_new_candle(one_candle, bucket)
            return True

        last_candle = self.candle_stick_5minute[-1]

        # 같은 5분 구간이면 업데이트
        if not self.candle_stick_5minute or bucket > last_candle.start_time:
            # 새로운 5분 구간이면 새 봉 생성
            self._add_new_candle(one_candle, bucket)
            return True

        elif last_candle.start_time == bucket:
            changed = last_candle.close_price != one_candle.close_price # 가격이 변경된 경우에만 True 반환

            self.candle_merger.add_candle(one_candle)

            merged_candle = self.candle_merger.get_merged_candle()
            merged_candle.start_time = bucket

            self.candle_stick_5minute[-1] = merged_candle
            self._insert_candle(self.candle_stick_5minute[-1])
            return changed

        return False

    def _add_new_candle(self, new_candle: Candlestick, bucket: float):
        self.candle_merger = CandlestickMerger()
        self.candle_merger.add_candle(new_candle)

        merged_candle = self.candle_merger.get_merged_candle()
        merged_candle.start_time = bucket

        self.candle_stick_5minute.append(merged_candle)
        self._insert_candle(merged_candle)

        # 메모리 관리
        if len(self.candle_stick_5minute) > 200:
            oldest = self.candle_stick_5minute.pop(0)
            self._delete_candle(oldest.start_time)
        return True
    
    def is_purchase_overtime(self):
        # 3시부터는 매도를 시작하므로 2시 50분부터는 구매 추천하지 않음
        local_time = time.localtime()
        return (local_time.tm_hour == 14 and local_time.tm_min >= 50) or (local_time.tm_hour >= 15)
        
    def is_purchase_recommended(self):
        if self.is_purchase_overtime():
            return False

        if not self._is_purchase_trend_recommended():
            return False
        if self._is_pullback_buy():
            return True
        if self._is_breakout_buy():
            return True

        return False

    def _ema(self, prices, period):
        if len(prices) < period:
            return None

        k = 2 / (period + 1)

        # 초기 EMA는 단순 이동 평균으로 시작
        ema = sum(prices[:period]) / period
        
        for price in prices[period:]:
            ema = price * k + ema * (1 - k)
        return ema

    # 구매 추세 조건    
    def _is_purchase_trend_recommended(self):
        # 구매 추세 추천 로직

        candles = self.candle_stick_5minute
        if len(candles) < 60:
            return False

        closes = [c.close_price for c in candles]

        ema20 = self._ema(closes, 20)
        ema60 = self._ema(closes, 60)

        if ema20 is None or ema60 is None:
            return False
    
        # 이격도 최소 0.6%
        if (ema20 - ema60) / ema60 < 0.006:
            return False
        
        avg_vol = sum(c.volume for c in candles[-11:-1]) / 10
        if candles[-1].volume < avg_vol * 1.3:
            # 거래량이 충분히 증가하지 않았다면 추세로 보기 어렵다고 판단
            return False

        # 1️⃣ 20EMA > 60EMA
        if ema20 <= ema60:
            return False

        # 2️⃣ EMA 기울기 확인 (상승 중인지)
        prev_ema20 = self._ema(closes[:-1], 20)
        if prev_ema20 is None or ema20 <= prev_ema20:
            return False

        last_close = closes[-1]

        # 3️⃣ 현재가가 20EMA 위에 있는지
        if last_close < ema20:
            return False

        # 4️⃣ 최근 3봉 중 2봉 이상 양봉
        recent_candles = candles[-3:]
        bullish_count = sum(1 for c in recent_candles if c.is_bullish())
        if bullish_count < 2:
            return False

        return True
    
    def _is_pullback_buy(self):
        # 눌림목 구매 추천 로직
        candles = self.candle_stick_5minute
        if len(candles) < 60:
            return False

        closes = [c.close_price for c in candles]

        ema20 = self._ema(closes, 20)
        ema60 = self._ema(closes, 60)

        if ema20 is None or ema60 is None:
            return False

        # 추세 조건
        if ema20 <= ema60:
            return False

        prev_low = candles[-2].low_price
        last_close = closes[-1]

        # EMA20 터치 후 반등 확인
        if prev_low <= ema20 and last_close > ema20:
            if candles[-1].is_bullish():
                return True

        return False
    
    def _is_breakout_buy(self):
        # 돌파 구매 추천 로직
        # 최근 5분봉이 최근 1시간 내 고점(20이평 이상)을 뚫고 올라오는 모양이면 구매 추천

        candles = self.candle_stick_5minute
        if len(candles) < 11:
            return False
        
        last_candle = candles[-1]
        avg_vol = sum(c.volume for c in candles[-11:-1]) / 10
        recent_high = max(c.high_price for c in candles[-11:-1])

        if last_candle.volume < avg_vol * 1.5:
            # 거래량이 충분히 증가하지 않았다면 돌파로 보기 어렵다고 판단
            return False

        if last_candle.close_price > recent_high:
            if last_candle.is_bullish():
                return True

        return False
    
    def is_sell_recommended(self, purchase_price):
        # 판매 추천 로직
        # 익절 로직
        if len(self.candle_stick_5minute) < 3:
            return False

        candles = self.candle_stick_5minute
        last = candles[-1]
        prev = candles[-2]

        current_price = last.close_price
        profit_rate = (current_price - purchase_price) / purchase_price

        # 1.5% 이상 수익 구간이 아니면 판매 안함
        if profit_rate < 0.015:
            return False

        if profit_rate >= 0.03:
            # 3% 이상 수익이면 바로 판매 추천
            return True

        closes = [c.close_price for c in candles]
        ema20 = self._ema(closes, 20)

        # ----------------------------
        # 🔼 상승 유지 조건
        # ----------------------------

        # 1️⃣ EMA20 위에 있고
        ema_condition = ema20 is not None and current_price >= ema20

        # 2️⃣ 최근 봉이 양봉이고
        bullish_condition = last.is_bullish()

        # 3️⃣ 고점이 낮아지지 않았으면 (higher high)
        high_condition = last.high_price >= prev.high_price

        # 상승 유지면 안 판다
        if ema_condition and bullish_condition and high_condition:
            return False

        # 상승 꺾이면 매도
        return True
    
    def is_sell_stop_loss_recommended(self, purchase_price):
        # 손절 추천 로직
        local_time = time.localtime()

        # 장마감시간이 15:30이므로, 15:00 이후에는 어찌 되었든 판매 추천
        if (local_time.tm_hour > 15) or \
            (local_time.tm_hour == 15 and local_time.tm_min >= 30):
            return True
        
        # -0.6% 손절 로직
        if not self.candle_stick_5minute:
            return False

        return self.candle_stick_5minute[-1].close_price <= purchase_price * 0.994