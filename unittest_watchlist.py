import unittest
import os
import time
import tempfile
from unittest.mock import patch
from watchlist import Watchlist
from common_structure import SymbolItem

class TestWatchlist(unittest.TestCase):
    def setUp(self):
        # 독립적인 파일 입출력 테스트를 위한 임시 캐시 파일 생성
        self.fd, self.temp_cache_path = tempfile.mkstemp(suffix=".json")
        os.close(self.fd)

        # 시스템의 다른 파라미터 변경에 영향받지 않게 주요 파라미터를 고정(Mocking)
        self.patchers = [
            patch("filter.TradingParams.WATCHLIST_ITEM_MIN_VOLUME", 1000),
            patch("filter.TradingParams.WATCHLIST_ITEM_MAX_COUNT", 3),
            patch("filter.TradingParams.WATCHLIST_ITEM_MIN_PRICE", 1000),
            patch("filter.TradingParams.WATCHLIST_ITEM_MAX_PRICE", 10000),
            patch("filter.TradingParams.WATCHLIST_ITEM_EXPIRY_DAYS", 3),
        ]
        for p in self.patchers:
            p.start()

        self.watchlist = Watchlist(self.temp_cache_path)

    def tearDown(self):
        for p in self.patchers:
            p.stop()
        
        # 테스트 종료 후 임시 파일 삭제
        if os.path.exists(self.temp_cache_path):
            os.remove(self.temp_cache_path)

    def test_add_valid_stock(self):
        """정상적인 조건의 종목이 잘 추가되는지 테스트"""
        result = self.watchlist.update_stock("000001", "테스트종목", 5000, 2000)
        self.assertTrue(result)
        self.assertEqual(len(self.watchlist.items), 1)
        self.assertEqual(self.watchlist.get_stocks()[0].pdno, "000001")

    def test_filter_by_name(self):
        """이름이나 속성에 의한 필터링 테스트 (SymbolFilter 동작 확인)"""
        # "인버스"가 이름에 포함되어 추가가 거절되어야 함
        result = self.watchlist.update_stock("000002", "곱버스인버스", 5000, 2000)
        self.assertFalse(result)
        self.assertEqual(len(self.watchlist.items), 0)

    def test_filter_by_price_and_volume(self):
        """가격 및 거래량 하한 필터링 테스트"""
        # 가격 상한선 초과 거부 (10000 초과)
        self.assertFalse(self.watchlist.update_stock("000003", "비싼종목", 15000, 2000))
        # 거래량 하한선 미달 거부 (1000 미만)
        self.assertFalse(self.watchlist.update_stock("000004", "거래안됨", 5000, 500))

    def test_sort_by_volume(self):
        """추가/업데이트 시 거래량 순으로 내림차순 정렬되는지 테스트"""
        self.watchlist.update_stock("000001", "종목A", 5000, 2000)
        self.watchlist.update_stock("000002", "종목B", 5000, 5000)
        self.watchlist.update_stock("000003", "종목C", 5000, 1500)

        items = self.watchlist.items
        self.assertEqual(items[0].stock.pdno, "000002")  # 5000이 가장 우선
        self.assertEqual(items[1].stock.pdno, "000001")  # 2000이 다음
        self.assertEqual(items[2].stock.pdno, "000003")  # 1500이 마지막

    def test_update_existing_stock(self):
        """기존 종목 정보 업데이트 시 정보 변경 및 재정렬 확인"""
        self.watchlist.update_stock("000001", "종목A", 5000, 2000)
        self.watchlist.update_stock("000002", "종목B", 5000, 5000)

        # 종목A의 거래량을 대폭 올려 1등으로 만듦
        self.watchlist.update_stock("000001", "종목A", 5500, 9000)
        
        self.assertEqual(len(self.watchlist.items), 2)
        self.assertEqual(self.watchlist.items[0].stock.pdno, "000001")
        self.assertEqual(self.watchlist.items[0].price, 5500)
        self.assertEqual(self.watchlist.items[0].volume, 9000)

    def test_max_count_limit(self):
        """최대 보유 종목 수 초과 방지 테스트 (MAX_COUNT = 3)"""
        self.watchlist.update_stock("000001", "종목1", 5000, 5000)
        self.watchlist.update_stock("000002", "종목2", 5000, 4000)
        self.watchlist.update_stock("000003", "종목3", 5000, 3000)
        
        # 이미 3개가 차있으므로 추가 안 됨
        result = self.watchlist.update_stock("000004", "종목4", 5000, 2000)
        self.assertFalse(result)
        self.assertEqual(len(self.watchlist.items), 3)

    def test_tick_and_purge_expired(self):
        """시간 감소(tick) 후 잔여 시간이 0 이하면 리스트에서 제외되는지 테스트"""
        self.watchlist.update_stock("000001", "종목1", 5000, 5000)
        
        # 처음 부여된 초기 잔여 시간(3일*6.5시간) 임의 검사
        initial_time = 3 * 6.5 * 3600
        self.assertEqual(self.watchlist.items[0].remaining_time, initial_time)
        
        # 시간이 만료되도록 초과하는 값을 tick
        self.watchlist.tick(initial_time + 100)
        self.assertEqual(len(self.watchlist.items), 0)

    @patch("time.time")
    def test_apply_trade_result(self, mock_time):
        """매매 결과에 따른 시간 증감 및 코히전(쿨타임) 로직 테스트"""
        current_time = 10000.0
        mock_time.return_value = current_time

        self.watchlist.update_stock("000001", "종목1", 5000, 5000)
        base_time = self.watchlist.items[0].remaining_time
        
        # 1. 수익 실현: 시간 1일치(6.5 * 3600) 연장 반영
        self.watchlist.apply_trade_result("000001", is_profit=True)
        self.assertEqual(self.watchlist.items[0].remaining_time, base_time + (6.5 * 3600))
        self.assertEqual(self.watchlist.items[0].last_profit_at, current_time)

        # 2. 쿨타임(20분) 내 다시 수익 실현이 들어오면 무시되어야 함
        mock_time.return_value = current_time + 600  # 10분 지남
        self.watchlist.apply_trade_result("000001", is_profit=True)
        self.assertEqual(self.watchlist.items[0].remaining_time, base_time + (6.5 * 3600))  # 증가하지 않음

        # 3. 손실 실현 로직 검증을 위해 20분 이후 세팅 
        mock_time.return_value = current_time + 1500  # 25분 지남 (20 * 60 = 1200초)
        profit_time = self.watchlist.items[0].remaining_time
        self.watchlist.apply_trade_result("000001", is_profit=False)
        self.assertEqual(self.watchlist.items[0].remaining_time, profit_time - (3 * 3600))
        self.assertEqual(self.watchlist.items[0].last_loss_at, mock_time.return_value)

    def test_save_and_load(self):
        """캐시 파일 저장 및 재로드 정합성 테스트"""
        self.watchlist.update_stock("111111", "저장테스트", 5000, 5000)
        self.watchlist.items[0].remaining_time = 12345.0
        self.watchlist.save()

        # 새로운 객체로 동일한 캐시 파일 로드
        new_watchlist = Watchlist(self.temp_cache_path)
        self.assertEqual(len(new_watchlist.items), 1)
        self.assertEqual(new_watchlist.items[0].stock.pdno, "111111")
        self.assertEqual(new_watchlist.items[0].remaining_time, 12345.0)

if __name__ == "__main__":
    unittest.main()
