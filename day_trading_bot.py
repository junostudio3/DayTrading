from KisAuth import KisAuth
from KisAuthOrder import OrderCheckResult
from KisKey import app_account
from KisKey import app_domain
from KisKey import app_is_virtual
from KisKey import app_key
from KisKey import app_secret
from info_kosdaq import find_kosdaq_by_name, load_kosdaq_master
from info_kospi import find_kospi_by_name, load_kospi_master
from price_analysis import PriceAnalysis
from interest_stock_manager import InterestStockManager
import time
from dataclasses import dataclass
from typing import Optional
from typing import List
from trade_step import TradeStep
from common_structure import SymbolItem
from symbol_snapshot_cache import SymbolSnapshot, SymbolSnapshotCache
from trade_reporter import TradeReporter, TradeType


@dataclass
class TradeState:
    step: TradeStep = TradeStep.JUDGE_STEP
    buy_order_no: str = ""
    sell_order_no: str = ""
    buy_order_requested_at: float = 0.0
    sell_order_requested_at: float = 0.0


class DayTradingBot:
    BUY_ORDER_TIMEOUT_SECONDS = 60
    SELL_ORDER_TIMEOUT_SECONDS = 60

    def __init__(self):
        # print로 로그를 남기도록 한다. (TradingEngine이 가동되면 log 함수는 엔진의 로그 함수로 대체된다.)
        self.log = print

        self.auth = KisAuth(app_key, app_secret, app_account, app_is_virtual, app_domain)
        self.auth.account.update()

        self.symbol_snapshot_cache = SymbolSnapshotCache("./cache/symbol_snapshot_cache.db")
        self.price_analysis = PriceAnalysis("./cache/price_analysis_cache.json")
        self.interest_stock_manager = InterestStockManager("./cache/interest_stocks.json")

        if self.interest_stock_manager.keep_7days is False:
            # interest_stock_manager에 symbol_snapshot_cache를 주입한다.(임시)
            for snap_shot in self.symbol_snapshot_cache.get_all_snapshots():
                self.interest_stock_manager.update_stock(snap_shot.symbol.pdno, snap_shot.symbol.prdt_name, snap_shot.price, snap_shot.volume)

        self.loop_count = 0
        self.is_running = True
        self.pdno_states: dict[str, TradeState] = {}
        self.buy_fail_counts: dict[str, int] = {}
        self.sell_cooldown: dict[str, float] = {}
        self.monitor_list: list[SymbolItem] = []
        self.price_update_interval_sec = 2.5
        self.last_price_update_at: dict[str, float] = {}
        self.snapshot_collect_candidates: list[SymbolItem] = []
        self.trade_reporter = TradeReporter(self)

        self._update_snapshot_collect_candidates()
        self.update_sell_list()

    def run(self):
        self.display_account_info()
        while True:
            self.process_once()
            time.sleep(1)

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

    def update_price(self, symbol_item: SymbolItem, now: Optional[float] = None, force: bool = False) -> Optional[float]:
        """단일 종목의 현재가 조회"""
        if now is None:
            now = time.time()

        cached_item = self.price_analysis.items.get(symbol_item.pdno)
        if not force:
            last_update_at = self.last_price_update_at.get(symbol_item.pdno, 0.0)
            if now - last_update_at < self.price_update_interval_sec:
                if cached_item is not None and cached_item.candle_stick_5minute:
                    return cached_item.candle_stick_5minute[-1].close_price

        error_count = 0
        while error_count < 5:
            try:
                current_time = time.localtime(now)
                hour = current_time.tm_hour
                minute = current_time.tm_min
                candle = self.auth.price.get_one_minute_candlestick(symbol_item.pdno, hour, minute)
                # candle 데이터중 첫번째 (가장 최근 데이터)의 현재가와 체결량을 가져온다.)
                if candle is None:
                    raise ValueError("캔들스틱 데이터를 가져오지 못했습니다.")

                break
            except Exception as e:
                error_count += 1
                if error_count >= 5:
                    self.log(f"Error fetching current price for {symbol_item.pdno} after 5 attempts: {e}")
                    return None

                time.sleep(1)  # 잠시 대기 후 재시도
                continue

        self.last_price_update_at[symbol_item.pdno] = now

        if self.price_analysis.add_price(symbol_item, candle):
            # 가격이 업데이트된 경우에만 로그에 남기기에는 너무 많으므로 콘솔에 출력함
            print(f"[{symbol_item.pdno}] {symbol_item.prdt_name} / 현재가: {candle.close_price} / 거래량: {candle.volume}")

    def _update_snapshot_collect_candidates(self):
        self.snapshot_collect_candidates: list[SymbolItem] = []
        kosdq_records = load_kosdaq_master()
        kospi_records = load_kospi_master()
        all_records = kospi_records + kosdq_records

        self.log(f"kospi와 kosdaq 항목을 조사하여 관심 종목 스냅샷 수집 후보 리스트를 업데이트합니다. (count={len(all_records)})")

        for record in all_records:
            pdno = getattr(record, 'mksc_shrn_iscd', '')
            name = getattr(record, 'hts_kor_isnm', '')

            if self.symbol_snapshot_cache.is_exists(pdno):
                # 이미 캐시에 존재하는 심볼은 스냅샷 수집 후보에서 제외한다.
                continue

            stock_item = SymbolItem(pdno, name)
            self.snapshot_collect_candidates.append(stock_item)

    def _find_inventory(self, pdno: str):
        return self.auth.account.stocks_by_pdno.get(pdno)

    def _get_trade_state(self, pdno: str) -> TradeState:
        if pdno not in self.pdno_states:
            self.pdno_states[pdno] = TradeState()
        return self.pdno_states[pdno]
    
    def _collect_interest_stocks(self, now: float):
        # 8시부터 4시 30분 사이에만 관심 종목을 탐색한다.
        # 미리 준비하는 목적이어서 장 시작 조금 전부터 탐색을 시작한다.
        current_time = time.localtime(now)
        if current_time.tm_hour < 8 or (current_time.tm_hour == 16 and current_time.tm_min > 30) or current_time.tm_hour > 16:
            return

        if len(self.snapshot_collect_candidates) == 0:
            # 한번씩은 모든 종목을 탐색했다.
            # 모든 데이터가 symbol_snapshot_cache에 저장되어 있을 것이다
            # 이제부터는 이것을 유지하고 가장 오래된 데이터부터만 하나씩 탐색한다.
            self.interest_stock_manager.enable_keep_7days()
            symbol_item = self.symbol_snapshot_cache.get_oldest_snapshot_symbol()
        else:
            symbol_item = self.snapshot_collect_candidates.pop(0)

        if symbol_item is None:
            return

        pdno = symbol_item.pdno
        name = symbol_item.prdt_name
        
        if not pdno:
            return
        
        changed_list = False

        try:
            # 관심 종목의 전일 종가와 거래량을 조회하여 관심 종목 리스트를 업데이트한다.
            price, volume = self.auth.price.get_previous_day_price_and_volume(pdno)
            
            if price is not None and volume is not None:
                price = int(price)
                volume = int(volume)

                changed_list |= self.interest_stock_manager.update_stock(pdno, name, price, volume)

        except Exception as e:
            self.log(f"관심 종목 탐색 중 오류가 발생했습니다. pdno: {pdno} name: {name} error: {e}")
            pass

        # 관심 종목은 매수 할 수 있으므로 매도 리스트에도 추가한다.
        if changed_list:
            self.update_sell_list()

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
        
        if not self.price_analysis.is_purchase_overtime(pdno):
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

        if self.price_analysis.is_purchase_overtime(pdno):
            self._symbol_log(symbol_item, "현재 시간은 매수 추천이 종료된 시간입니다. 매수 주문 단계에서 판단 단계로 이동합니다.")
            state.step = TradeStep.JUDGE_STEP
            return

        cooldown_end = self.sell_cooldown.get(pdno, 0.0)
        if time.time() < cooldown_end:
            return

        if self.price_analysis.is_purchase_recommended(pdno) is False:
            return

        if pdno not in self.price_analysis.items or not self.price_analysis.items[pdno].candle_stick_5minute:
            return

        max_budget = 1000000
        current_price = int(self.price_analysis.items[pdno].candle_stick_5minute[-1].close_price)
        quantity = int(max_budget // current_price)
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
            self._symbol_log(symbol_item, "매수 체크하려 했으나 주문 번호가 없습니다. 매수 주문 단계로 이동합니다.")
            return

        if (
            state.buy_order_requested_at > 0
            and (time.time() - state.buy_order_requested_at) > self.BUY_ORDER_TIMEOUT_SECONDS
        ):
            try:
                self.auth.order.cancel_order(state.buy_order_no)
                # 매수 주문이 취소되었으므로 현재 보유 수량과 비교하여 체결된 수량을 계산한다.
                filled_quantity = self.update_account_stock_and_get_diff_quantity(pdno)

                self.trade_reporter.add(TradeType.BUY_CANCELLED, symbol_item, filled_quantity, 0, f"체결 대기 시간 {self.BUY_ORDER_TIMEOUT_SECONDS // 60}분 초과")  # 매수 주문 취소 로그 추가
                state.buy_order_no = ""
                state.buy_order_requested_at = 0.0
                state.step = TradeStep.JUDGE_STEP
            except Exception as e:
                self._symbol_log(symbol_item, f"매수 주문 체결 대기가 {self.BUY_ORDER_TIMEOUT_SECONDS // 60}분을 초과했으나 주문 취소에 실패했습니다: {e}")
            return

        check_order_result = self.check_order_completed(symbol_item, state.buy_order_no, True)

        if check_order_result.rmn_qty == 0:
            # 잔여수량이 0이면 모두 체결된 것이므로 매도 주문 단계로 이동한다.
            self.update_account_stock()
            state.buy_order_no = ""
            state.buy_order_requested_at = 0.0
            self.trade_reporter.add(TradeType.BUY_COMPLETED, symbol_item, check_order_result.tot_ccld_qty, check_order_result.ord_unpr)  # 매수 체결 로그 추가
            state.step = TradeStep.DECIDE_ON_SELL

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

        if self.price_analysis.is_sell_stop_loss_recommended(pdno, purchase_price):
            current_price = int(self.price_analysis.items[pdno].candle_stick_5minute[-1].close_price) if pdno in self.price_analysis.items and self.price_analysis.items[pdno].candle_stick_5minute else 0
            order = self.immediately_sell(symbol_item, quantity)
            state.sell_order_no = order.get("ODNO", "") if isinstance(order, dict) else ""
            state.sell_order_requested_at = time.time() if state.sell_order_no else 0.0
            self._symbol_log(symbol_item, f"손절 추천: 구매가: {purchase_price} / 현재가: {current_price}")
            self.trade_reporter.add(TradeType.IMMEDIATE_SELL, symbol_item, quantity, current_price)  # 즉시 매도 주문 로그 추가
            state.step = TradeStep.WAIT_ACCEPT_SELL
            return

        if not self.price_analysis.is_sell_recommended(pdno, purchase_price):
            return

        if pdno not in self.price_analysis.items or not self.price_analysis.items[pdno].candle_stick_5minute:
            return

        current_price = int(self.price_analysis.items[pdno].candle_stick_5minute[-1].close_price)
        order = self.sell(symbol_item, quantity, current_price)
        self.trade_reporter.add(TradeType.SELL, symbol_item, quantity, current_price)
        state.sell_order_no = order.get("ODNO", "") if isinstance(order, dict) else ""
        state.sell_order_requested_at = time.time() if state.sell_order_no else 0.0
        state.step = TradeStep.WAIT_ACCEPT_SELL

    def _process_step_sell_check(self, symbol_item: SymbolItem):
        pdno = symbol_item.pdno
        state = self._get_trade_state(pdno)
        if not state.sell_order_no:
            state.sell_order_requested_at = 0.0
            state.step = TradeStep.DECIDE_ON_PURCHASE
            self._symbol_log(symbol_item, "매도 체크하려 했으나 주문 번호가 없습니다. 매수 주문 단계로 이동합니다.")
            return

        if (
            state.sell_order_requested_at > 0
            and (time.time() - state.sell_order_requested_at) > self.SELL_ORDER_TIMEOUT_SECONDS
        ):
            try:
                self.auth.order.cancel_order(state.sell_order_no)
                # 매도 주문이 취소되었으므로 현재 보유 수량과 비교하여 체결된 수량을 계산한다.
                filled_quantity = self.update_account_stock_and_get_diff_quantity(pdno) * -1 # 매도 주문이므로 보유 수량에서 빠져나가는 것이어서 음수로 계산

                self.trade_reporter.add(TradeType.SELL_CANCELLED, symbol_item, filled_quantity, 0, f"체결 대기 시간 {self.SELL_ORDER_TIMEOUT_SECONDS // 60}분 초과")  # 매도 주문 취소 로그 추가
                state.sell_order_no = ""
                state.sell_order_requested_at = 0.0
                state.step = TradeStep.JUDGE_STEP
            except Exception as e:
                self._symbol_log(symbol_item, f"매도 주문 체결 대기가 {self.SELL_ORDER_TIMEOUT_SECONDS // 60}분을 초과했으나 주문 취소에 실패했습니다: {e}")
            return
        
        check_order_result = self.check_order_completed(symbol_item, state.sell_order_no, False)

        if check_order_result.rmn_qty == 0:
            # 잔여수량이 0이면 모두 체결된 것이므로 매수 주문 단계로 이동한다.
            self.update_account_stock()

            state.sell_order_no = ""
            state.sell_order_requested_at = 0.0
            self.trade_reporter.add(TradeType.SELL_COMPLETED, symbol_item, check_order_result.tot_ccld_qty, check_order_result.ord_unpr)  # 매도 체결 로그 추가
            # 매도 후 30분간 (1800초) 해당 종목의 재진입을 금지하여 잦은 휩쏘로 인한 뇌동매매를 강도높게 방지한다.
            self.sell_cooldown[pdno] = time.time() + 1800
            state.step = TradeStep.DECIDE_ON_PURCHASE
            

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

    def process_once(self):
        '''
        장 시작 여부 확인
         - 장이 시작되지 않았으면, 장이 시작될 때까지 대기한다.
         - 장이 시작되면, _process_step 함수를 호출하여 매매 로직을 실행한다.
        '''
        now = time.time()

        self._collect_interest_stocks(now)

        if not self.is_market_open(now):
            if self.is_running:
                if time.localtime(now).tm_wday >= 5:
                    self.log("장이 쉬는 날입니다. 토요일과 일요일에는 동작하지 않습니다.")
                else:
                    self.log("장외 시간입니다. 9:00 ~ 15:30 사이에만 동작합니다.")
                self.price_analysis.save_cache()

            self.is_running = False
            return

        self.is_running = True
        self._process_step(now)

    def _process_step(self, now: float):
        # 종목별 상태머신 동작
        processed_pdnos = set()
        for symbol_item in self.monitor_list:
            pdno = symbol_item.pdno
            name = symbol_item.prdt_name
            if not pdno:
                continue
            if pdno in processed_pdnos:
                continue
            processed_pdnos.add(pdno)

            state = self._get_trade_state(pdno)

            # 모든 step: 현재가 조회 및 분석(update_price)
            self.update_price(symbol_item, now)
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
        if self.loop_count % 60 == 0:
            self.price_analysis.save_cache()

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
            item = self.price_analysis.items.get(pdno)
            current_price = None
            candle_count = 0
            volume = 0
            if item is not None and item.candle_stick_5minute:
                candle_count = len(item.candle_stick_5minute)
                current_price = item.candle_stick_5minute[-1].close_price
                volume = item.candle_stick_5minute[-1].volume

                inventory = self.auth.account.stocks_by_pdno.get(pdno)
                if inventory is not None:
                    purchase_price = float(inventory['pchs_avg_pric'])

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

        return {
            "market_open": self.is_market_open(),
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
        if not self.is_market_open():
            raise ValueError("장외 시간에는 주문할 수 없습니다.")

        if not pdno in self.price_analysis.items or not self.price_analysis.items[pdno].candle_stick_5minute:
            raise ValueError("현재가를 가져오지 못해 주문할 수 없습니다.")
        
        symbol_item = self.price_analysis.items[pdno].symbol_item
        price = self.price_analysis.items[pdno].candle_stick_5minute[-1].close_price

        result = self.buy(symbol_item, quantity, price)
        self.update_account_stock()
        return result

    def place_manual_sell(self, pdno: str, quantity: int):
        if quantity <= 0:
            raise ValueError("수량은 1 이상이어야 합니다.")
        if not self.is_market_open():
            raise ValueError("장외 시간에는 주문할 수 없습니다.")
        
        if not pdno in self.price_analysis.items or not self.price_analysis.items[pdno].candle_stick_5minute:
            raise ValueError("현재가를 가져오지 못해 주문할 수 없습니다.")

        symbol_item = self.price_analysis.items[pdno].symbol_item
        price = self.price_analysis.items[pdno].candle_stick_5minute[-1].close_price

        inventory = self.auth.account.stocks_by_pdno.get(pdno)
        if inventory is None:
            raise ValueError("보유하지 않은 종목입니다.")

        holding_qty = int(inventory.get('hldg_qty', 0))
        if quantity > holding_qty:
            raise ValueError(f"보유 수량({holding_qty})을 초과하여 매도할 수 없습니다.")

        result = self.sell(symbol_item, quantity, price)
        self.update_account_stock()
        return result

    def update_sell_list(self):
        self.update_account_stock()

        # self.kosdq_monitor_list에 매도 리스트 업데이트
        self.monitor_list: list[SymbolItem] = []
        monitor_pdnos = set()

        # 먼저 관심종목들을 모니터링 리스트에 추가
        for stock in self.interest_stock_manager.get_stocks():
            self.monitor_list.append(stock)
            monitor_pdnos.add(stock.pdno)

        # 재고로 가지고 있는 건 모두 모니터링 리스트에 추가
        for stock in self.auth.account.stocks:
            pdno = stock.get('pdno', '')
            prdt_name = stock.get('prdt_name', '')
            if pdno not in monitor_pdnos:
                self.monitor_list.append(SymbolItem(pdno, prdt_name))
                monitor_pdnos.add(pdno)

    def update_account_stock_and_get_diff_quantity(self, pdno: str) -> int:
        old_quantity = int(self._find_inventory(pdno)['hldg_qty']) if self._find_inventory(pdno) else 0
        self.update_account_stock()
        new_quantity = int(self._find_inventory(pdno)['hldg_qty']) if self._find_inventory(pdno) else 0
        return new_quantity - old_quantity

    def update_account_stock(self):
        try_count = 0
        while True:
            try:
                self.auth.account.update_stock()
                break
            except Exception as e:
                if try_count >= 5:
                    self.log(f"계좌 Stock 정보 업데이트 실패: {e}")
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

    def check_order_completed(self, symbol_item: SymbolItem, order_no: str, is_buy: bool) -> OrderCheckResult:
        """매도/매수 주문 체결 여부 확인"""
        pd_no = symbol_item.pdno
        try_count = 0

        while True:
            try:
                check_list: List[OrderCheckResult] = self.auth.order.order_check(pd_no, order_no, is_buy)

                total_check_result = OrderCheckResult()

                for check in check_list:
                    total_check_result.add(check)

                return total_check_result
            except Exception as e:
                if try_count >= 5:
                    if is_buy:
                        self._symbol_log(symbol_item, f"매수 주문 체결 확인 실패\n{e}")
                    else:
                        self._symbol_log(symbol_item, f"매도 주문 체결 확인 실패\n{e}")

                time.sleep(1)  # 잠시 대기 후 재시도
                try_count += 1
                continue

    def sell(self, symbol_item: SymbolItem, quantity: int, price: int):
        """현금 매도 주문"""
        while True:
            try:
                return self.auth.order.sell_order_cash(symbol_item.pdno, quantity, price)
            except Exception as e:
                self._symbol_log(symbol_item, f"매도 주문 실패\n{e}")
                time.sleep(1)  # 잠시 대기 후 재시도
                continue
    
    def immediately_sell(self, symbol_item: SymbolItem, quantity: int):
        """즉시 매도 주문 (시장가)"""
        while True:
            try:
                return self.auth.order.immediately_sell(symbol_item.pdno, quantity)
            except Exception as e:
                self._symbol_log(symbol_item, f"즉시 매도 주문 실패\n{e}")
                time.sleep(1)  # 잠시 대기 후 재시도
                continue

if __name__ == "__main__":
    bot = DayTradingBot()
    bot.run()
