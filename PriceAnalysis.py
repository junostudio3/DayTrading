import os
import time
import sqlite3
from datetime import datetime
from Candlestick import Candlestick

class PriceAnalysisItem:
    def __init__(self, symbol, name, cache_dir):
        self.symbol = symbol
        self.name = name
        self.volume = 0
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

        if self.candle_stick_5minute:
            self.volume = int(self.candle_stick_5minute[-1].volume)
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

    def _timestamp_from_stick_time(self, stick_time: str) -> float:
        if not stick_time:
            return time.time()

        try:
            hhmmss = stick_time.strip()[:6]
            hour = int(hhmmss[0:2])
            minute = int(hhmmss[2:4])
            second = int(hhmmss[4:6])
            now = datetime.now()
            tick_dt = now.replace(hour=hour, minute=minute, second=second, microsecond=0)
            return tick_dt.timestamp()
        except Exception:
            return time.time()

    def add_price(self, price, volume, stick_time: str) -> bool:
        tick_volume = int(volume) if volume is not None else 0
        timestamp = self._timestamp_from_stick_time(stick_time)
        bucket = self._get_5min_bucket(timestamp)

        if not self.candle_stick_5minute:
            # 새로운 캔들스틱 생성
            new_candle = Candlestick(price, price, price, price, tick_volume)
            new_candle.start_time = bucket
            new_candle.end_time = bucket + 300
            self.candle_stick_5minute.append(new_candle)
            self._insert_candle(new_candle)
            self.volume = int(new_candle.volume)
            return True

        last_candle = self.candle_stick_5minute[-1]

        # 같은 5분 구간이면 업데이트
        if last_candle.start_time == bucket:
            changed = last_candle.close_price != price # 가격이 변경된 경우에만 True 반환
            last_candle.close_price = price
            last_candle.high_price = max(last_candle.high_price, price)
            last_candle.low_price = min(last_candle.low_price, price)
            last_candle.volume = int(last_candle.volume) + tick_volume
            self._insert_candle(last_candle)
            self.volume = int(last_candle.volume)
            return changed

        # 새로운 5분 구간이면 새 봉 생성
        elif bucket > last_candle.start_time:
            new_candle = Candlestick(price, price, price, price, tick_volume)
            new_candle.start_time = bucket
            new_candle.end_time = bucket + 300
            self.candle_stick_5minute.append(new_candle)
            self._insert_candle(new_candle)
            self.volume = int(new_candle.volume)

            # 메모리 관리
            if len(self.candle_stick_5minute) > 200:
                oldest = self.candle_stick_5minute.pop(0)
                self._delete_candle(oldest.start_time)
            return True
        return False
        
    def is_purchase_recommended(self):
        if self._is_purchase_trend_recommended():
            return True
        if self._is_pullback_buy():
            return True
        if self._is_breakout_buy():
            return True

        return False

    # 구매 추세 조건    
    def _is_purchase_trend_recommended(self):
        # 구매 추세 추천 로직

        candles = self.candle_stick_5minute
        candle_count = len(candles)
        if candle_count < 60:
            return False

        # 5분봉이 5시간 이상 쌓였을 때 분석 시작
        sum_60 = 0.0
        sum_20 = 0.0
        start_60 = candle_count - 60
        start_20 = candle_count - 20

        for idx in range(start_60, candle_count):
            close_price = candles[idx].close_price
            sum_60 += close_price
            if idx >= start_20:
                sum_20 += close_price

        average_20 = sum_20 / 20
        average_60 = sum_60 / 60
        if average_20 < average_60:
            return False

        # 20이평 > 60이평 이면
        last_close_price = candles[-1].close_price
        prev_20 = (sum_20 - last_close_price + candles[candle_count - 21].close_price) / 20
        if average_20 <= prev_20:
            return False

        # 이평이 위로 뚫고 올라오는 모양이면
        if last_close_price < average_20:
            return False

        # 현재가 > 20이평 이면
        # 최근 3봉 중 2봉 이상 양봉이면
        recent_candles = candles[-3:]
        bullish_count = sum(1 for candle in recent_candles if candle.is_bullish())
        if bullish_count < 2:
            return False

        # 상승 추세라고 판단하여 구매 추천
        return True
    
    def _is_pullback_buy(self):
        # 눌림목 구매 추천 로직
        # 20이평 > 60이평 이면서, 최근 5분봉이 20이평을 뚫고 올라오는 모양이면 구매 추천
        candles = self.candle_stick_5minute
        if len(candles) < 60:
            return False

        closes = [c.close_price for c in candles]
        ma20 = sum(closes[-20:]) / 20
        ma60 = sum(closes[-60:]) / 60

        if ma20 <= ma60:
            return False

        prev_close = closes[-2]
        last_close = closes[-1]

        # 눌림 후 복귀
        if prev_close < ma20 and last_close > ma20:
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
        # 마지막 캔들스틱의 종가를 기준으로 purchase_price 대비 2% 이상 상승했을 때 판매 추천
        if not self.candle_stick_5minute:
            return False

        return self.candle_stick_5minute[-1].close_price >= purchase_price * 1.02
    
    def is_sell_stop_loss_recommended(self, purchase_price):
        # 손절 추천 로직
        local_time = time.localtime()

        # 장마감시간이 15:30이므로, 15:00 이후에는 어찌 되었든 판매 추천
        if (local_time.tm_hour > 15) or \
            (local_time.tm_hour == 15 and local_time.tm_min >= 30):
            return True
        
        # -1% 손절 로직
        if not self.candle_stick_5minute:
            return False

        return self.candle_stick_5minute[-1].close_price <= purchase_price * 0.99

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

    def add_price(self, symbol, price, volume, stick_time: str) -> bool:
        is_changed = False
        if symbol not in self.items:
            self.items[symbol] = PriceAnalysisItem(symbol, symbol, self.cache_dir)  # 이름은 심볼로 초기화
            is_changed = True
        if self.items[symbol].add_price(price, volume, stick_time):
            is_changed = True
        return is_changed

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
