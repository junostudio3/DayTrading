import time


class PriceAnalysisItem:
    def __init__(self, symbol, name):
        self.symbol = symbol
        self.name = name
        self.prices = []
        self.min_price = None
        self.max_price = None

    def add_price(self, price):
        timestamp = time.time()
        self.prices.append((timestamp, price))
        if self.min_price is None or price < self.min_price:
            self.min_price = price

        if self.max_price is None or price > self.max_price:
            self.max_price = price

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
