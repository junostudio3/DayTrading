from KisAuth import KisAuth
from KisKey import app_account
from KisKey import app_domain
from KisKey import app_is_virtual
from KisKey import app_key
from KisKey import app_secret
from InfoKosdaq import find_kosdaq_by_name, load_kosdaq_master
from InfoKospi import find_kospi_by_name, load_kospi_master
from PriceAnalysis import PriceAnalysis
from InterestStockManager import InterestStockManager
import time
from dataclasses import dataclass
from typing import Any, Optional
from TradeStep import TradeStep
from StockItem import StockItem


@dataclass
class TradeState:
    step: TradeStep = TradeStep.JUDGE_STEP
    buy_order_no: str = ""
    sell_order_no: str = ""
    buy_order_requested_at: float = 0.0
    sell_order_requested_at: float = 0.0

class DayTradingBot:
    ORDER_TIMEOUT_SECONDS = 60 * 5

    def __init__(self):
        self.auth = KisAuth(app_key, app_secret, app_account, app_is_virtual, app_domain)
        self.auth.account.update()

        self.price_analysis = PriceAnalysis("./cache/price_analysis_cache.json")
        self.interest_stock_manager = InterestStockManager("./cache/interest_stocks.json")
        self.loop_count = 0
        self.is_running = True
        self.pdno_states: dict[str, TradeState] = {}
        self.buy_fail_counts: dict[str, int] = {}
        self.monitor_list: list[StockItem] = []
        self.price_update_interval_sec = 2.5
        self.last_price_update_at: dict[str, float] = {}
        self.kosdq_records = load_kosdaq_master()
        self.kospi_records = load_kospi_master()
        self.all_records = self.kospi_records + self.kosdq_records

        # print로 로그를 남기도록 한다.
        self.log = print
        self.update_sell_list()

        from TradeReporter import TradeReporter
        self.trade_reporter = TradeReporter(self)

    def run(self):
        self.display_account_info()
        while True:
            self.process_once()
            time.sleep(1)

    def display_account_info(self):
        self.log(f"예수금: {self.auth.account.dnca_tot_amt}")
        self.log(f"D+1 예수금: {self.auth.account.nxdy_excc_amt}")
        self.log(f"D+2 예수금: {self.auth.account.prvs_rcdl_excc_amt}")
        self.log("주식 잔고:")
        if not self.auth.account.stocks:
            self.log("보유 주식이 없습니다.")
        else:
            for stock in self.auth.account.stocks:
                self.log(f"종목번호: {stock['pdno']} {self._stock_name(stock)}, 보유수량: {stock['hldg_qty']}, 매입평균가: {stock['pchs_avg_pric']}")

    def update_price(self, pdno: str, now: Optional[float] = None, force: bool = False, name: Optional[str] = None) -> Optional[float]:
        """단일 종목의 현재가 조회"""
        if now is None:
            now = time.time()

        cached_item = self.price_analysis.items.get(pdno)
        if not force:
            last_update_at = self.last_price_update_at.get(pdno, 0.0)
            if now - last_update_at < self.price_update_interval_sec:
                if cached_item is not None and cached_item.candle_stick_5minute:
                    return cached_item.candle_stick_5minute[-1].close_price

        error_count = 0
        while error_count < 5:
            try:
                current_time = time.localtime(now)
                hour = current_time.tm_hour
                minute = current_time.tm_min
                candle = self.auth.price.get_one_minute_candlestick(pdno, hour, minute)
                price = None
                volume = None
                stick_time = None
                # candle 데이터중 첫번째 (가장 최근 데이터)의 현재가와 체결량을 가져온다.)
                if candle and len(candle) > 0 and "stck_prpr" in candle[0] and "cntg_vol" in candle[0] and "stck_cntg_hour" in candle[0]:
                    price = float(candle[0]["stck_prpr"])
                    volume = int(candle[0]["cntg_vol"])
                    stick_time = candle[0]["stck_cntg_hour"]
                else:
                    raise ValueError("캔들스틱 데이터를 가져오지 못했습니다.")

                break
            except Exception as e:
                error_count += 1
                if error_count >= 5:
                    self.log(f"Error fetching current price for {pdno} after 5 attempts: {e}")
                    return None

                time.sleep(1)  # 잠시 대기 후 재시도
                continue

        self.last_price_update_at[pdno] = now

        if self.price_analysis.add_price(pdno, price, volume, stick_time):
            # 가격이 업데이트된 경우에만 로그에 남기기에는 너무 많으므로 콘솔에 출력함

            if name is None:
                print(f"관심 종목: [{pdno}] / 현재가: {price} / 체결: {volume}")
            else:
                print(f"관심 종목: [{pdno}] {name} / 현재가: {price} / 체결: {volume}")
        return price

    def _stock_pdno(self, stock: Any) -> str:
        if isinstance(stock, dict):
            return stock.get('pdno', '')
        return getattr(stock, 'mksc_shrn_iscd', '')

    def _stock_name(self, stock: Any) -> str:
        if isinstance(stock, dict):
            return stock.get('prdt_name', stock.get('pdno', ''))
        return getattr(stock, 'hts_kor_isnm', self._stock_pdno(stock))

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

        if not self.all_records:
            return

        explore_index = self.interest_stock_manager.get_explore_index()

        # 한 번 호출 시 하나씩 조회 (인덱스 유지)
        if explore_index >= len(self.all_records):
            explore_index = 0
            self.interest_stock_manager.enable_keep_7days()

        record = self.all_records[explore_index]
        pdno = self._stock_pdno(record)
        name = self._stock_name(record)
        
        self.interest_stock_manager.set_explore_index(explore_index + 1)

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

    def _process_step_judge(self, pdno: str, name: str):
        self.update_sell_list()
        state = self._get_trade_state(pdno)

        # self.auth.account.stocks 내에 현재 심볼이 존재하는지 확인하여 매도 주문 단계로 이동
        if self._find_inventory(pdno) is not None:
            state.step = TradeStep.DECIDE_ON_SELL
            self.log(f"[{pdno}] {name} 보유 수량이 확인되어 매도 주문 단계로 이동합니다.")
            return
        else:
            # 보유 수량이 없는 경우 매수 주문 단계로 이동
            state.step = TradeStep.DECIDE_ON_PURCHASE
            self.log(f"[{pdno}] {name} 보유 수량이 없어서 매수 주문 단계로 이동합니다.")
            return

    def _process_step_order_buy(self, pdno: str, name: str):
        state = self._get_trade_state(pdno)
        inventory = self._find_inventory(pdno)
        if inventory is not None:
            # 이상하다 보유 수량이 있는데 매수 주문 단계에 있다.
            # 다시 판단 단계로 이동한다.
            state.step = TradeStep.JUDGE_STEP
            self.log(f"[{pdno}] {name} 보유 수량이 확인되었으나 매수 주문 단계에 있어 판단 단계로 이동합니다.")
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
            self.log(
                f"[{pdno}] {name} 매수 연속 실패 {fail_count}회로 수량을 1 감소하여 재시도합니다. "
                f"({quantity} -> {order_quantity})"
            )

        order = self.buy(pdno, order_quantity, current_price)
        if order is None:
            self.buy_fail_counts[pdno] = fail_count + 1
            self.log(
                f"매수 주문이 실패했습니다: [{pdno}] {name} / 수량: {order_quantity} / 가격: {current_price} "
                f"/ 연속 실패: {self.buy_fail_counts[pdno]}"
            )

            if self.buy_fail_counts[pdno] >= 20:
                self.log(f"[{pdno}] {name} 매수 연속 실패가 20회에 도달하여 Fail 관련 카운트를 초기화합니다.")
                self.buy_fail_counts[pdno] = 0  # 실패 카운트 초기화

            return

        self.buy_fail_counts[pdno] = 0

        order_no = order.get("ODNO", "")

        self.trade_reporter.add_buy_order(pdno, name, order_quantity, current_price)  
        state.buy_order_no = order_no
        state.buy_order_requested_at = time.time()
        state.step = TradeStep.WAIT_ACCEPT_PURCHASE

    def _process_step_buy_check(self, pdno: str, name: str):
        state = self._get_trade_state(pdno)
        if not state.buy_order_no:
            state.buy_order_requested_at = 0.0
            state.step = TradeStep.DECIDE_ON_PURCHASE
            self.log(f"{pdno}] {name} 매수 체크하려 했으나 주문 번호가 없습니다. 매수 주문 단계로 이동합니다.")
            return

        if (
            state.buy_order_requested_at > 0
            and (time.time() - state.buy_order_requested_at) > self.ORDER_TIMEOUT_SECONDS
        ):
            try:
                self.auth.order.cancel_order(state.buy_order_no)
                self.trade_reporter.add_buy_order_cncelled(pdno, name, "체결 대기 시간 5분 초과")  # 매수 주문 취소 로그 추가
                state.buy_order_no = ""
                state.buy_order_requested_at = 0.0
                state.step = TradeStep.JUDGE_STEP
            except Exception as e:
                self.log(f"[{pdno}] {name} 매수 주문 체결 대기가 5분을 초과했으나 주문 취소에 실패했습니다: {e}")
            return

        if self.check_order_completed(pdno, state.buy_order_no, True):
            self.update_account_stock()
            self.interest_stock_manager.update_trade_date(pdno)
            state.buy_order_no = ""
            state.buy_order_requested_at = 0.0
            self.trade_reporter.add_buy_order_completed(pdno, name)  # 매수 체결 로그 추가
            state.step = TradeStep.DECIDE_ON_SELL

    def _process_order_sell(self, pdno: str, name: str):
        state = self._get_trade_state(pdno)
        inventory = self._find_inventory(pdno)
        if inventory is None:
            state.step = TradeStep.DECIDE_ON_PURCHASE
            state.sell_order_no = ""
            state.sell_order_requested_at = 0.0
            self.log(f"[{pdno}] {name} 매도를 준비하려 했으나 보유 수량이 없습니다. 매수 주문 단계로 이동합니다.")
            return

        purchase_price = float(inventory['pchs_avg_pric'])
        quantity = int(inventory['hldg_qty'])

        if self.price_analysis.is_sell_stop_loss_recommended(pdno, purchase_price):
            current_price = self.price_analysis.items[pdno].candle_stick_5minute[-1].close_price if pdno in self.price_analysis.items and self.price_analysis.items[pdno].candle_stick_5minute else 0
            order = self.immediately_sell(pdno, quantity)
            state.sell_order_no = order.get("ODNO", "") if isinstance(order, dict) else ""
            state.sell_order_requested_at = time.time() if state.sell_order_no else 0.0
            self.log(f"손절 추천: [{pdno}] {name} / 구매가: {purchase_price} / 현재가: {current_price}")
            self.trade_reporter.add_immediate_sell_order(pdno, name, quantity, current_price)  # 가격이 0인 것은 시장가 주문을 의미한다.
            state.step = TradeStep.WAIT_ACCEPT_SELL
            return

        if not self.price_analysis.is_sell_recommended(pdno, purchase_price):
            return

        if pdno not in self.price_analysis.items or not self.price_analysis.items[pdno].candle_stick_5minute:
            return

        current_price = int(self.price_analysis.items[pdno].candle_stick_5minute[-1].close_price)
        order = self.sell(pdno, quantity, current_price)
        self.trade_reporter.add_sell_order(pdno, name, quantity, current_price)
        state.sell_order_no = order.get("ODNO", "") if isinstance(order, dict) else ""
        state.sell_order_requested_at = time.time() if state.sell_order_no else 0.0
        state.step = TradeStep.WAIT_ACCEPT_SELL

    def _process_step_sell_check(self, pdno: str, name: str):
        state = self._get_trade_state(pdno)
        if not state.sell_order_no:
            state.sell_order_requested_at = 0.0
            state.step = TradeStep.DECIDE_ON_PURCHASE
            self.log(f"[{pdno}] {name} 매도 체크하려 했으나 주문 번호가 없습니다. 매수 주문 단계로 이동합니다.")
            return

        if (
            state.sell_order_requested_at > 0
            and (time.time() - state.sell_order_requested_at) > self.ORDER_TIMEOUT_SECONDS
        ):
            try:
                self.auth.order.cancel_order(state.sell_order_no)
                self.trade_reporter.add_sell_order_cancelled(pdno, name, "체결 대기 시간 5분 초과")  # 매도 주문 취소 로그 추가
                state.sell_order_no = ""
                state.sell_order_requested_at = 0.0
                state.step = TradeStep.JUDGE_STEP
            except Exception as e:
                self.log(f"[{pdno}] {name} 매도 주문 체결 대기가 5분을 초과했으나 주문 취소에 실패했습니다: {e}")
            return

        if self.check_order_completed(pdno, state.sell_order_no, False):
            self.update_account_stock()
            self.interest_stock_manager.update_trade_date(pdno)
            state.sell_order_no = ""
            state.sell_order_requested_at = 0.0
            self.trade_reporter.add_sell_order_completed(pdno, name)  # 매도 체결 로그 추가
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
        for stock in self.monitor_list:
            pdno = stock.pdno
            name = stock.prdt_name
            if not pdno:
                continue
            if pdno in processed_pdnos:
                continue
            processed_pdnos.add(pdno)

            state = self._get_trade_state(pdno)

            # 모든 step: 현재가 조회 및 분석(update_price)
            self.update_price(pdno, now, name=name)
            step = state.step

            if step == TradeStep.JUDGE_STEP:
                # step0: 스탭판단
                self._process_step_judge(pdno, name)
            elif step == TradeStep.DECIDE_ON_PURCHASE:
                # step1: 매수 가능 확인 (매수 주문 후 step2)
                self._process_step_order_buy(pdno, name)
            elif step == TradeStep.WAIT_ACCEPT_PURCHASE:
                # step2: 체결 확인 자리(현재는 step3으로 패스)
                self._process_step_buy_check(pdno, name)
            elif step == TradeStep.DECIDE_ON_SELL:
                # step3: 매도 가능 확인 (매도 주문 후 step4)
                self._process_order_sell(pdno, name)
            elif step == TradeStep.WAIT_ACCEPT_SELL:
                # step4: 체결 확인 자리(현재는 step1으로 패스)
                self._process_step_sell_check(pdno, name)
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
            "explore_index": self.interest_stock_manager.get_explore_index(),
            "max_count": len(self.all_records),
            "account": {
                "cash": self.auth.account.dnca_tot_amt,
                "d1": self.auth.account.nxdy_excc_amt,
                "d2": self.auth.account.prvs_rcdl_excc_amt,
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

        if pdno in self.price_analysis.items and self.price_analysis.items[pdno].candle_stick_5minute:
            price = self.price_analysis.items[pdno].candle_stick_5minute[-1].close_price
        else:
            price = self.update_price(pdno, force=True)
            if price is None:
                raise RuntimeError("현재가를 가져오지 못해 주문할 수 없습니다.")

        result = self.buy(pdno, quantity, price)
        self.update_account_stock()
        self.interest_stock_manager.update_trade_date(pdno)
        return result

    def place_manual_sell(self, pdno: str, quantity: int):
        if quantity <= 0:
            raise ValueError("수량은 1 이상이어야 합니다.")
        if not self.is_market_open():
            raise ValueError("장외 시간에는 주문할 수 없습니다.")

        inventory = self.auth.account.stocks_by_pdno.get(pdno)
        if inventory is None:
            raise ValueError("보유하지 않은 종목입니다.")

        holding_qty = int(inventory.get('hldg_qty', 0))
        if quantity > holding_qty:
            raise ValueError(f"보유 수량({holding_qty})을 초과하여 매도할 수 없습니다.")

        if pdno in self.price_analysis.items and self.price_analysis.items[pdno].candle_stick_5minute:
            price = self.price_analysis.items[pdno].candle_stick_5minute[-1].close_price
        else:
            price = self.update_price(pdno, force=True)
            if price is None:
                raise RuntimeError("현재가를 가져오지 못해 주문할 수 없습니다.")

        result = self.sell(pdno, quantity, price)
        self.update_account_stock()
        self.interest_stock_manager.update_trade_date(pdno)
        return result

    def update_sell_list(self):
        self.update_account_stock()

        # self.kosdq_monitor_list에 매도 리스트 업데이트
        self.monitor_list: list[StockItem] = []
        monitor_pdnos = set()
        # 먼저 매수 리스트에 있는 종목들을 모니터링 리스트에 추가
        for stock in self.interest_stock_manager.get_stocks():
            self.monitor_list.append(stock)
            pdno = stock.pdno
            if pdno:
                monitor_pdnos.add(pdno)

        # 재고로 가지고 있는 건 모두 모니터링 리스트에 추가
        for stock in self.auth.account.stocks:
            pdno = stock.get('pdno', '')
            if pdno and pdno not in monitor_pdnos:
                self.monitor_list.append(stock)
                monitor_pdnos.add(pdno)

    def update_account_stock(self):
        try_count = 0
        while True:
            try:
                self.auth.account.update_stock()
                break
            except Exception as e:
                if try_count >= 5:
                    self.log(f"계좌 정보 업데이트 실패: {e}")
                time.sleep(1)  # 잠시 대기 후 재시도
                try_count += 1

    def buy(self, pdno: str, quantity: int, price: int):
        """현금 매수 주문"""
        try:
            return self.auth.order.buy_order_cash(pdno, quantity, price)
        except Exception as e:
            self.log(f"매수 주문 실패: {e}")
            return None

    def check_order_completed(self, pd_no: str, order_no: str, is_buy: bool):
        """매도/매수 주문 체결 여부 확인"""
        while True:
            try:
                check_list = self.auth.order.order_check(pd_no, order_no, is_buy)

                for check in check_list:
                    if check.get("rmn_qty", "0") != "0":
                        # 잔여수량 0이 아니면 체결 안된 것으로 간주
                        return False
                return True
            except Exception as e:
                if is_buy:
                    self.log(f"매수 주문 체결 확인 실패: {e}")
                else:
                    self.log(f"매도 주문 체결 확인 실패: {e}")

                time.sleep(1)  # 잠시 대기 후 재시도
                continue

    def sell(self, pdno: str, quantity: int, price: int):
        """현금 매도 주문"""
        while True:
            try:
                return self.auth.order.sell_order_cash(pdno, quantity, price)
            except Exception as e:
                self.log(f"매도 주문 실패: {e}")
                time.sleep(1)  # 잠시 대기 후 재시도
                continue
    
    def immediately_sell(self, pdno: str, quantity: int):
        """즉시 매도 주문 (시장가)"""
        while True:
            try:
                result = self.auth.order.immediately_sell(pdno, quantity)
                self.update_sell_list()
                return result
            except Exception as e:
                self.log(f"즉시 매도 주문 실패: {e}")
                time.sleep(1)  # 잠시 대기 후 재시도
                continue

if __name__ == "__main__":
    bot = DayTradingBot()
    bot.run()
