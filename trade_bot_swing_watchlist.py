import json
import os
import time
from filter import SymbolFilter, TradingParams
from typing import List
from common_structure import SymbolItem
from dataclasses import dataclass

@dataclass
class SwingWatchlistItem:
    stock: SymbolItem
    price: float
    volume: int
    remaining_time: float 
    last_profit_at: float = 0
    last_loss_at: float = 0


class SwingWatchlist:
    def __init__(self, cache_file_path: str):
        self.cache_file_path = cache_file_path
        self.items: List[SwingWatchlistItem] = []
        self.load()

    def load(self):
        if os.path.exists(self.cache_file_path):
            try:
                with open(self.cache_file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)

                    for item in data.get("items", []):
                        record = item.get("record", {})
                        pdno = record.get("pdno", "")
                        prdt_name = record.get("prdt_name", "")
                        price = item.get("price", 0)
                        volume = item.get("volume", 0)
                        remaining_time = item.get("remaining_time", TradingParams.SWINGWATCHLIST_ITEM_EXPIRY_DAYS * 6.5 * 3600)
                        last_profit_at = item.get("last_profit_at", 0)
                        last_loss_at = item.get("last_loss_at", 0)
                        if self.is_avoided(pdno, prdt_name, price, volume):
                            continue
                        self.items.append(SwingWatchlistItem(
                            stock=SymbolItem(pdno, prdt_name),
                            price=price,
                            volume=volume,
                            remaining_time=remaining_time,
                            last_profit_at=last_profit_at,
                            last_loss_at=last_loss_at,
                        ))
            except Exception as e:
                print(f"Failed to load watchlist from {self.cache_file_path}: {e}")
                self.items = []

        # 로드 시 만료된 종목 자동 제거
        self._purge_expired()

    def save(self):
        os.makedirs(os.path.dirname(self.cache_file_path), exist_ok=True)
        try:
            data = {
                "items": [
                    {
                        "record": {
                            "pdno": item.stock.pdno,
                            "prdt_name": item.stock.prdt_name,
                        },
                        "price": item.price,
                        "volume": item.volume,
                        "remaining_time": item.remaining_time,
                        "last_profit_at": item.last_profit_at,
                        "last_loss_at": item.last_loss_at,
                    }
                    for item in self.items
                ]
            }
            with open(self.cache_file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
        except Exception as e:
            print(f"Failed to save watchlist to {self.cache_file_path}: {e}")

    def clear(self):
        self.items = []
        self.save()

    def tick(self, seconds: float):
        """일정 시간마다 잔여 시간을 감소시킨다. (장시간 동안 동작 시 호출됨)"""
        for item in self.items:
            item.remaining_time -= seconds
        self._purge_expired()

    def _purge_expired(self):
        """잔여 시간이 0 이하가 된 종목을 자동 제거한다."""
        before = len(self.items)
        self.items = [
            item for item in self.items
            if item.remaining_time > 0
        ]
        if len(self.items) != before:
            self.save()

    def is_existing(self, pdno: str) -> bool:
        return any(item.stock.pdno == pdno for item in self.items)

    def is_avoided(self, pdno: str, name: str, price: int = 0, volume: int = 0) -> bool:
        if SymbolFilter.is_not_watched_by_name(name):
            return True

        if SymbolFilter.is_not_watched_by_price(price):
            return True

        return False

    def update_stock(self, pdno: str, name: str, price: int, volume: int) -> bool:
        existing = next((item for item in self.items if item.stock.pdno == pdno), None)

        is_avoided = self.is_avoided(pdno, name, price, volume)
        if is_avoided:
            if existing:
                self.items.remove(existing)
                self.save()
                return True
            return False

        if existing:
            existing.price = price
            existing.volume = volume
            self.items.sort(key=lambda x: x.volume, reverse=True)
            self.save()
            return False

        # 신규 진입 품질 게이트: 최소 거래량 미달시 진입 불가
        if volume < TradingParams.WATCHLIST_ITEM_MIN_VOLUME:
            return False

        max_count = TradingParams.SWINGWATCHLIST_ITEM_MAX_COUNT

        if len(self.items) >= max_count:
            # 만료된 종목 우선 제거
            self._purge_expired()

        if len(self.items) >= max_count:
            # 여전히 꽉 차 있으면 추가 진입 불가
            return False

        initial_time = TradingParams.SWINGWATCHLIST_ITEM_EXPIRY_DAYS * 6.5 * 3600
        self.items.append(SwingWatchlistItem(
            stock=SymbolItem(pdno, name),
            price=price,
            volume=volume,
            remaining_time=initial_time
        ))
        self.items.sort(key=lambda x: x.volume, reverse=True)
        self.save()

        return True

    def get_stocks(self) -> List[SymbolItem]:
        return [item.stock for item in self.items]
