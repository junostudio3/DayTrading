class Candlestick:
    def __init__(self, open_price, high_price, low_price, close_price, volume=0):
        self.start_time = None  # 캔들스틱의 시작 시간
        self.end_time = None    # 캔들스틱의 종료 시간
        self.open_price = open_price
        self.high_price = high_price
        self.low_price = low_price
        self.close_price = close_price
        self.volume = volume

    def is_bullish(self):
        return self.close_price > self.open_price

    def is_bearish(self):
        return self.close_price < self.open_price

    def get_body_length(self):
        return abs(self.close_price - self.open_price)

    def get_upper_shadow_length(self):
        return self.high_price - max(self.open_price, self.close_price)

    def get_lower_shadow_length(self):
        return min(self.open_price, self.close_price) - self.low_price

class CandlestickMerger:
    def __init__(self):
        # 1분봉 캔들을 시간 키값으로 저장하여 중복 시 덮어쓰기 가능하게 함
        self.candles_1m = {}

    def add_candle(self, candle):
        """
        분봉 캔들을 추가하거나 덮어씁니다.
        :param candle: Candlestick 객체
        """
        time_key = candle.start_time  # 시작 시간을 키로 사용
        self.candles_1m[time_key] = candle

    def get_merged_candle(self):
        """
        저장된 봉들을 조합하여 Candlestick을 생성하여 반환합니다.
        """
        if not self.candles_1m:
            return None
        
        # 시간에 따라 정렬하여 시가와 종가를 정확하게 파악
        sorted_keys = sorted(self.candles_1m.keys())
        candles = [self.candles_1m[k] for k in sorted_keys]
        
        first_candle = candles[0]
        last_candle = candles[-1]
        
        open_price = first_candle.open_price
        close_price = last_candle.close_price
        high_price = max(c.high_price for c in candles)
        low_price = min(c.low_price for c in candles)
        volume = sum(c.volume for c in candles)
        
        c5m = Candlestick(open_price, high_price, low_price, close_price, volume)
        c5m.start_time = first_candle.start_time
        c5m.end_time = last_candle.end_time
        
        return c5m
