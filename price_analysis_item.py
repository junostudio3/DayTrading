import os
import time
import sqlite3
from candlestick import Candlestick
from candlestick import CandlestickMerger
from common_structure import SymbolItem
from filter import TradingParams

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
        # load all rows sorted by time, skip stale candles older than STOCK_EXPIRY_DAYS
        cutoff = time.time() - (TradingParams.STOCK_EXPIRY_DAYS * 24 * 60 * 60)
        conn = self._db_connect()
        c = conn.cursor()

        # DB에서 만료된 캔들 삭제
        c.execute("DELETE FROM candles WHERE start_time < ?", (cutoff,))
        conn.commit()

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

        # 메모리 관리 (하루=5분봉x6.5시간(주장시간)=78, 일주일=하루x7=546)
        if len(self.candle_stick_5minute) > 546:
            oldest = self.candle_stick_5minute.pop(0)
            self._delete_candle(oldest.start_time)
        return True
    
    def is_purchase_overtime(self):
        # 시간 제한: 장 시작 직후 혼조세(9시 15분 이전)이거나, 장 마감 직전(14시 20분 이후)일 때 매수 금지
        local_time = time.localtime()
        hour = local_time.tm_hour
        minute = local_time.tm_min

        # 매수 시작 시각 이전이면 구매 추천 안함 (9시 15분부터 매수 가능)
        if hour < TradingParams.PURCHASE_START_HOUR or (hour == TradingParams.PURCHASE_START_HOUR and minute < TradingParams.PURCHASE_START_MIN):
            return True

        # FORCE_SELL_HOUR 부터는 매도를 시작하므로 그 이전 시각부터 구매 추천하지 않음
        return (hour == TradingParams.PURCHASE_OVERTIME_HOUR and minute >= TradingParams.PURCHASE_OVERTIME_MIN) or (hour >= TradingParams.FORCE_SELL_HOUR)
        
    def is_purchase_recommended(self):
        if self.is_purchase_overtime():
            return False

        candles = self.candle_stick_5minute
        if len(candles) < TradingParams.MIN_CANDLE_COUNT:
            return False

        closes = [c.close_price for c in candles]
        
        # 과매수 방지 필터
        rsi = self._rsi(closes, 14)
        if rsi is not None and rsi > TradingParams.RSI_UPPER_LIMIT:
            return False
        
        # [2026-04-01 추가] 과매도 방지 필터 - 휩쏘 손실 방지
        if rsi is not None and rsi < TradingParams.RSI_LOWER_LIMIT:
            return False

        # 이격도 필터: 현재가가 20EMA 대비 너무 높게(급등) 떠 있으면 추격 매수 금지
        ema20 = self._ema(closes, 20)
        current_price = closes[-1]
        if ema20 is not None and (current_price - ema20) / ema20 > TradingParams.EMA20_DEVIATION_MAX:
            return False

        if not self._is_purchase_trend_recommended():
            return False
        if self._is_pullback_buy():
            return True
        if self._is_breakout_buy():
            return True

        return False

    def _rsi(self, closes, period=14):
        if len(closes) < period + 1:
            return None
        deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
        gains = [d if d > 0 else 0 for d in deltas]
        losses = [-d if d < 0 else 0 for d in deltas]
        
        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period
        
        for i in range(period, len(deltas)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period
            
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def _atr(self, candles, period=14):
        if len(candles) < period + 1:
            return None
        tr_list = []
        for i in range(1, len(candles)):
            high = candles[i].high_price
            low = candles[i].low_price
            prev_close = candles[i-1].close_price
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            tr_list.append(tr)
            
        atr = sum(tr_list[:period]) / period
        for i in range(period, len(tr_list)):
            atr = (atr * (period - 1) + tr_list[i]) / period
        return atr

    def _ema(self, prices, period):
        if len(prices) < period:
            return None

        k = 2 / (period + 1)

        # 초기 EMA는 단순 이동 평균으로 시작
        ema = sum(prices[:period]) / period
        
        for price in prices[period:]:
            ema = price * k + ema * (1 - k)
        return ema

    def _std(self, prices, period):
        if len(prices) < period:
            return None
        mean = sum(prices[-period:]) / period
        variance = sum((p - mean) ** 2 for p in prices[-period:]) / period
        import math
        return math.sqrt(variance)

    def get_current_indicators(self):
        """현재 기술적 지표 상태를 반환합니다."""
        if not self.candle_stick_5minute:
            return {}

        candles = self.candle_stick_5minute
        closes = [c.close_price for c in candles]

        # 단기 이동 평균 및 보조지표 계산
        ema20 = self._ema(closes, 20)
        ema60 = self._ema(closes, 60)
        rsi = self._rsi(closes, 14)
        atr = self._atr(candles, 14)
        volume = candles[-1].volume if len(candles) > 0 else 0

        # 볼린저 밴드 계산
        sma20 = sum(closes[-20:]) / 20 if len(closes) >= 20 else None
        std20 = self._std(closes, 20) if len(closes) >= 20 else None
        bb_upper = sma20 + 2 * std20 if sma20 is not None and std20 is not None else None
        bb_lower = sma20 - 2 * std20 if sma20 is not None and std20 is not None else None

        # 결과 포맷팅 (소수점 2자리)
        result = {
            "RSI": round(rsi, 2) if rsi is not None else None,
            "EMA20": round(ema20, 2) if ema20 is not None else None,
            "EMA60": round(ema60, 2) if ema60 is not None else None,
            "ATR": round(atr, 2) if atr is not None else None,
            "BB_Up": round(bb_upper, 2) if bb_upper is not None else None,
            "BB_Low": round(bb_lower, 2) if bb_lower is not None else None,
            "Vol": int(volume)
        }

        if ema20 is not None and ema60 is not None and ema60 > 0:
            result["EMA_Gap"] = round(((ema20 - ema60) / ema60) * 100, 2)
        if bb_upper is not None and bb_lower is not None and sma20 is not None and sma20 > 0:
            result["BB_Width"] = round(((bb_upper - bb_lower) / sma20) * 100, 2)

        if len(candles) >= 11:
            avg_vol = sum(c.volume for c in candles[-11:-1]) / 10
            if avg_vol > 0:
                result["Vol_Ratio"] = round(volume / avg_vol, 2)
            if closes[-11] > 0:
                result["Momentum"] = round(((closes[-1] - closes[-11]) / closes[-11]) * 100, 2)

        # 당일 VWAP(거래량 가중 평균 가격) 및 괴리율 계산
        if len(candles) > 0:
            last_time = time.localtime(candles[-1].start_time)
            target_yday = last_time.tm_yday
            target_year = last_time.tm_year
            
            cum_vol = 0
            cum_pv = 0
            for c in reversed(candles):
                c_time = time.localtime(c.start_time)
                if c_time.tm_yday != target_yday or c_time.tm_year != target_year:
                    break
                cum_vol += c.volume
                cum_pv += c.close_price * c.volume
                
            vwap = cum_pv / cum_vol if cum_vol > 0 else None
            
            if vwap is not None:
                result["VWAP"] = round(vwap, 2)
                result["VWAP_Gap"] = round(((closes[-1] - vwap) / vwap) * 100, 2)

        return result

    # 구매 추세 조건    
    def _is_purchase_trend_recommended(self):
        # 구매 추세 추천 로직

        candles = self.candle_stick_5minute
        if len(candles) < TradingParams.MIN_CANDLE_COUNT:
            return False

        closes = [c.close_price for c in candles]

        ema20 = self._ema(closes, 20)
        ema60 = self._ema(closes, 60)

        if ema20 is None or ema60 is None:
            return False
    
        # EMA 이격도 최소 비율
        if (ema20 - ema60) / ema60 < TradingParams.EMA_GAP_MIN:
            return False
        
        avg_vol = sum(c.volume for c in candles[-11:-1]) / 10
        if candles[-1].volume < avg_vol * TradingParams.TREND_VOLUME_RATIO:
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
        if bullish_count < TradingParams.TREND_BULLISH_MIN:
            return False

        return True
    
    def _is_pullback_buy(self):
        # 눌림목 구매 추천 로직
        candles = self.candle_stick_5minute
        if len(candles) < TradingParams.MIN_CANDLE_COUNT:
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

        if last_candle.volume < avg_vol * TradingParams.BREAKOUT_VOLUME_RATIO:
            # 거래량이 충분히 증가하지 않았다면 돌파로 보기 어렵다고 판단
            return False

        if last_candle.close_price > recent_high:
            if last_candle.is_bullish():
                return True

        return False
    
    def is_sell_recommended(self, purchase_price, buy_time=0.0) -> tuple[bool, str]:
        # 판매 추천 로직
        # 익절 로직
        if len(self.candle_stick_5minute) < 3:
            return False, ""

        candles = self.candle_stick_5minute
        last = candles[-1]
        prev = candles[-2]

        current_price = last.close_price
        if purchase_price <= 0:
            # 구매 가격이 유효하지 않으면 판매 추천하지 않음
            return False, ""

        profit_rate = (current_price - purchase_price) / purchase_price

        if profit_rate >= TradingParams.TAKE_PROFIT_FORCE:
            # 강제 익절 수익률 이상이면 바로 판매 추천
            return True, f"강제익절 (수익률 {profit_rate * 100:.2f}%)"

        # [2026-04-29 추가] 트레일링 스탑 (수익 보존)
        max_high = 0.0
        # buy_time이 있으면 그 이후의 캔들만, 없으면 최근 12개(1시간) 캔들 검사
        valid_candles = [c for c in candles if c.start_time >= buy_time] if buy_time > 0.0 else candles[-12:]
        if valid_candles:
            max_high = max(c.high_price for c in valid_candles)
            max_profit_rate = (max_high - purchase_price) / purchase_price
            
            # 최고가 기준 수익률이 트리거를 넘었고, 현재가가 최고가 대비 드랍 폭 이상 빠졌다면 익절 검토
            if max_profit_rate >= TradingParams.TRAILING_STOP_TRIGGER:
                drop_rate = (max_high - current_price) / max_high
                if drop_rate >= TradingParams.TRAILING_STOP_DROP:
                    # [2026-04-30 수정] 단, 이미 하락하여 최소 보존 수익률(원금 등) 밑으로 떨어졌다면 
                    # 트레일링 스탑 기회는 지나간 것으로 보고 스탑로스에 맡김 (Whipsaw 방지)
                    if profit_rate >= TradingParams.TRAILING_STOP_MIN_PROFIT:
                        return True, f"트레일링스탑 (고점방어: {max_profit_rate*100:.2f}% -> 현재 {profit_rate*100:.2f}%)"

        # 최소 수익률 이상이 아 니면 기본 익절 판별 안함
        if profit_rate < TradingParams.TAKE_PROFIT_MIN:
            return False, ""

        closes = [c.close_price for c in candles]
        ema20 = self._ema(closes, 20)
        
        # [2026-04-01 추가] 거래량 필터 - 저유동성에서 익절 차단 (미끄러짐 방지)
        if len(candles) >= 11:
            avg_vol = sum(c.volume for c in candles[-11:-1]) / 10
            vol_ratio = last.volume / avg_vol if avg_vol > 0 else 0
            if vol_ratio < TradingParams.MIN_SELL_VOLUME_RATIO:
                return False, ""  # 유동성 부족 시 익절 연기

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
            return False, ""

        # 상승 꺾이면 매도
        return True, f"추세이탈 익절 (수익률 {profit_rate * 100:.2f}%)"
    
    def is_sell_stop_loss_recommended(self, purchase_price) -> tuple[bool, str]:
        # 손절 추천 로직
        local_time = time.localtime()

        # 장마감시간 이후에는 어찌 되었든 판매 추천
        if local_time.tm_hour >= TradingParams.FORCE_SELL_HOUR:
            return True, "장마감강제청산"
        
        if not self.candle_stick_5minute:
            return False, ""
        
        # [2026-04-01 추가] 거래량 필터 - 저유동성에서 손절 차단 (미끄러짐 방지)
        candles = self.candle_stick_5minute
        if len(candles) >= 11:
            avg_vol = sum(c.volume for c in candles[-11:-1]) / 10
            vol_ratio = candles[-1].volume / avg_vol if avg_vol > 0 else 0
            if vol_ratio < TradingParams.MIN_SELL_VOLUME_RATIO:
                return False, ""  # 유동성 부족 시 손절 연기

        # ATR 기반 동적 손절 폭
        current_price = self.candle_stick_5minute[-1].close_price
        atr = self._atr(self.candle_stick_5minute, 14)
        
        stop_loss_ratio = TradingParams.STOP_LOSS_MIN
        if atr is not None and current_price > 0:
            atr_ratio = (atr * TradingParams.ATR_MULTIPLIER) / current_price 
            stop_loss_ratio = max(TradingParams.STOP_LOSS_MIN, min(TradingParams.STOP_LOSS_MAX, atr_ratio))
            
        if current_price <= purchase_price * (1.0 - stop_loss_ratio):
            # 손절 달성
            loss_rate = (current_price - purchase_price) / purchase_price
            return True, f"손절컷(목표: -{stop_loss_ratio*100:.2f}%, 현재: {loss_rate*100:.2f}%)"
            
        return False, ""