from api.market_data_service import MarketDataService
from api.kis_user import KisUser
from api.kis_user import KisUserManager
from api.special_days import SpecialDays
from KisKey import data_go_kr_api_key
from api.info_kosdaq import load_kosdaq_master
from api.info_kospi import load_kospi_master
from price_analysis import PriceAnalysis
from typing import Optional
from typing import List
from common_structure import SymbolItem
from symbol_snapshot_cache import SymbolSnapshot, SymbolSnapshotCache
from filter import TradingParams
from trade_bot_daily_comm import TradeBotDailyComm
from trade_bot_swing_comm import TradeBotSwingComm

import io
import os
import time
import urllib.request
import zipfile


class TradeBot:
    def __init__(self):
        import threading
        self._price_lock = threading.Lock()
        # print로 로그를 남기도록 한다. (TradingEngine이 가동되면 log 함수는 엔진의 로그 함수로 대체된다.)
        self.log = print
        self.trade_log = None
        self.symbol_snapshot_cache = SymbolSnapshotCache("./cache/symbol_snapshot_cache.db")
        self.price_analysis = PriceAnalysis("./cache/price_analysis/")
        self.daily = TradeBotDailyComm(self)
        self.swing = TradeBotSwingComm(self)
        self.price_update_interval_sec = 2.5
        self.last_price_update_at: dict[str, float] = {}
        self.valid_pdno_set: set[str] = set()
        self.is_running = None

        self.snapshot_collect_candidates: list[SymbolItem] = []
        self._snapshot_toggle = False
        
        # 시장 지수 정보
        self.market_index_kosdaq: float = 0.0
        self.market_index_kosdaq_drop_rate: float = 0.0

        self.user_manager = KisUserManager()
        # KisKey.json 파일에서 사용자 정보를 읽어와서 user_manager에 추가한다.
        self._load_users("./KisKey.json")

        if len(self.user_manager.users) == 0:
            raise ValueError("사용자 정보가 없습니다. KisKey.json 파일을 확인해주세요.")
        else:
            # 가격 조회 서비스 초기화
            self.market_data_service = MarketDataService(self.user_manager.users[0].auth)

        for user in self.user_manager.users:
            try:
                self.daily.add_bot(user)
                if user.use_swing_bot:
                    self.swing.add_bot(user)
            except Exception as e:
                self.log(f"사용자 {user.app_id}에 대한 봇 초기화 중 오류가 발생했습니다: {e}")
                continue

    def _load_users(self, json_path: str):
        # json_path 경로에 있는 JSON 파일에서 사용자 정보를 읽어와서 user_manager에 추가한다.
        # JSON 파일은 사용자 정보의 리스트 형태로 되어 있어야 한다.
        # 각 사용자 정보는 app_id, api_key, api_secret, account_number, is_virtual 필드를 포함해야 한다.
        import json
        if not os.path.exists(json_path):
            self.log(f"사용자 정보 파일이 존재하지 않습니다: {json_path}")
            return

        try:
            with open(json_path, "r") as f:
                users_data = json.load(f)
                if not "users" in users_data:
                    self.log(f"사용자 정보 항목에 'users' 필드가 없습니다. 항목을 건너뜁니다: {users_data}")
                    return

                for user_data in users_data["users"]:
                    is_virtual = user_data["is_virtual"]
                    user = KisUser(user_data["id"],
                        user_data["key"],
                        user_data["secret"],
                        user_data["account"],
                        is_virtual,
                        user_data["use_swing_bot"],
                        self.log)
                    
                    is_valid = True
                    while True:
                        if user.update_account(5):
                            break
                        if is_virtual:
                            # 모의투자 때문에 시작을 못하는 것은 좋지 않으므로
                            # 모의투자 계좌는 계좌 정보 업데이트에 실패하더라도 계속 진행한다.
                            is_valid = False
                            break
                        time.sleep(1)
                    if not is_valid:
                        self.log(f"사용자 {user.app_id}는 모의투자 계좌가 계좌 정보 업데이트에 실패했습니다. 무시됩니다. 추후 확인하세요")
                        continue
                    self.user_manager.add_user(user)
        except Exception as e:
            self.log(f"사용자 정보 파일을 읽어오는 중 오류가 발생했습니다: {e}")

    def _day_initialize(self, now: float) -> bool:
        local_time = time.localtime(now)
        date_str = time.strftime("%Y-%m-%d", local_time)

        # 장 시작 전에 관심 종목 스냅샷 수집 후보 리스트를 업데이트한다.
        # 서버 기동 시 마스터 파일 다운로드 및 압축 해제
        self._download_and_extract_master_files()
        # 관심 종목 스냅샷 수집 후보 리스트 업데이트
        self._update_snapshot_collect_candidates()
        get_holiday_success = False
        for loop in range(5):
            try:
                self._is_now_holiday = SpecialDays.is_holiday(local_time, data_go_kr_api_key)
                get_holiday_success = True
                break
            except Exception as e:
                time.sleep(1)  # 잠시 대기 후 재시도

        if not get_holiday_success:
            self._is_now_holiday = False
            self.log("공휴일API는 쓸대없는 동작을 방지하기 위한 참고용 정보이므로, API 요청에 실패하더라도 오늘이 휴일이 아닌 것으로 간주하고 봇을 동작시킵니다.")

        self._current_date = date_str
        self.daily_start_logged = False
        self.daily_end_logged = False
        self.is_running = None

        if self._is_now_holiday:
            self.log(f"오늘은 {date_str}로 휴일입니다. 봇이 동작하지 않습니다.")
        return True

    def _download_and_extract_master_files(self):
        base_url = "https://new.real.download.dws.co.kr/common/master/"
        files = ["kospi_code.mst", "kosdaq_code.mst"]
        info_dir = "./cache/information"
        os.makedirs(info_dir, exist_ok=True)
        
        for file_name in files:
            zip_url = f"{base_url}{file_name}.zip"
            self.log(f"Downloading {zip_url}...")
            try:
                req = urllib.request.Request(zip_url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req) as response:
                    with zipfile.ZipFile(io.BytesIO(response.read())) as z:
                        z.extract(file_name, path=info_dir)
                        self.log(f"Extracted {file_name} to {info_dir}")
            except Exception as e:
                self.log(f"Failed to download or extract {file_name}: {e}")

    def get_user_app_ids(self) -> List[str]:
        return [user.app_id for user in self.user_manager.users]

    def set_logger(self, log):
        self.log = log
        self.user_manager.set_logger(log)
        self.daily.set_logger(log)
        self.swing.set_logger(log)

    def set_trade_logger(self, log):
        self.trade_log = log
        self.daily.set_trade_logger(log)
        self.swing.set_trade_logger(log)

    def display_account_info(self):
        self.daily.display_account_info()
        self.swing.display_account_info()

    def update_market_and_stock_data(self, now: float):
        local_time = time.localtime(now)
        date_str = time.strftime("%Y-%m-%d", local_time)

        if getattr(self, '_current_date', None) != date_str:
            # 날짜가 바뀌었으므로 일별 초기화 작업을 수행한다.
            self._day_initialize(now)
            return

        if getattr(self, '_is_now_holiday', False):
            # 오늘이 휴일인 경우에는 아무 작업도 하지 않는다.
            return
    
        if self.is_running is False:
            return
        
        if self.is_running is None:
            # is_running이 None인 경우는 서버가 처음 시작된 직후이다
            # 한번은 업데이트를 시도하고 is_running을 False로 설정한다
            self.is_running = False

        if not hasattr(self, '_last_watchlist_tick_time'):
            self._last_watchlist_tick_time = now

        if now - self._last_watchlist_tick_time >= 600:
            self.daily.update_tick(600)
            self.swing.update_tick(600)
            self._last_watchlist_tick_time = now

        self._update_market_data(now)
        self._update_watchlist(now)

    def process_once(self, app_id: str):
        if getattr(self, '_current_date', None) == None:
            # 현재 날짜 정보가 없으므로 대기한다.
            return

        '''
        장 시작 여부 확인
         - 장이 시작되지 않았으면, 장이 시작될 때까지 대기한다.
         - 장이 시작되면, _process_step 함수를 호출하여 매매 로직을 실행한다.
        '''
        now = time.time()
        local_time = time.localtime(now)

        if getattr(self, '_is_now_holiday', False):
            # 오늘이 휴일인 경우에는 아무 작업도 하지 않는다.
            return

        if not self.is_market_open(now):
            if self.is_running is True:
                # 장이 열려 있다가 닫힌 경우
                if not self.daily_end_logged and local_time.tm_hour >= 15 and local_time.tm_min >= 30:
                    # 모든 봇의 계좌 정보를 업데이트하고 기록한다.
                    for bot in self.daily.bots.values():
                        bot.update_account()
                        bot.record_account_history()
                    self.daily_end_logged = True

                if local_time.tm_wday >= 5:
                    self.log("장이 쉬는 날입니다. 토요일과 일요일에는 동작하지 않습니다.")
                else:
                    self.log("장외 시간입니다. 9:00 ~ 15:30 사이에만 동작합니다.")

            self.is_running = False
            return

        if self.is_running is False:
            # 장이 닫혀 있다가 열린 경우 (장 시작)
            if not self.daily_start_logged:
                # 장 시작 시점에 모든 봇의 계좌 정보를 업데이트하고 기록한다.
                for bot in self.daily.bots.values():
                    bot.update_account()
                    bot.record_account_history()
                self.daily_start_logged = True

        self.is_running = True

        self.daily.process_once(app_id, now)
        self.swing.process_once(app_id, now)

    def is_market_open(self, now: Optional[float] = None) -> bool:
        if now is None:
            now = time.time()

        local_time = time.localtime(now)
        if local_time.tm_wday >= 5:
            return False

        if local_time.tm_hour < 9:
            return False
        if local_time.tm_hour > 15:
            return False
        if local_time.tm_hour == 15 and local_time.tm_min > 30:
            return False
        return True

    def price_analysis_items(self, pdno: str):
        if pdno in self.price_analysis.items:
            return self.price_analysis.items[pdno]
        return None

    def place_manual_buy(self, app_id: str, pdno: str, quantity: int, price: int = None):
        self.swing.manual_buy(app_id, pdno, quantity, price)
        
    def place_manual_sell(self, app_id: str, pdno: str, quantity: int, price: int = None):
        self.swing.manual_sell(app_id, pdno, quantity, price)

    def get_dashboard_snapshot(self, app_id: str) -> Optional[dict]:
        bot = self.daily.bots.get(app_id)
        if bot:
            snapshot = bot.get_dashboard_snapshot()
            if snapshot:
                swing_bot = self.swing.bots.get(app_id)
                if swing_bot:
                    swing_snap = swing_bot.get_dashboard_snapshot()
                    if swing_snap and "swing_watch" in swing_snap:
                        snapshot["swing_watch"] = swing_snap["swing_watch"]
            return snapshot
        return None

    def _update_watchlist(self, now: float):
        # 8시부터 4시 30분 사이에만 관심 종목을 탐색한다.
        # 미리 준비하는 목적이어서 장 시작 조금 전부터 탐색을 시작한다.
        current_time = time.localtime(now)
        if current_time.tm_hour < 8 or (current_time.tm_hour == 16 and current_time.tm_min > 30) or current_time.tm_hour > 16:
            return

        if len(self.snapshot_collect_candidates) == 0:
            # 한번씩은 모든 종목을 탐색했다.
            # 모든 데이터가 symbol_snapshot_cache에 저장되어 있을 것이다
            # 이제부터는 거래량 우선과 가장 오래된 종목을 번갈아 가며 30분 TTL이 지난 종목을 갱신한다.
            if self._snapshot_toggle:
                symbol_item = self.symbol_snapshot_cache.get_oldest_snapshot_symbol(min_age_seconds=1800)
            else:
                symbol_item = self.symbol_snapshot_cache.get_high_volume_stale_symbol(min_age_seconds=1800)

            if symbol_item is None:
                return

            if self.is_valid_pdno(symbol_item.pdno) is False:
                self.log(f"심볼 스냅샷 캐시에서 가져온 종목이 유효하지 않아 캐시에서 삭제합니다. pdno: {symbol_item.pdno} name: {symbol_item.prdt_name}")
                self.symbol_snapshot_cache.remove_snapshot(symbol_item.pdno)
                return

            self._snapshot_toggle = not self._snapshot_toggle
        else:
            symbol_item = self.snapshot_collect_candidates.pop(0)

        if symbol_item is None:
            return

        pdno = symbol_item.pdno
        name = symbol_item.prdt_name
        if not pdno:
            return

        try:
            # 관심 종목의 전일 종가와 거래량을 조회하여 관심 종목 리스트를 업데이트한다.
            price, volume = self.market_data_service.get_previous_day_price_and_volume(pdno)

            if price is None or volume is None:
                return

            price = int(price)
            volume = int(volume)
        except Exception as e:
            self.log(f"관심 종목 탐색 중 오류가 발생했습니다. pdno: {pdno} name: {name} error: {e}")
            return
        
        # 스냅샷 캐시 갱신 (TTL 타임스탬프 업데이트)
        snapshot = SymbolSnapshot(symbol_item, now, price, volume)
        self.symbol_snapshot_cache.add_snapshot(snapshot)

        if self.daily.watchlist.update_stock(pdno, name, price, volume):
            for bot in self.daily.bots.values():
                bot.update_sell_list()

        self.swing.check_stock(symbol_item)

    def _update_market_data(self, now: float):
        # 모든 봇의 모니터링 리스트에서 중복을 제거한 관심 종목을 추출
        # 이것들의 현재가를 업데이트한다. 업데이트된 가격은 price_analysis에 저장된다.

        current_time = time.localtime(now)
        # 현재가를 업데이트하는 것은 장이 열려있는 시간에만 의미가 있다.
        # 따라서 장이 열려있는 시간에만 가격 업데이트를 한다. (9:00 ~ 15:30)
        if current_time.tm_hour < 9 or (current_time.tm_hour == 15 and current_time.tm_min > 30) or current_time.tm_hour > 15:
            return

        # KOSDAQ 시장 지수 업데이트 (10초에 한 번 정도 갱신하도록 처리)
        if getattr(self, '_last_market_index_tick_time', 0.0) + 10 <= now:
            self._last_market_index_tick_time = now
            try:
                if getattr(self.market_data_service.auth, 'is_virtual', False):
                    # 모의투자 환경에서는 시장 지수 조회 API를 미지원하므로 필터 기능 생략
                    self.market_index_kosdaq = 0.0
                    self.market_index_kosdaq_drop_rate = 0.0
                else:
                    kosdaq_val, kosdaq_rate = self.market_data_service.get_market_index(is_kosdaq=True)
                    self.market_index_kosdaq = kosdaq_val
                    self.market_index_kosdaq_drop_rate = kosdaq_rate
                    
                    # 시장 폭락 경고 로깅 (10분에 한 번만 남기도록)
                    if TradingParams.USE_MARKET_INDEX_FILTER and kosdaq_rate <= TradingParams.MARKET_INDEX_DROP_LIMIT:
                        if getattr(self, '_last_market_drop_log_time', 0.0) + 600 <= now:
                            self.log(f"🚨 시장 지수 경고: 코스닥 지수 하락률({kosdaq_rate}%)이 제한치({TradingParams.MARKET_INDEX_DROP_LIMIT}%)에 도달하여 신규 매수가 차단됩니다.")
                            self._last_market_drop_log_time = now
            except Exception as e:
                self.log(f"시장 지수 업데이트 중 오류: {e}")

        monitor_dict: dict[str, SymbolItem] = {}
        for bot in self.daily.bots.values():
            for item in bot.monitor_list:
                if item.pdno not in monitor_dict:
                    monitor_dict[item.pdno] = item

        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(self._update_price, symbol_item, now) for symbol_item in monitor_dict.values()]
            concurrent.futures.wait(futures)

    def _update_price(self, symbol_item: SymbolItem, now: float, force: bool = False):
        """단일 종목의 현재가 조회"""
        with self._price_lock:
            cached_item = self.price_analysis.items.get(symbol_item.pdno)
            if not force:
                last_update_at = self.last_price_update_at.get(symbol_item.pdno, 0.0)
                if now - last_update_at < self.price_update_interval_sec:
                    return

        error_count = 0
        candle = None
        while error_count < 5:
            try:
                current_time = time.localtime(now)
                hour = current_time.tm_hour
                minute = current_time.tm_min
                    
                candle = self.market_data_service.get_one_minute_candlestick(symbol_item.pdno, hour, minute)
                # candle 데이터중 첫번째 (가장 최근 데이터)의 현재가와 체결량을 가져온다.)
                if candle is None:
                    raise ValueError("캔들스틱 데이터를 가져오지 못했습니다.")

                break
            except Exception as e:
                error_count += 1
                if error_count >= 5:
                    self.log(f"Error fetching current price for {symbol_item.pdno} after 5 attempts: {e}")
                    return

                time.sleep(1)  # 잠시 대기 후 재시도
                continue

        if candle is None:
            return

        with self._price_lock:
            self.last_price_update_at[symbol_item.pdno] = now

            if self.price_analysis.add_price(symbol_item, candle):
                # 가격이 업데이트된 경우에만 로그에 남기기에는 너무 많으므로 콘솔에 출력함
                print(f"[{symbol_item.pdno}] {symbol_item.prdt_name} / 현재가: {candle.close_price} / 거래량: {candle.volume}")

    def _update_snapshot_collect_candidates(self):
        self.snapshot_collect_candidates: list[SymbolItem] = []
        kosdq_records = load_kosdaq_master()
        kospi_records = load_kospi_master()
        all_valid_records = kospi_records + kosdq_records
        self.valid_pdno_set = {getattr(record, 'mksc_shrn_iscd', '') for record in all_valid_records}

        self.log(f"kospi와 kosdaq 항목을 조사하여 관심 종목 스냅샷 수집 후보 리스트를 업데이트합니다. (count={len(all_valid_records)})")

        for record in all_valid_records:
            pdno = getattr(record, 'mksc_shrn_iscd', '')
            name = getattr(record, 'hts_kor_isnm', '')

            if self.symbol_snapshot_cache.is_exists(pdno):
                # 이미 캐시에 존재하는 심볼은 스냅샷 수집 후보에서 제외한다.
                continue

            stock_item = SymbolItem(pdno, name)
            self.snapshot_collect_candidates.append(stock_item)
    
    def is_valid_pdno(self, pdno: str) -> bool:
        return pdno in self.valid_pdno_set


if __name__ == "__main__":
    bot = TradeBot()
    bot.display_account_info()
    user_app_ids = bot.get_user_app_ids()

    while True:
        now = time.time()
        bot.update_market_and_stock_data(now)

        for app_id in user_app_ids:
            bot.process_once(app_id)
            time.sleep(1)
