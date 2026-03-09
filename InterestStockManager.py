import json
import os
import time
from typing import List, Dict, Any
from StockItem import StockItem


class InterestStockItem:
    def __init__(self, pdno: str, prdt_name: str, price: float, volume: int, added_at: float):
        self.stock = StockItem(pdno, prdt_name)
        self.price = price
        self.volume = volume
        self.added_at = added_at


class InterestStockManager:
    def __init__(self, cache_file_path: str = "./cache/interest_stocks.json"):
        self.cache_file_path = cache_file_path
        self.buy_list: List[InterestStockItem] = []
        self.explore_index: int = 0
        self.keep_7days: bool = False
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
                            # 옛날에 저장된 항목 중 피해야 할 종목이 있을 수 있으므로 로드 시에도 체크한다
                            continue
                        self.buy_list.append(InterestStockItem(pdno, prdt_name, price, volume, added_at))

                    self.explore_index = data.get("explore_index", 0)
                    self.keep_7days = data.get("keep_7days", False)
            except Exception as e:
                print(f"Failed to load interest stocks from {self.cache_file_path}: {e}")
                self.buy_list = []
                self.explore_index = 0
                self.keep_7days = False

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
                ],
                "explore_index": self.explore_index,
                "keep_7days": self.keep_7days
            }
            with open(self.cache_file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
        except Exception as e:
            print(f"Failed to save interest stocks to {self.cache_file_path}: {e}")

    def clear(self):
        self.buy_list = []
        self.explore_index = 0
        self.keep_7days = False
        self.save()
  
    def is_avoided(self, pdno: str, name: str, price: int = 0, volume: int = 0) -> bool:
        # 이름에 인버스 또는 레버가 포함된 종목은 피한다
        if "인버스" in name or "레버" in name:
            return True
        
        # 가격이 너무 큰 종목은 피한다 (하드코딩)
        if price > 20000:
            return True

        # 가격이 너무 낮은 종목은 % 계산시 작은 값으로도 큰 변동이 발생할 수 있으므로 피한다 (하드코딩)
        if price <= 4000:
            return True

        return False

    def update_stock(self, pdno: str, name: str, price: int, volume: int) -> bool:
        existing = next((item for item in self.buy_list if item.stock.pdno == pdno), None)

        is_avoided = self.is_avoided(pdno, name, price, volume)
        if is_avoided:
            if existing:
                # 기존에 관심 종목으로 등록되어 있었지만 이제는 피해야 하는 종목이 되었으므로 목록에서 제거한다
                self.buy_list.remove(existing)
                self.save()
                return True
            return False

        if existing:
            existing.price = price
            existing.volume = volume
            if existing.added_at is None:
                existing.added_at = time.time()
            self.buy_list.sort(key=lambda x: x.volume, reverse=True)
            self.save()
            return False

        # self.buy_list는 기본적으로 Top 10을 유지한다 (보호 항목 제외)
        if len(self.buy_list) >= 10:
            candidates = None
            if self.keep_7days:
                now = time.time()
                seven_days = 7 * 24 * 60 * 60
                candidates = [item for item in self.buy_list if (now - item.added_at) > seven_days]
            
            if candidates:
                # 일주일 이상된 항목이 있다면 그 중 가장 낮은 거래량을 가진 항목을 찾아서 제거한다
                lowest_volume_item = min(candidates, key=lambda x: x.volume)
                self.buy_list.remove(lowest_volume_item)
            else:
                # volume이 10번째 종목보다 작으면 탑 10에 들 수 없으므로 무시
                self.buy_list.sort(key=lambda x: x.volume, reverse=True)
                if volume <= self.buy_list[9].volume:
                    return False
                self.buy_list.pop()  # 10번째 항목 제거

        # 조건을 만족하여 탑 10에 진입하는 새 종목
        self.buy_list.append(InterestStockItem(pdno, name, price, volume, time.time()))
        self.buy_list.sort(key=lambda x: x.volume, reverse=True)
        self.save()

        return True

    def update_trade_date(self, pdno: str):
        existing = next((item for item in self.buy_list if item.stock.pdno == pdno), None)
        if existing:
            existing.added_at = time.time()
            self.save()

    def enable_keep_7days(self):
        self.keep_7days = True
        self.save()

    def get_stocks(self) -> List[StockItem]:
        return [item.stock for item in self.buy_list]

    def set_explore_index(self, index: int):
        self.explore_index = index
        self.save()

    def get_explore_index(self) -> int:
        return self.explore_index
