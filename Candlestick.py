class Candlestick:
    def __init__(self, open_price, high_price, low_price, close_price):
        self.start_time = None  # 캔들스틱의 시작 시간
        self.end_time = None    # 캔들스틱의 종료 시간
        self.open_price = open_price
        self.high_price = high_price
        self.low_price = low_price
        self.close_price = close_price

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
