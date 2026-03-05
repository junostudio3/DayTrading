import json
import os
import time
from typing import List, Dict, Any

class InterestStockManager:
    def __init__(self, cache_file_path: str = "./cache/interest_stocks.json"):
        self.cache_file_path = cache_file_path
        self.buy_list: List[Dict[str, Any]] = []
        self.explore_index: int = 0
        self.keep_7days: bool = False
        self.load()

    def load(self):
        if os.path.exists(self.cache_file_path):
            try:
                with open(self.cache_file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        self.buy_list = data.get("buy_list", [])
                        self.explore_index = data.get("explore_index", 0)
                        self.keep_7days = data.get("keep_7days", False)
                    elif isinstance(data, list):
                        # 이전 버전 호환: 리스트 형태로 저장된 경우 buy_list로 간주
                        self.buy_list = data
                        self.explore_index = 0
                        self.keep_7days = False
            except Exception as e:
                print(f"Failed to load interest stocks from {self.cache_file_path}: {e}")
                self.buy_list = []
                self.explore_index = 0
                self.keep_7days = False

    def save(self):
        os.makedirs(os.path.dirname(self.cache_file_path), exist_ok=True)
        try:
            data = {
                "buy_list": self.buy_list,
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

    def update_stock(self, symbol: str, name: str, price: float, volume: int) -> bool:
        existing = next((item for item in self.buy_list if item["record"].get("pdno") == symbol), None)

        if price <= 0 or price > 20000:
            if existing:
                self.buy_list.remove(existing)
                self.save()
                return True
            return False

        if existing:
            existing["price"] = price
            existing["volume"] = volume
            if "added_at" not in existing:
                existing["added_at"] = time.time()
            self.buy_list.sort(key=lambda x: x["volume"], reverse=True)
            self.save()
            return False

        # self.buy_list는 기본적으로 Top 10을 유지한다 (보호 항목 제외)
        if len(self.buy_list) >= 10:
            candidates = None
            if self.keep_7days:
                now = time.time()
                seven_days = 7 * 24 * 60 * 60
                candidates = [item for item in self.buy_list if (now - item.get("added_at", now)) > seven_days]
            
            if candidates:
                # 일주일 이상된 항목이 있다면 그 중 가장 낮은 거래량을 가진 항목을 찾아서 제거한다
                lowest_volume_item = min(candidates, key=lambda x: x["volume"])
                self.buy_list.remove(lowest_volume_item)
            else:
                # volume이 10번째 종목보다 작으면 탑 10에 들 수 없으므로 무시
                self.buy_list.sort(key=lambda x: x["volume"], reverse=True)
                if volume <= self.buy_list[9]["volume"]:
                    return False
                self.buy_list.pop()  # 10번째 항목 제거

        # 조건을 만족하여 탑 10에 진입하는 새 종목
        self.buy_list.append({
            "record": {
                "pdno": symbol,
                "prdt_name": name,
            },
            "price": price,
            "volume": volume,
            "added_at": time.time()
        })

        self.buy_list.sort(key=lambda x: x["volume"], reverse=True)
        self.save()

        return True

    def update_trade_date(self, symbol: str):
        existing = next((item for item in self.buy_list if item["record"].get("pdno") == symbol), None)
        if existing:
            existing["added_at"] = time.time()
            self.save()

    def enable_keep_7days(self):
        self.keep_7days = True
        self.save()

    def get_buy_list(self) -> List[Dict[str, Any]]:
        return self.buy_list

    def get_buy_records(self) -> List[Dict[str, str]]:
        return [item["record"] for item in self.buy_list]

    def set_explore_index(self, index: int):
        self.explore_index = index
        self.save()

    def get_explore_index(self) -> int:
        return self.explore_index
