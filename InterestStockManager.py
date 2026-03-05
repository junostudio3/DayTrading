import json
import os
from typing import List, Dict, Any

class InterestStockManager:
    def __init__(self, cache_file_path: str = "./cache/interest_stocks.json"):
        self.cache_file_path = cache_file_path
        self.buy_list: List[Dict[str, Any]] = []
        self.explore_index: int = 0
        self.load()

    def load(self):
        if os.path.exists(self.cache_file_path):
            try:
                with open(self.cache_file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        self.buy_list = data.get("buy_list", [])
                        self.explore_index = data.get("explore_index", 0)
                    elif isinstance(data, list):
                        self.buy_list = data
                        self.explore_index = 0
            except Exception as e:
                print(f"Failed to load interest stocks from {self.cache_file_path}: {e}")
                self.buy_list = []
                self.explore_index = 0

    def save(self):
        os.makedirs(os.path.dirname(self.cache_file_path), exist_ok=True)
        try:
            data = {
                "buy_list": self.buy_list,
                "explore_index": self.explore_index
            }
            with open(self.cache_file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
        except Exception as e:
            print(f"Failed to save interest stocks to {self.cache_file_path}: {e}")

    def clear(self):
        self.buy_list = []
        self.explore_index = 0
        self.save()

    def update_stock(self, symbol: str, name: str, price: float, volume: int) -> bool:
        existing = next((item for item in self.buy_list if item["record"].get("pdno") == symbol), None)

        if price <= 0:
            # 가격이 0이하인 경우는 관심 종목에서 제거한다.
            if existing:
                self.buy_list.remove(existing)
                self.save()
                return True  # 종목이 제거되었으므로 리스트가 변경되었다고 간주한다.
            return False  # 종목이 존재하지 않으므로 리스트 변경이 없다.

        if price > 20000:
            # 가격이 너무 높으면 단타가 어려울 수 있으므로 관심 종목에서 제거한다.
            if existing:
                self.buy_list.remove(existing)
                self.save()
                return True  # 종목이 제거되었으므로 리스트가 변경되었다고 간주한다.
            return False  # 종목이 존재하지 않으므로 리스트 변경이 없다.

        if existing:
            existing["price"] = price
            existing["volume"] = volume
            self.buy_list.sort(key=lambda x: x["volume"], reverse=True)
            self.save()
            return False  # 기존 종목의 가격/거래량 업데이트는 리스트 변경으로 간주하지 않는다.

        # self.buy_list는 최대 10개까지만 유지한다
        if len(self.buy_list) >= 10:
            # volume이 가장 작은 종목과 비교해서 새 종목이 더 거래량이 많으면 교체한다
            if volume < self.buy_list[-1]["volume"]:
                return False  # 새 종목이 거래량이 더 적으면 추가하지 않는다
            
            self.buy_list.pop()  # 거래량이 가장 작은 종목 제거

        self.buy_list.append({
            "record": {
                "pdno": symbol,
                "prdt_name": name,
            },
            "price": price,
            "volume": volume
        })

        self.buy_list.sort(key=lambda x: x["volume"], reverse=True)
        self.save()

        return True  # 새로운 종목이 추가되었으므로 리스트가 변경되었다고 간주한다.

    def get_buy_list(self) -> List[Dict[str, Any]]:
        return self.buy_list

    def get_buy_records(self) -> List[Dict[str, str]]:
        return [item["record"] for item in self.buy_list]

    def set_explore_index(self, index: int):
        self.explore_index = index
        self.save()

    def get_explore_index(self) -> int:
        return self.explore_index
