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
from trade_bot_daily_group import TradeBotDailyGroup
from trade_bot_swing_group import TradeBotSwingGroup
from watchlist_ai_comments import WatchlistAIComments
from daily_investment_advice import DailyInvestmentAdvice

import io
import os
import time
import urllib.request
import zipfile


class TradeBotManager:
    def __init__(self):
        import threading
        self._price_lock = threading.Lock()
        # print로 로그를 남기도록 한다. (TradingEngine이 가동되면 log 함수는 엔진의 로그 함수로 대체된다.)
        self.loop_count = 0
        self.log = print
        self.trade_log = None
        self.watchlist_ai_comments = WatchlistAIComments("./cache/watchlist_ai_comments.json")
        self.daily_investment_advice = DailyInvestmentAdvice("./cache/daily_investment_advice.json")
        self.symbol_snapshot_cache = SymbolSnapshotCache("./cache/symbol_snapshot_cache.db")
        self.price_analysis = PriceAnalysis("./cache/price_analysis/")
        self.price_update_interval_sec = 2.5
        self.last_price_update_at: dict[str, float] = {}
        self.valid_pdno_set: set[str] = set()
        self.market_data_update_elapsed :float = 0.0 # 마지막 시장 데이터 업데이트에 걸린 시간 (초 단위)
        self.process_once_elapsed :float = 0.0 # 마지막 process_once 함수 실행에 걸린 시간 (초 단위)
        self.is_running = None

        self.snapshot_collect_candidates: list[SymbolItem] = []
        self._snapshot_toggle = False
        
        # 시장 지수 정보
        self.market_index_kosdaq: float = 0.0
        self.market_index_kosdaq_drop_rate: float = 0.0

        # KisKey.json 파일에서 사용자 정보를 읽어와서 user_manager에 추가한다.
        self.user_manager = KisUserManager()
        self.user_manager.load("./KisKey.json", self.log)

        if len(self.user_manager.users) == 0:
            raise ValueError("사용자 정보가 없습니다. KisKey.json 파일을 확인해주세요.")
        else:
            # 가격 조회 서비스 초기화
            self.market_data_service = MarketDataService(self.user_manager.users[0].auth)

        self.daily = TradeBotDailyGroup(self)
        self.swing = TradeBotSwingGroup(self)

        for user in self.user_manager.users:
            try:
                if user.use_daily_bot:
                    self.daily.add_bot(user)

                if user.use_swing_bot:
                    self.swing.add_bot(user)
            except Exception as e:
                self.log(f"사용자 {user.app_id}에 대한 봇 초기화 중 오류가 발생했습니다: {e}")
                continue

        # app_id 별로 봇이 몇 번 프로세스에 진입했는지 카운트하는 딕셔너리
        self.process_counters: dict[str, int] = {}

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
        self.start_logged = False
        self.end_logged = False
        self.is_running = None

        elapsed = time.time() - now

        if self._is_now_holiday:
            self.log(f"오늘은 {date_str}로 휴일입니다. 봇이 동작하지 않습니다.")
        
        print(f"[{elapsed:10.2f}초] 날짜 초기화 작업이 완료됨.")
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
        
        start_time = time.time()

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
                if not self.end_logged and local_time.tm_hour >= 15 and local_time.tm_min >= 30:
                    # 모든 봇의 계좌 정보를 업데이트하고 기록한다.
                    self.update_portfolio(record_history=True)
                    self.end_logged = True

                if local_time.tm_wday >= 5:
                    self.log("장이 쉬는 날입니다. 토요일과 일요일에는 동작하지 않습니다.")
                else:
                    self.log("장외 시간입니다. 9:00 ~ 15:30 사이에만 동작합니다.")

            self.is_running = False
            return

        if self.is_running is not True:
            # 장이 닫혀 있다가 열린 경우 (장 시작)
            if not self.start_logged:
                # 장 시작 시점에 모든 봇의 계좌 정보를 업데이트하고 기록한다.
                self.update_portfolio(record_history=True)
                self.start_logged = True

        self.is_running = True

        if app_id not in self.process_counters:
            self.process_counters[app_id] = 0
        self.process_counters[app_id] = (self.process_counters[app_id] + 1) % 20

        if self.process_counters[app_id] == 0:
            # 수동 매수/매도가 있었을 수 있으므로
            # 20회에 한 번씩 계좌 업데이트를 하자
            self.update_portfolio(record_history=False, user=self.user_manager.find_user(app_id))

        self.daily.process_once(app_id, now)
        self.swing.process_once(app_id, now)
        self.process_once_elapsed = time.time() - start_time
        self.loop_count += 1

    def update_portfolio(self, record_history: bool, user: Optional[KisUser] = None):
        users_to_update = [user] if user is not None else self.user_manager.users
        for u in users_to_update:
            u.auth.update_stocks(logger=self.log)
            u.auth.update_balance(logger=self.log)
            if record_history:
                self.record_account_history(u)

            # self.daily.bots중 user의 봇이 있다면 그 봇의 포트폴리오 정보도 업데이트한다.
            bot = self.daily.bots.get(u.app_id)
            if bot:
                bot.updated_portfolio()

    def record_account_history(self, user: KisUser):
        try:
            from KisKey import mysql_host
            from KisKey import mysql_port
            from KisKey import mysql_user
            from KisKey import mysql_password
            from KisKey import mysql_database
            import pymysql

            connection = pymysql.connect(
                host=mysql_host,
                port=mysql_port,
                user=mysql_user,
                password=mysql_password,
                database=mysql_database,
                cursorclass=pymysql.cursors.DictCursor
            )
            try:
                with connection.cursor() as cursor:
                    balance = user.auth.portfolio.balance
                    tot_evlu_amt = int(balance.tot_evlu_amt)
                    dnca_tot_amt = int(balance.dnca_tot_amt)
                    nxdy_excc_amt = int(balance.nxdy_excc_amt)
                    prvs_rcdl_excc_amt = int(balance.prvs_rcdl_excc_amt)

                    # 이전 기록 조회
                    cursor.execute(
                        "SELECT tot_evlu_amt, dnca_tot_amt, nxdy_excc_amt, prvs_rcdl_excc_amt "
                        "FROM `pulsetrade.accounthistory` "
                        "WHERE app_id = %s ORDER BY time DESC LIMIT 1",
                        (user.app_id,)
                    )
                    last_record = cursor.fetchone()

                    # 마지막 기록과 비교
                    if last_record:
                        if (int(last_record['tot_evlu_amt']) == tot_evlu_amt and
                            int(last_record['dnca_tot_amt']) == dnca_tot_amt and
                            int(last_record['nxdy_excc_amt']) == nxdy_excc_amt and
                            int(last_record['prvs_rcdl_excc_amt']) == prvs_rcdl_excc_amt):
                            return  # 변경된 값이 없으면 저장하지 않음

                    sql = """
                        INSERT INTO `pulsetrade.accounthistory` 
                        (app_id, tot_evlu_amt, dnca_tot_amt, nxdy_excc_amt, prvs_rcdl_excc_amt, time)
                        VALUES (%s, %s, %s, %s, %s, NOW())
                    """
                    cursor.execute(sql, (
                        user.app_id,
                        tot_evlu_amt,
                        dnca_tot_amt,
                        nxdy_excc_amt,
                        prvs_rcdl_excc_amt
                    ))
                connection.commit()
            finally:
                connection.close()
        except Exception as e:
            self.log(f"계좌 기록 DB 저장 실패: {e}")

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
        snapshot = {}

        # 보유 종목 정보 추가
        user = self.user_manager.find_user(app_id)
        if user is not None:
            holdings_rows = []
            for stock in user.auth.portfolio.stocks:
                pdno = stock.get('pdno', '')
                quantity = int(stock.get('hldg_qty', 0))
                purchase_price = float(stock.get('pchs_avg_pric', 0))
                current_price = None
                if pdno in self.price_analysis.items and self.price_analysis.items[pdno].candle_stick_5minute:
                    current_price = self.price_analysis.items[pdno].candle_stick_5minute[-1].close_price

                profit_rate = None
                if current_price is not None and purchase_price > 0:
                    profit_rate = ((current_price - purchase_price) / purchase_price) * 100

                holdings_rows.append({
                    "pdno": pdno,
                    "name": stock.get('prdt_name', pdno),
                    "qty": quantity,
                    "purchase": purchase_price,
                    "current": current_price,
                    "profit_rate": profit_rate,
                })
            snapshot["holdings"] = holdings_rows
            snapshot["account"] = {
                "tot_evlu_amt": user.auth.portfolio.balance.tot_evlu_amt,
                "cash": user.auth.portfolio.balance.dnca_tot_amt,
                "d1": user.auth.portfolio.balance.nxdy_excc_amt,
                "d2": user.auth.portfolio.balance.prvs_rcdl_excc_amt,
            }

            today_advice = self.daily_investment_advice.get_advice(user.app_id, user.auth.portfolio)
            if today_advice is not None:
                snapshot["today_investment_advice"] = today_advice

        snapshot["market_open"] = self.is_market_open()
        snapshot["update_elapsed"] = self.market_data_update_elapsed
        snapshot["process_once_elapsed"] = self.process_once_elapsed
        snapshot["timestamp"] = time.time()
        snapshot["loop_count"] = self.loop_count
        
        daily_snap = self.daily.get_dashboard_snapshot(app_id)
        if daily_snap:
            if "watch" in daily_snap:
                snapshot["watch"] = daily_snap["watch"]

        swing_snap = self.swing.get_dashboard_snapshot(app_id)
        if swing_snap:
            if "swing_watch" in swing_snap:
                snapshot["swing_watch"] = swing_snap["swing_watch"]

        # AI 코멘트 정보 추가
        for key in ["watch", "swing_watch", "holdings"]:
            if not key in snapshot:
                continue

            for row in snapshot[key]:
                prdt_name = row.get("name")
                if prdt_name is None:
                    continue

                purchase_price = None
                quantity = None
                for user in self.user_manager.users:
                    if user.app_id == app_id:
                        for stock in user.auth.portfolio.stocks:
                            if stock['prdt_name'] == prdt_name:
                                # 보유하고 있는 종목이면 매입가와 수량 정보를 가져온다
                                purchase_price = stock['pchs_avg_pric']
                                quantity = stock['hldg_qty']
                                break

                comment = self.watchlist_ai_comments.get_ai_comment(prdt_name, app_id, purchase_price, quantity)
                if comment:
                    row["ai_comment"] = comment

        return snapshot

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
        start_time = time.time()
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
        for bot in self.swing.bots.values():
            for item in bot.monitor_list:
                if item.pdno not in monitor_dict:
                    monitor_dict[item.pdno] = item

        # 재고로 가지고 있는 건 모두 모니터링 리스트에 추가
        for user in self.user_manager.users:
            for stock in user.auth.portfolio.stocks:
                pdno = stock.get('pdno', '')
                prdt_name = stock.get('prdt_name', '')
                if pdno not in monitor_dict:
                    monitor_dict[pdno] = SymbolItem(pdno, prdt_name)

        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(self._update_price, symbol_item, now) for symbol_item in monitor_dict.values()]
            concurrent.futures.wait(futures)
            
        self.market_data_update_elapsed = time.time() - start_time

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
    bot = TradeBotManager()
    bot.display_account_info()
    user_app_ids = bot.get_user_app_ids()

    while True:
        now = time.time()
        bot.update_market_and_stock_data(now)

        for app_id in user_app_ids:
            bot.process_once(app_id)
            time.sleep(1)
