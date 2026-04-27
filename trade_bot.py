from api.kis_auth import KisAuth
from api.kis_auth_order import OrderCheckResult
from api.market_data_service import MarketDataService
from api.kis_user import KisUser
from api.kis_user import KisUserManager
from api.special_days import SpecialDays
from KisKey import get_kis_user_manager
from KisKey import data_go_kr_api_key
from api.info_kosdaq import load_kosdaq_master
from api.info_kospi import load_kospi_master
from price_analysis import PriceAnalysis
from interest_stock_manager import InterestStockManager
from dataclasses import dataclass
from typing import Optional
from typing import List
from trade_step import TradeStep
from common_structure import SymbolItem
from symbol_snapshot_cache import SymbolSnapshot, SymbolSnapshotCache
from trade_reporter import TradeReporter, TradeType
from filter import TradingParams

import io
import os
import time
import urllib.request
import zipfile


@dataclass
class TradeState:
    step: TradeStep = TradeStep.JUDGE_STEP
    buy_order_no: str = ""
    sell_order_no: str = ""
    buy_order_requested_at: float = 0.0
    sell_order_requested_at: float = 0.0
    cooldown_until: float = 0.0


class TradeBot:
    def __init__(self):
        import threading
        self._price_lock = threading.Lock()
        # print로 로그를 남기도록 한다. (TradingEngine이 가동되면 log 함수는 엔진의 로그 함수로 대체된다.)
        self.log = print
        self.trade_log = None
        self.symbol_snapshot_cache = SymbolSnapshotCache("./cache/symbol_snapshot_cache.db")
        self.price_analysis = PriceAnalysis("./cache/price_analysis/")
        self.interest_stock_manager = InterestStockManager("./cache/interest_stocks.json")
        self.price_update_interval_sec = 2.5
        self.last_price_update_at: dict[str, float] = {}
        self.valid_pdno_set: set[str] = set()
        self.is_running = None

        self.snapshot_collect_candidates: list[SymbolItem] = []
        self._snapshot_toggle = False

        self.user_manager: KisUserManager = get_kis_user_manager(self.log)
        if len(self.user_manager.users) == 0:
            raise ValueError("사용자 정보가 없습니다. KisKey.py 파일을 확인해주세요.")
        else:
            # 가격 조회 서비스 초기화
            self._market_data_service = MarketDataService(self.user_manager.users[0].auth)

        self.bots: dict[str, TradeSingleBot] = {}
        for user in self.user_manager.users:
            try:
                bot = TradeSingleBot(self, user)
                self.bots[user.app_id] = bot
            except Exception as e:
                self.log(f"사용자 {user.app_id}에 대한 봇 초기화 중 오류가 발생했습니다: {e}")
                continue

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
        for bot in self.bots.values():
            bot.set_logger(log)

    def set_trade_logger(self, log):
        self.trade_log = log
        for bot in self.bots.values():
            bot.set_trade_logger(log)

    def display_account_info(self):
        for bot in self.bots.values():
            bot.display_account_info()

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

        if not hasattr(self, '_last_interest_tick_time'):
            self._last_interest_tick_time = now

        if now - self._last_interest_tick_time >= 600:
            self.interest_stock_manager.tick(600)
            self._last_interest_tick_time = now

        self._update_market_data(now)
        self._update_interest_stock_manager(now)

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
                    for bot in self.bots.values():
                        bot.update_account_stock()
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
                for bot in self.bots.values():
                    bot.update_account_stock()
                    bot.record_account_history()
                self.daily_start_logged = True

        self.is_running = True

        bot = self.bots.get(app_id)
        if bot:
            bot.process_once(now)

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

    def place_manual_buy(self, app_id: str, pdno: str, quantity: int):
        bot = self.bots.get(app_id)
        if bot:
            return bot.place_manual_buy(pdno, quantity)
        
    def place_manual_sell(self, app_id: str, pdno: str, quantity: int):
        bot = self.bots.get(app_id)
        if bot:
            return bot.place_manual_sell(pdno, quantity)

    def get_dashboard_snapshot(self, app_id: str) -> Optional[dict]:
        bot = self.bots.get(app_id)
        if bot:
            return bot.get_dashboard_snapshot()
        return None

    def _update_interest_stock_manager(self, now: float):
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
            price, volume = self._market_data_service.get_previous_day_price_and_volume(pdno)

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

        if self.interest_stock_manager.update_stock(pdno, name, price, volume):
            for bot in self.bots.values():
                bot.update_sell_list()

    def _update_market_data(self, now: float):
        # 모든 봇의 모니터링 리스트에서 중복을 제거한 관심 종목을 추출
        # 이것들의 현재가를 업데이트한다. 업데이트된 가격은 price_analysis에 저장된다.

        current_time = time.localtime(now)
        # 현재가를 업데이트하는 것은 장이 열려있는 시간에만 의미가 있다.
        # 따라서 장이 열려있는 시간에만 가격 업데이트를 한다. (9:00 ~ 15:30)
        if current_time.tm_hour < 9 or (current_time.tm_hour == 15 and current_time.tm_min > 30) or current_time.tm_hour > 15:
            return

        monitor_dict: dict[str, SymbolItem] = {}
        for bot in self.bots.values():
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
                    
                candle = self._market_data_service.get_one_minute_candlestick(symbol_item.pdno, hour, minute)
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

class TradeSingleBot:
    def __init__(self, parent, user: KisUser):
        self.parent = parent
        self.log = parent.log
        self.trade_log = parent.trade_log
        self.auth = user.auth
        self.app_id = user.app_id

        self.loop_count = 0
        self.pdno_states: dict[str, TradeState] = {}
        self.buy_fail_counts: dict[str, int] = {}
        self.monitor_list: list[SymbolItem] = []
        self.trade_reporter = TradeReporter(self)

        self.update_sell_list()

    def set_logger(self, log):
        self.log = log

    def set_trade_logger(self, log):
        self.trade_log = log

    def display_account_info(self):
        self.log(f"예수금: {self.auth.account.balance.dnca_tot_amt}")
        self.log(f"D+1 예수금: {self.auth.account.balance.nxdy_excc_amt}")
        self.log(f"D+2 예수금: {self.auth.account.balance.prvs_rcdl_excc_amt}")
        self.log("주식 잔고:")
        if not self.auth.account.stocks:
            self.log("보유 주식이 없습니다.")
        else:
            for stock in self.auth.account.stocks:
                self.log(f"종목번호: {stock['pdno']} {stock['prdt_name']}, 보유수량: {stock['hldg_qty']}, 매입평균가: {stock['pchs_avg_pric']}")

    def _find_inventory(self, pdno: str):
        return self.auth.account.stocks_by_pdno.get(pdno)

    def _get_trade_state(self, pdno: str) -> TradeState:
        if pdno not in self.pdno_states:
            self.pdno_states[pdno] = TradeState()
        return self.pdno_states[pdno]
    
    def _symbol_log(self, symbol_item: SymbolItem, message: str):
        pdno = symbol_item.pdno
        name = symbol_item.prdt_name
        self.log(f"[{pdno}] {name} {message}")

    def _process_step_judge(self, symbol_item: SymbolItem):
        pdno = symbol_item.pdno
        self.update_sell_list()
        state = self._get_trade_state(pdno)

        # self.auth.account.stocks 내에 현재 심볼이 존재하는지 확인하여 매도 주문 단계로 이동
        if self._find_inventory(pdno) is not None:
            state.step = TradeStep.DECIDE_ON_SELL
            self._symbol_log(symbol_item, "보유 수량이 확인되어 매도 주문 단계로 이동합니다.")
            return
        
        if not self.parent.price_analysis.is_purchase_overtime(pdno):
            # 보유 수량이 없는 경우 매수 주문 단계로 이동
            # 단 3시부터는 매도를 시작하므로 2시 50분부터는 그냥 판단 단계에 머무르도록 한다.
            state.step = TradeStep.DECIDE_ON_PURCHASE
            self._symbol_log(symbol_item, "보유 수량이 없어서 매수 주문 단계로 이동합니다.")
            return

    def _process_step_order_buy(self, symbol_item: SymbolItem):
        pdno = symbol_item.pdno
        state = self._get_trade_state(pdno)
        inventory = self._find_inventory(pdno)
        if inventory is not None:
            # 이상하다 보유 수량이 있는데 매수 주문 단계에 있다.
            # 다시 판단 단계로 이동한다.
            state.step = TradeStep.JUDGE_STEP
            self._symbol_log(symbol_item, "보유 수량이 확인되었으나 매수 주문 단계에 있어 판단 단계로 이동합니다.")
            return

        if self.parent.price_analysis.is_purchase_overtime(pdno):
            self._symbol_log(symbol_item, "현재 시간은 매수 추천이 종료된 시간입니다. 매수 주문 단계에서 판단 단계로 이동합니다.")
            state.step = TradeStep.JUDGE_STEP
            return

        if time.time() < state.cooldown_until:
            return

        if self.parent.price_analysis.is_purchase_recommended(pdno) is False:
            return

        if pdno not in self.parent.price_analysis.items or not self.parent.price_analysis.items[pdno].candle_stick_5minute:
            return

        budget = self.auth.account.balance.dnca_tot_amt

        # 수수료를 감안하여 budget에 여유를 둔다. (약 만원 정도 여유를 둔다고 가정)
        # 어차피 비싼 종목은 사지 않게 되어 있으므로 큰 문제가 되지는 않을 것이다.
        budget = max(0, budget - 10000)

        # 최대 200만원까지 투자하도록 제한한다.
        budget = min(budget, 2000000)

        # 총평가금액 기준으로 한종목에 50% 이상 투자하지 않도록 제한한다.
        balance = self.auth.account.balance
        tot_evlu_amt = int(balance.tot_evlu_amt)
        if tot_evlu_amt < 1000000:
            # 총평가금액이 100만원 미만인 경우에는 최대 투자 금액을 총평가금액의 50%로 제한한다.
            budget = min(budget, tot_evlu_amt // 2)
        else:
            # 총평가금액이 100만원 이상인 경우에는 최대 투자 금액을 총평가금액의 33%로 제한한다.
            budget = min(budget, tot_evlu_amt // 3)

        current_price = int(self.parent.price_analysis.items[pdno].candle_stick_5minute[-1].close_price)
        quantity = int(budget // current_price)
        if quantity <= 0:
            return

        fail_count = self.buy_fail_counts.get(pdno, 0)
        order_quantity = quantity
        if fail_count >= 10 and order_quantity > 1:
            order_quantity -= 1
            self._symbol_log(symbol_item,
                f"매수 연속 실패 {fail_count}회로 수량을 1 감소하여 재시도합니다. "
                f"({quantity} -> {order_quantity})"
            )

        order = self.buy(symbol_item, order_quantity, current_price)
        if order is None:
            self.buy_fail_counts[pdno] = fail_count + 1
            self._symbol_log(symbol_item,
                f"매수 주문이 실패했습니다: 수량: {order_quantity} / 가격: {current_price} "

                f"/ 연속 실패: {self.buy_fail_counts[pdno]}"
            )

            if self.buy_fail_counts[pdno] >= 20:
                self._symbol_log(symbol_item, f"매수 연속 실패가 20회에 도달하여 Fail 관련 카운트를 초기화합니다.")
                self.buy_fail_counts[pdno] = 0  # 실패 카운트 초기화

            return

        self.buy_fail_counts[pdno] = 0

        order_no = order.get("ODNO", "")
        self.trade_reporter.add(TradeType.BUY, symbol_item, order_quantity, current_price)
        state.buy_order_no = order_no
        state.buy_order_requested_at = time.time()
        state.step = TradeStep.WAIT_ACCEPT_PURCHASE

    def _process_step_buy_check(self, symbol_item: SymbolItem):
        pdno = symbol_item.pdno
        state = self._get_trade_state(pdno)
        if not state.buy_order_no:
            state.buy_order_requested_at = 0.0
            state.step = TradeStep.DECIDE_ON_PURCHASE
            self.trade_reporter.add(TradeType.UNKNOWN_ERROR, symbol_item, 0, 0, "매수 체크하려 했으나 주문 번호가 없습니다. 매수 주문 단계로 이동합니다.")
            return

        check_order_result = self.check_order_completed(symbol_item, state.buy_order_no, True)

        if check_order_result is not None and check_order_result.rmn_qty == 0:
            # 잔여수량이 0이면 모두 체결된 것이므로 매도 주문 단계로 이동한다.
            self.update_account_stock()
            state.buy_order_no = ""
            state.buy_order_requested_at = 0.0
            self.trade_reporter.add(TradeType.BUY_COMPLETED, symbol_item, check_order_result.tot_ccld_qty, check_order_result.ord_unpr)  # 매수 체결 로그 추가
            state.step = TradeStep.DECIDE_ON_SELL
        elif (
            state.buy_order_requested_at > 0
            and (time.time() - state.buy_order_requested_at) > TradingParams.BUY_ORDER_TIMEOUT_SECONDS
        ):
            try:
                # 취소 전에 order_check API로 실제 체결 수량을 조회한다.
                check_result = self.check_order_completed(symbol_item, state.buy_order_no, True)
                self.auth.order.cancel_order(state.buy_order_no)
                self.update_account_stock()
                filled_quantity = check_result.tot_ccld_qty if check_result else 0

                self.trade_reporter.add(TradeType.BUY_CANCELLED, symbol_item, filled_quantity, 0, f"체결 대기 시간 {TradingParams.BUY_ORDER_TIMEOUT_SECONDS // 60}분 초과")  # 매수 주문 취소 로그 추가
                state.cooldown_until = time.time() + TradingParams.COOLDOWN_AFTER_CANCEL  # 취소 후 쿨다운 적용
                state.buy_order_no = ""
                state.buy_order_requested_at = 0.0
                state.step = TradeStep.JUDGE_STEP
            except Exception as e:
                self._symbol_log(symbol_item, f"매수 주문 체결 대기가 {TradingParams.BUY_ORDER_TIMEOUT_SECONDS // 60}분을 초과했으나 주문 취소에 실패했습니다: {e}")
            return

    def _process_order_sell(self, symbol_item: SymbolItem):
        pdno = symbol_item.pdno
        state = self._get_trade_state(pdno)
        inventory = self._find_inventory(pdno)
        if inventory is None:
            state.step = TradeStep.DECIDE_ON_PURCHASE
            state.sell_order_no = ""
            state.sell_order_requested_at = 0.0
            self._symbol_log(symbol_item, "매도를 준비하려 했으나 보유 수량이 없습니다. 매수 주문 단계로 이동합니다.")
            return

        purchase_price = float(inventory['pchs_avg_pric'])
        quantity = int(inventory['hldg_qty'])

        if self.parent.price_analysis.is_sell_stop_loss_recommended(pdno, purchase_price):
            current_price = int(self.parent.price_analysis.items[pdno].candle_stick_5minute[-1].close_price) if pdno in self.parent.price_analysis.items and self.parent.price_analysis.items[pdno].candle_stick_5minute else 0
            order = self.immediately_sell(symbol_item, quantity)
            if order is None:
                self._symbol_log(symbol_item, f"손절 추천이지만 즉시 매도 주문에 실패했습니다. 다음 루프에서 다시 시도합니다.")
                return

            state.sell_order_no = order.get("ODNO", "") if isinstance(order, dict) else ""
            state.sell_order_requested_at = time.time() if state.sell_order_no else 0.0
            self._symbol_log(symbol_item, f"손절 추천: 구매가: {purchase_price} / 현재가: {current_price}")
            self.trade_reporter.add(TradeType.IMMEDIATE_SELL, symbol_item, quantity, current_price)  # 즉시 매도 주문 로그 추가
            state.step = TradeStep.WAIT_ACCEPT_SELL
            return

        if not self.parent.price_analysis.is_sell_recommended(pdno, purchase_price):
            return

        if pdno not in self.parent.price_analysis.items or not self.parent.price_analysis.items[pdno].candle_stick_5minute:
            return

        current_price = int(self.parent.price_analysis.items[pdno].candle_stick_5minute[-1].close_price)
        order = self.sell(symbol_item, quantity, current_price)
        if order is None:
            return

        self.trade_reporter.add(TradeType.SELL, symbol_item, quantity, current_price)
        state.sell_order_no = order.get("ODNO", "") if isinstance(order, dict) else ""
        state.sell_order_requested_at = time.time() if state.sell_order_no else 0.0
        state.step = TradeStep.WAIT_ACCEPT_SELL

    def _process_step_sell_check(self, symbol_item: SymbolItem):
        pdno = symbol_item.pdno
        state = self._get_trade_state(pdno)
        if not state.sell_order_no:
            state.sell_order_requested_at = 0.0
            state.step = TradeStep.DECIDE_ON_SELL
            self.trade_reporter.add(TradeType.UNKNOWN_ERROR, symbol_item, 0, 0, "매도 체크하려 했으나 주문 번호가 없습니다. 매도 주문 단계로 이동합니다.")
            return

        check_order_result = self.check_order_completed(symbol_item, state.sell_order_no, False)

        if check_order_result is not None and check_order_result.rmn_qty == 0:
            pdno = symbol_item.pdno
            inventory = self._find_inventory(pdno)
            purchase_price = float(inventory['pchs_avg_pric']) if inventory else 0.0

            # 잔여수량이 0이면 모두 체결된 것이므로 매수 주문 단계로 이동한다.
            self.update_account_stock()

            state.sell_order_no = ""
            state.sell_order_requested_at = 0.0
            self.trade_reporter.add(TradeType.SELL_COMPLETED, symbol_item, check_order_result.tot_ccld_qty, check_order_result.ord_unpr)  # 매도 체결 로그 추가
            
            if purchase_price > 0:
                is_profit = float(check_order_result.ord_unpr) > purchase_price
                self.parent.interest_stock_manager.apply_trade_result(pdno, is_profit)

            # 매도 후 해당 종목의 재진입을 금지하여 잦은 휩쏘로 인한 뇌동매매를 강도높게 방지한다.
            state.cooldown_until = time.time() + TradingParams.COOLDOWN_AFTER_SELL
            state.step = TradeStep.DECIDE_ON_PURCHASE
        elif (
            state.sell_order_requested_at > 0
            and (time.time() - state.sell_order_requested_at) > TradingParams.SELL_ORDER_TIMEOUT_SECONDS
        ):
            try:
                # 취소 전에 order_check API로 실제 체결 수량을 조회한다.
                check_result = self.check_order_completed(symbol_item, state.sell_order_no, False)
                self.auth.order.cancel_order(state.sell_order_no)
                self.update_account_stock()
                filled_quantity = check_result.tot_ccld_qty if check_result else 0

                self.trade_reporter.add(TradeType.SELL_CANCELLED, symbol_item, filled_quantity, 0, f"체결 대기 시간 {TradingParams.SELL_ORDER_TIMEOUT_SECONDS // 60}분 초과")  # 매도 주문 취소 로그 추가
                state.sell_order_no = ""
                state.sell_order_requested_at = 0.0
                state.step = TradeStep.JUDGE_STEP
            except Exception as e:
                self._symbol_log(symbol_item, f"매도 주문 체결 대기가 {TradingParams.SELL_ORDER_TIMEOUT_SECONDS // 60}분을 초과했으나 주문 취소에 실패했습니다: {e}")
            return            

    def process_once(self, now):
        self._process_step(now)

    def record_account_history(self):
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
                    balance = self.auth.account.balance
                    tot_evlu_amt = int(balance.tot_evlu_amt)
                    dnca_tot_amt = int(balance.dnca_tot_amt)
                    nxdy_excc_amt = int(balance.nxdy_excc_amt)
                    prvs_rcdl_excc_amt = int(balance.prvs_rcdl_excc_amt)

                    # 이전 기록 조회
                    cursor.execute(
                        "SELECT tot_evlu_amt, dnca_tot_amt, nxdy_excc_amt, prvs_rcdl_excc_amt "
                        "FROM `pulsetrade.accounthistory` "
                        "WHERE app_id = %s ORDER BY time DESC LIMIT 1",
                        (self.app_id,)
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
                        self.app_id,
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

    def _process_step(self, now: float):
        # 종목별 상태머신 동작
        processed_pdnos = set()
        for symbol_item in self.monitor_list:
            pdno = symbol_item.pdno
            if not pdno:
                continue
            if pdno in processed_pdnos:
                continue
            processed_pdnos.add(pdno)

            state = self._get_trade_state(pdno)
            step = state.step

            if step == TradeStep.JUDGE_STEP:
                # step0: 스탭판단
                self._process_step_judge(symbol_item)
            elif step == TradeStep.DECIDE_ON_PURCHASE:
                # step1: 매수 가능 확인 (매수 주문 후 step2)
                self._process_step_order_buy(symbol_item)
            elif step == TradeStep.WAIT_ACCEPT_PURCHASE:
                # step2: 체결 확인 자리(현재는 step3으로 패스)
                self._process_step_buy_check(symbol_item)
            elif step == TradeStep.DECIDE_ON_SELL:
                # step3: 매도 가능 확인 (매도 주문 후 step4)
                self._process_order_sell(symbol_item)
            elif step == TradeStep.WAIT_ACCEPT_SELL:
                # step4: 체결 확인 자리(현재는 step1으로 패스)
                self._process_step_sell_check(symbol_item)
            else:
                state.step = TradeStep.DECIDE_ON_PURCHASE

        self.loop_count += 1

    def get_dashboard_snapshot(self):
        pdno_to_name = {}
        watch_pdnos = []
        watch_pdno_set = set()
        for item in self.monitor_list:
            pdno = item.pdno
            if not pdno:
                continue
            pdno_to_name[pdno] = item.prdt_name
            if pdno not in watch_pdno_set:
                watch_pdnos.append(pdno)
                watch_pdno_set.add(pdno)

        watch_rows = []
        for pdno in watch_pdnos:
            item = self.parent.price_analysis.items.get(pdno)
            current_price = None
            candle_count = 0
            volume = 0
            if item is not None and item.candle_stick_5minute:
                candle_count = len(item.candle_stick_5minute)
                current_price = item.candle_stick_5minute[-1].close_price
                volume = item.candle_stick_5minute[-1].volume

            watch_rows.append({
                "pdno": pdno,
                "name": pdno_to_name.get(pdno, pdno),
                "price": current_price,
                "candles": candle_count,
                "volume": volume,
                "step": self._get_trade_state(pdno).step.GetAbbreviation(),
            })

        holdings_rows = []
        for stock in self.auth.account.stocks:
            pdno = stock.get('pdno', '')
            quantity = int(stock.get('hldg_qty', 0))
            purchase_price = float(stock.get('pchs_avg_pric', 0))
            current_price = None
            if pdno in self.parent.price_analysis.items and self.parent.price_analysis.items[pdno].candle_stick_5minute:
                current_price = self.parent.price_analysis.items[pdno].candle_stick_5minute[-1].close_price

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

        return {
            "market_open": self.parent.is_market_open(),
            "loop_count": self.loop_count,
            "account": {
                "tot_evlu_amt": self.auth.account.balance.tot_evlu_amt,
                "cash": self.auth.account.balance.dnca_tot_amt,
                "d1": self.auth.account.balance.nxdy_excc_amt,
                "d2": self.auth.account.balance.prvs_rcdl_excc_amt,
            },
            "watch": watch_rows,
            "holdings": holdings_rows,
            "timestamp": time.time(),
        }

    def place_manual_buy(self, pdno: str, quantity: int):
        if quantity <= 0:
            raise ValueError("수량은 1 이상이어야 합니다.")
        if not self.parent.is_market_open():
            raise ValueError("장외 시간에는 주문할 수 없습니다.")

        if not pdno in self.parent.price_analysis.items or not self.parent.price_analysis.items[pdno].candle_stick_5minute:
            raise ValueError("현재가를 가져오지 못해 주문할 수 없습니다.")
        
        symbol_item = self.parent.price_analysis.items[pdno].symbol_item
        price = self.parent.price_analysis.items[pdno].candle_stick_5minute[-1].close_price

        result = self.buy(symbol_item, quantity, price)
        self.update_account_stock()
        return result

    def place_manual_sell(self, pdno: str, quantity: int):
        if quantity <= 0:
            raise ValueError("수량은 1 이상이어야 합니다.")
        if not self.parent.is_market_open():
            raise ValueError("장외 시간에는 주문할 수 없습니다.")
        
        if not pdno in self.parent.price_analysis.items or not self.parent.price_analysis.items[pdno].candle_stick_5minute:
            raise ValueError("현재가를 가져오지 못해 주문할 수 없습니다.")

        symbol_item = self.parent.price_analysis.items[pdno].symbol_item
        price = self.parent.price_analysis.items[pdno].candle_stick_5minute[-1].close_price

        inventory = self.auth.account.stocks_by_pdno.get(pdno)
        if inventory is None:
            raise ValueError("보유하지 않은 종목입니다.")

        holding_qty = int(inventory.get('hldg_qty', 0))
        if quantity > holding_qty:
            raise ValueError(f"보유 수량({holding_qty})을 초과하여 매도할 수 없습니다.")

        result = self.sell(symbol_item, quantity, price)
        if result is None:
            raise ValueError("매도 주문이 실패했습니다.")

        self.update_account_stock()
        return result

    def update_sell_list(self):
        self.update_account_stock()

        self.monitor_list: list[SymbolItem] = []
        monitor_pdnos = set()

        # 먼저 관심종목들을 모니터링 리스트에 추가
        for stock in self.parent.interest_stock_manager.get_stocks():
            self.monitor_list.append(stock)
            monitor_pdnos.add(stock.pdno)

        # 재고로 가지고 있는 건 모두 모니터링 리스트에 추가
        for stock in self.auth.account.stocks:
            pdno = stock.get('pdno', '')
            prdt_name = stock.get('prdt_name', '')
            if pdno not in monitor_pdnos:
                self.monitor_list.append(SymbolItem(pdno, prdt_name))
                monitor_pdnos.add(pdno)

    def update_account_stock(self):
        try_count = 0
        while True:
            try:
                self.auth.account.update_stock()
                break
            except Exception as e:
                if try_count >= 5:
                    self.log(f"계좌 Stock 정보 업데이트 실패: {e}")
                    self.auth.delete_token() # 토큰이 문제가 있을 수 있으니 삭제해서 다음 주문 시 재발급 받도록 한다.
                time.sleep(1)  # 잠시 대기 후 재시도
                try_count += 1
        try_count = 0
        while True:
            try:
                self.auth.account.update()
                break
            except Exception as e:
                if try_count >= 5:
                    self.log(f"계좌 정보 업데이트 실패: {e}")
                    self.auth.delete_token() # 토큰이 문제가 있을 수 있으니 삭제해서 다음 주문 시 재발급 받도록 한다.   
                time.sleep(1)  # 잠시 대기 후 재시도
                try_count += 1
        
        self.trade_reporter.set_account_balance(self.auth.account.balance)

    def buy(self, symbol_item: SymbolItem, quantity: int, price: int):
        """현금 매수 주문"""
        try:
            return self.auth.order.buy_order_cash(symbol_item.pdno, quantity, price)
        except Exception as e:
            self._symbol_log(symbol_item, f"매수 주문 실패\n{e}")
            return None

    def check_order_completed(self, symbol_item: SymbolItem, order_no: str, is_buy: bool) -> Optional[OrderCheckResult]:
        """매도/매수 주문 체결 여부 확인. 5회 실패 시 None 반환."""
        pd_no = symbol_item.pdno

        for try_count in range(10):
            try:
                check_list: List[OrderCheckResult] = self.auth.order.order_check(pd_no, order_no, is_buy)

                total_check_result = OrderCheckResult()

                for check in check_list:
                    total_check_result.add(check)

                return total_check_result
            except Exception as e:
                time.sleep(1)

        self._symbol_log(symbol_item, "주문 체결 확인 10회 실패, 다음 루프에서 재시도합니다.")
        return None

    def sell(self, symbol_item: SymbolItem, quantity: int, price: int):
        """현금 매도 주문"""
        for try_count in range(20):
            try:
                return self.auth.order.sell_order_cash(symbol_item.pdno, quantity, price)
            except Exception as e:
                last_error = e
                time.sleep(1)  # 잠시 대기 후 재시도
                continue

        self._symbol_log(symbol_item, f"매도 주문 실패\n{last_error}")
        self.auth.delete_token() # 토큰이 문제가 있을 수 있으니 삭제해서 다음 주문 시 재발급 받도록 한다.
        return None

    def immediately_sell(self, symbol_item: SymbolItem, quantity: int):
        """즉시 매도 주문 (시장가)"""
        for try_count in range(20):
            try:
                return self.auth.order.immediately_sell(symbol_item.pdno, quantity)
            except Exception as e:
                last_error = e
                time.sleep(1)  # 잠시 대기 후 재시도
                continue

        self._symbol_log(symbol_item, f"즉시 매도 주문 실패\n{last_error}")
        self.auth.delete_token() # 토큰이 문제가 있을 수 있으니 삭제해서 다음 주문 시 재발급 받도록 한다.
        return None

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

