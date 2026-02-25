import time
from Candlestick import Candlestick

class PriceAnalysisItem:
    def __init__(self, symbol, name):
        self.symbol = symbol
        self.name = name
        self.candle_stick_5minute: list[Candlestick] = []

    def add_price(self, price):
        timestamp = time.time()
        if not self.candle_stick_5minute or timestamp - self.candle_stick_5minute[-1].start_time >= 300:
            # 새로운 캔들스틱 생성
            new_candle = Candlestick(price, price, price, price)
            new_candle.start_time = timestamp
            new_candle.end_time = timestamp
            self.candle_stick_5minute.append(new_candle)
        else:
            # 기존 캔들스틱 업데이트
            current_candle = self.candle_stick_5minute[-1]
            current_candle.end_time = timestamp
            current_candle.close_price = price
            current_candle.high_price = max(current_candle.high_price, price)
            current_candle.low_price = min(current_candle.low_price, price)
        
    def is_purchase_recommended(self):
        # 구매 추천 로직
        return False  # 실제 로직은 여기에 구현되어야 함

class PriceAnalysis:
    def __init__(self):
        self.items: dict[str, PriceAnalysisItem] = {}

    def add_price(self, symbol, price):
        if symbol not in self.items:
            self.items[symbol] = PriceAnalysisItem(symbol, symbol)  # 이름은 심볼로 초기화
        self.items[symbol].add_price(price)
