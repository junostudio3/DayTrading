import os
import time
from price_analysis_item import PriceAnalysisItem
from candlestick import Candlestick
from common_structure import SymbolItem

class PriceAnalysis:
    def __init__(self, cache_dir):
        # cache_file originally pointed to a json file; we treat its dirname as
        # the directory that will contain per-pdno databases.
        self.cache_dir = cache_dir
        os.makedirs(self.cache_dir, exist_ok=True)

        self.items: dict[str, PriceAnalysisItem] = {}

        # load any existing pdno databases
        self._load_cache()

    def _load_cache(self):
        # load per-pdno databases
        now = time.time()
        for fname in os.listdir(self.cache_dir):
            if not fname.endswith(".db"):
                continue
            pdno = fname[:-3]
            if pdno in self.items:
                # already loaded via migration
                continue
            item = PriceAnalysisItem(SymbolItem(pdno, pdno), self.cache_dir)
            self.items[pdno] = item

            # 만약 데이터가 1주일 이상 오래된 경우, 캐시에서 제거 및 SQLite 파일 삭제
            if item.candle_stick_5minute:
                last_candle_time = item.candle_stick_5minute[-1].end_time
                if now - last_candle_time > 7 * 24 * 3600:
                    del self.items[pdno]
                    os.remove(item.db_path)

    def add_price(self, symbol_item: SymbolItem, one_candle : Candlestick) -> bool:
        is_changed = False
        if symbol_item.pdno not in self.items:
            self.items[symbol_item.pdno] = PriceAnalysisItem(symbol_item, self.cache_dir)  # 이름은 심볼로 초기화
            is_changed = True
        if self.items[symbol_item.pdno].add_price(one_candle):
            is_changed = True
        return is_changed
    
    def is_purchase_overtime(self, pdno):
        if pdno in self.items:
            return self.items[pdno].is_purchase_overtime()
        return False

    def is_purchase_recommended(self, pdno):
        if pdno in self.items:
            return self.items[pdno].is_purchase_recommended()
        return False
    
    def is_sell_recommended(self, pdno, purchase_price, buy_time=0.0):
        if pdno in self.items:
            return self.items[pdno].is_sell_recommended(purchase_price, buy_time)
        return False

    def is_sell_stop_loss_recommended(self, pdno, purchase_price):
        if pdno in self.items:
            return self.items[pdno].is_sell_stop_loss_recommended(purchase_price)
        return False
