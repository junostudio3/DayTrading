import os
import time
from PriceAnalysisItem import PriceAnalysisItem

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
        now = time.time()
        for fname in os.listdir(self.cache_dir):
            if not fname.endswith(".db"):
                continue
            symbol = fname[:-3]
            if symbol in self.items:
                # already loaded via migration
                continue
            item = PriceAnalysisItem(symbol, symbol, self.cache_dir)
            self.items[symbol] = item

            # 만약 데이터가 1주일 이상 오래된 경우, 캐시에서 제거 및 SQLite 파일 삭제
            if item.candle_stick_5minute:
                last_candle_time = item.candle_stick_5minute[-1].end_time
                if now - last_candle_time > 7 * 24 * 3600:
                    del self.items[symbol]
                    os.remove(item.db_path)

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
