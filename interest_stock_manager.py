import json
import os
import time
from datetime import date, timedelta
from filter import SymbolFilter, TradingParams
from typing import List
from common_structure import SymbolItem


class InterestStockItem:
    def __init__(self, pdno: str, prdt_name: str, price: float, volume: int, added_at: float):
        self.stock = SymbolItem(pdno, prdt_name)
        self.price = price
        self.volume = volume
        self.added_at = added_at


class InterestStockManager:
    def __init__(self, cache_file_path: str):
        self.cache_file_path = cache_file_path
        self.buy_list: List[InterestStockItem] = []
        self.load()

    def load(self):
        if os.path.exists(self.cache_file_path):
            try:
                with open(self.cache_file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)

                    for item in data.get("buy_list", []):
                        record = item.get("record", {})
                        pdno = record.get("pdno", "")
                        prdt_name = record.get("prdt_name", "")
                        price = item.get("price", 0)
                        volume = item.get("volume", 0)
                        added_at = item.get("added_at", time.time())
                        if self.is_avoided(pdno, prdt_name, price, volume):
                            continue
                        self.buy_list.append(InterestStockItem(pdno, prdt_name, price, volume, added_at))
            except Exception as e:
                print(f"Failed to load interest stocks from {self.cache_file_path}: {e}")
                self.buy_list = []

        # 로드 시 만료된 종목 자동 제거
        self._purge_expired()

    def save(self):
        os.makedirs(os.path.dirname(self.cache_file_path), exist_ok=True)
        try:
            data = {
                "buy_list": [
                    {
                        "record": {
                            "pdno": item.stock.pdno,
                            "prdt_name": item.stock.prdt_name,
                        },
                        "price": item.price,
                        "volume": item.volume,
                        "added_at": "" if item.added_at is None else item.added_at
                    }
                    for item in self.buy_list
                ]
            }
            with open(self.cache_file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
        except Exception as e:
            print(f"Failed to save interest stocks to {self.cache_file_path}: {e}")

    def clear(self):
        self.buy_list = []
        self.save()

    def _count_trading_days(self, from_ts: float, to_ts: float) -> int:
        """from_ts ~ to_ts 사이의 영업일(월~금) 수를 계산한다."""
        start = date.fromtimestamp(from_ts)
        end = date.fromtimestamp(to_ts)
        count = 0
        current = start
        while current < end:
            current += timedelta(days=1)
            if current.weekday() < 5:
                count += 1
        return count

    def _purge_expired(self):
        """만료 기간(영업일 기준)이 지난 종목을 자동 제거한다."""
        now = time.time()
        before = len(self.buy_list)
        self.buy_list = [
            item for item in self.buy_list
            if self._count_trading_days(item.added_at, now) <= TradingParams.STOCK_EXPIRY_DAYS
        ]
        if len(self.buy_list) != before:
            self.save()

    def is_avoided(self, pdno: str, name: str, price: int = 0, volume: int = 0) -> bool:
        if SymbolFilter.is_not_interested_by_name(name):
            return True

        if SymbolFilter.is_not_interested_by_price(price):
            return True

        return False

    def update_stock(self, pdno: str, name: str, price: int, volume: int) -> bool:
        existing = next((item for item in self.buy_list if item.stock.pdno == pdno), None)

        is_avoided = self.is_avoided(pdno, name, price, volume)
        if is_avoided:
            if existing:
                self.buy_list.remove(existing)
                self.save()
                return True
            return False

        if existing:
            existing.price = price
            existing.volume = volume
            self.buy_list.sort(key=lambda x: x.volume, reverse=True)
            self.save()
            return False

        # 신규 진입 품질 게이트: 최소 거래량 미달시 진입 불가
        if volume < TradingParams.MIN_INTEREST_VOLUME:
            return False

        max_count = TradingParams.INTEREST_STOCK_MAX

        if len(self.buy_list) >= max_count:
            # 만료된 종목 우선 제거
            self._purge_expired()

        if len(self.buy_list) >= max_count:
            # 여전히 꽉 차 있으면 최하위 거래량 종목을 교체
            self.buy_list.sort(key=lambda x: x.volume, reverse=True)
            if volume <= self.buy_list[-1].volume:
                return False
            self.buy_list.pop()

        self.buy_list.append(InterestStockItem(pdno, name, price, volume, time.time()))
        self.buy_list.sort(key=lambda x: x.volume, reverse=True)
        self.save()

        return True

    def get_stocks(self) -> List[SymbolItem]:
        return [item.stock for item in self.buy_list]
