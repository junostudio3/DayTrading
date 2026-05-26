from api.kis_auth_order import OrderCheckResult
from api.kis_user import KisUser
from common_structure import SymbolItem
from dataclasses import dataclass
from filter import TradingParams
from trade_reporter import TradeReporter
from trade_reporter import TradeType
from trade_step import TradeStep
from typing import List
from typing import Optional

import json
import os
import time


@dataclass
class TradeState:
    step: TradeStep = TradeStep.JUDGE_STEP
    buy_order_no: str = ""
    sell_order_no: str = ""
    buy_order_requested_at: float = 0.0
    sell_order_requested_at: float = 0.0
    cooldown_until: float = 0.0


class TradeBotDaily:
    def __init__(self, parent, user: KisUser):
        from trade_bot_manager import TradeBotManager
        self.parent: TradeBotManager = parent
        self.log = parent.log
        self.trade_log = parent.trade_log
        self.user = user
        self.auth = user.auth
        self.app_id = user.app_id

        self.loop_count = 0
        self.pdno_states: dict[str, TradeState] = {}
        self.buy_fail_counts: dict[str, int] = {}
        self.monitor_list: list[SymbolItem] = []
        self.trade_reporter = TradeReporter(self)
        
        self.bot_purchases_path = f"./cache/daily_bot_purchases_{self.app_id}.json"
        self.bot_purchased_pdnos = set()
        self._load_bot_purchases()

        self.update_sell_list()

    def _load_bot_purchases(self):
        if os.path.exists(self.bot_purchases_path):
            try:
                with open(self.bot_purchases_path, "r") as f:
                    data = json.load(f)
                    self.bot_purchased_pdnos = set(data.get("purchased_pdnos", []))
            except Exception as e:
                self.log(f"봇 구매 내역 로드 중 오류 발생: {e}")

    def _save_bot_purchases(self):
        try:
            os.makedirs(os.path.dirname(self.bot_purchases_path), exist_ok=True)
            with open(self.bot_purchases_path, "w") as f:
                json.dump({"purchased_pdnos": list(self.bot_purchased_pdnos)}, f)
        except Exception as e:
            self.log(f"봇 구매 내역 저장 중 오류 발생: {e}")

    def add_bot_purchase(self, pdno: str):
        self.bot_purchased_pdnos.add(pdno)
        self._save_bot_purchases()

    def remove_bot_purchase(self, pdno: str):
        if pdno in self.bot_purchased_pdnos:
            self.bot_purchased_pdnos.remove(pdno)
            self._save_bot_purchases()

    def set_logger(self, log):
        self.log = log

    def set_trade_logger(self, log):
        self.trade_log = log

    def display_account_info(self):
        self.log(f"예수금: {self.auth.portfolio.balance.dnca_tot_amt}")
        self.log(f"D+1 예수금: {self.auth.portfolio.balance.nxdy_excc_amt}")
        self.log(f"D+2 예수금: {self.auth.portfolio.balance.prvs_rcdl_excc_amt}")
        self.log("주식 잔고:")
        if not self.auth.portfolio.stocks:
            self.log("보유 주식이 없습니다.")
        else:
            for stock in self.auth.portfolio.stocks:
                self.log(f"종목번호: {stock['pdno']} {stock['prdt_name']}, 보유수량: {stock['hldg_qty']}, 매입평균가: {stock['pchs_avg_pric']}")

    def _find_inventory(self, pdno: str):
        return self.auth.portfolio.stocks_by_pdno.get(pdno)

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

        # self.auth.portfolio.stocks 내에 현재 심볼이 존재하는지 확인하여 매도 주문 단계로 이동
        if self._find_inventory(pdno) is not None:
            if pdno in self.bot_purchased_pdnos:
                state.step = TradeStep.DECIDE_ON_SELL
                self._symbol_log(symbol_item, "봇이 매수했던 보유 수량이 확인되어 매도 주문 단계로 이동합니다.")
            else:
                # self._symbol_log(symbol_item, "수동으로 매수/보유 중인 종목이므로 단타 봇이 개입하지 않고 무시합니다.")
                pass
            return
        else:
            if pdno in self.bot_purchased_pdnos:
                self.remove_bot_purchase(pdno)

        if not self.parent.price_analysis.is_purchase_overtime(pdno):
            # 보유 수량이 없는 경우 매수 주문 단계로 이동
            # 단 3시부터는 매도를 시작하므로 2시 50분부터는 그냥 판단 단계에 머무르도록 한다.
            state.step = TradeStep.DECIDE_ON_PURCHASE
            self._symbol_log(symbol_item, "보유 수량이 없어서 매수 주문 단계로 이동합니다.")
            return

    def _add_daily_purchase(self, pdno: str):
        purchases = self._get_daily_purchases()
        purchases.add(pdno)
        with open(self.daily_bot_purchases_file, "w") as f:
            json.dump(list(purchases), f)

    def _remove_daily_purchase(self, pdno: str):
        purchases = self._get_daily_purchases()
        if pdno in purchases:
            purchases.remove(pdno)
            with open(self.daily_bot_purchases_file, "w") as f:
                json.dump(list(purchases), f)

    def _get_daily_purchases(self):
        if os.path.exists(self.daily_bot_purchases_file):
            with open(self.daily_bot_purchases_file, "r") as f:
                return set(json.load(f))
        return set()

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

        if TradingParams.USE_MARKET_INDEX_FILTER and self.parent.market_index_kosdaq_drop_rate <= TradingParams.MARKET_INDEX_DROP_LIMIT:
            # 시장 지수가 과도하게 하락한 장세일 경우 매수 진입을 완전히 차단한다.
            return

        if time.time() < state.cooldown_until:
            return

        if self.parent.price_analysis.is_purchase_recommended(pdno) is False:
            return

        if pdno not in self.parent.price_analysis.items or not self.parent.price_analysis.items[pdno].candle_stick_5minute:
            return

        budget = self.auth.portfolio.balance.dnca_tot_amt

        # 수수료를 감안하여 budget에 여유를 둔다. (약 만원 정도 여유를 둔다고 가정)
        # 어차피 비싼 종목은 사지 않게 되어 있으므로 큰 문제가 되지는 않을 것이다.
        budget = max(0, budget - 10000)

        # 최대 200만원까지 투자하도록 제한한다.
        budget = min(budget, 2000000)

        # 총평가금액 기준으로 한종목에 50% 이상 투자하지 않도록 제한한다.
        balance = self.auth.portfolio.balance
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
        self.add_bot_purchase(pdno)
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
            self.parent.update_portfolio(record_history=False, user=self.user)
            state.buy_order_no = ""
            state.buy_order_requested_at = 0.0
            self.trade_reporter.add(TradeType.BUY_COMPLETED, symbol_item, check_order_result.tot_ccld_qty, check_order_result.avg_prvs)  # 매수 체결 로그 추가
            state.step = TradeStep.DECIDE_ON_SELL
        elif (
            state.buy_order_requested_at > 0
            and (time.time() - state.buy_order_requested_at) > TradingParams.BUY_ORDER_TIMEOUT_SECONDS
        ):
            try:
                # 취소 전에 order_check API로 실제 체결 수량을 조회한다.
                check_result = self.check_order_completed(symbol_item, state.buy_order_no, True)
                self.auth.order.cancel_order(state.buy_order_no)
                self.parent.update_portfolio(record_history=False, user=self.user)
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

        is_stop_loss, stop_reason = self.parent.price_analysis.is_sell_stop_loss_recommended(pdno, purchase_price)
        if is_stop_loss:
            current_price = int(self.parent.price_analysis.items[pdno].candle_stick_5minute[-1].close_price) if pdno in self.parent.price_analysis.items and self.parent.price_analysis.items[pdno].candle_stick_5minute else 0
            order = self.immediately_sell(symbol_item, quantity)
            if order is None:
                self._symbol_log(symbol_item, f"손절 추천[{stop_reason}]이지만 즉시 매도 주문에 실패했습니다. 다음 루프에서 다시 시도합니다.")
                return

            state.sell_order_no = order.get("ODNO", "") if isinstance(order, dict) else ""
            state.sell_order_requested_at = time.time() if state.sell_order_no else 0.0
            self._symbol_log(symbol_item, f"손절 추천 [{stop_reason}]: 구매가: {purchase_price} / 현재가: {current_price}")
            self.trade_reporter.add(TradeType.IMMEDIATE_SELL, symbol_item, quantity, current_price, text=stop_reason)  # 즉시 매도 주문 로그 추가
            state.step = TradeStep.WAIT_ACCEPT_SELL
            return

        is_recommend, reason = self.parent.price_analysis.is_sell_recommended(pdno, purchase_price, state.buy_order_requested_at)
        if not is_recommend:
            return

        if pdno not in self.parent.price_analysis.items or not self.parent.price_analysis.items[pdno].candle_stick_5minute:
            return

        current_price = int(self.parent.price_analysis.items[pdno].candle_stick_5minute[-1].close_price)
        
        self._symbol_log(symbol_item, f"일반 익절/매도 추천 [{reason}]: 구매가: {purchase_price} / 현재가: {current_price}")
        
        if "트레일링스탑" in reason or "강제익절" in reason or "장마감임박 익절" in reason:
            order = self.immediately_sell(symbol_item, quantity)
            trade_type = TradeType.IMMEDIATE_SELL
        else:
            order = self.sell(symbol_item, quantity, current_price)
            trade_type = TradeType.SELL
            
        if order is None:
            return

        self.trade_reporter.add(trade_type, symbol_item, quantity, current_price, text=reason)
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
            self.parent.update_portfolio(record_history=False, user=self.user)

            state.sell_order_no = ""
            state.sell_order_requested_at = 0.0
            self.trade_reporter.add(TradeType.SELL_COMPLETED, symbol_item, check_order_result.tot_ccld_qty, check_order_result.avg_prvs)  # 매도 체결 로그 추가 (평균체결가 사용)
            
            if purchase_price > 0:
                is_profit = float(check_order_result.avg_prvs) > purchase_price
                self.parent.daily.watchlist.apply_trade_result(pdno, is_profit)

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
                self.parent.update_portfolio(record_history=False, user=self.user)
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

    def _process_step(self, now: float):
        # 종목별 상태머신 동작
        processed_pdnos = set()
        for symbol_item in self.monitor_list:
            pdno = symbol_item.pdno
            if not pdno:
                continue
            if pdno in processed_pdnos:
                continue
            if self.user.use_daily_bot is False:
                # 사용자 설정에서 일간 봇 사용 안함으로 되어 있으면 일간 봇이 개입하지 않고 판단 단계에 머무르도록 한다.
                # 봇 자체를 비활성화하는 것이 좋겠지만 현재 코드가 정리가 되어 있지 않아서 일단은 이렇게 처리한다.
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
        for stock in self.auth.portfolio.stocks:
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
                "tot_evlu_amt": self.auth.portfolio.balance.tot_evlu_amt,
                "cash": self.auth.portfolio.balance.dnca_tot_amt,
                "d1": self.auth.portfolio.balance.nxdy_excc_amt,
                "d2": self.auth.portfolio.balance.prvs_rcdl_excc_amt,
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
        self.parent.update_portfolio(record_history=False, user=self.user)
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

        inventory = self.auth.portfolio.stocks_by_pdno.get(pdno)
        if inventory is None:
            raise ValueError("보유하지 않은 종목입니다.")

        holding_qty = int(inventory.get('hldg_qty', 0))
        if quantity > holding_qty:
            raise ValueError(f"보유 수량({holding_qty})을 초과하여 매도할 수 없습니다.")

        result = self.sell(symbol_item, quantity, price)
        if result is None:
            raise ValueError("매도 주문이 실패했습니다.")

        self.parent.update_portfolio(record_history=False, user=self.user)
        return result

    def update_sell_list(self):
        self.parent.update_portfolio(record_history=False, user=self.user)

        self.monitor_list: list[SymbolItem] = []
        monitor_pdnos = set()

        # 먼저 관심종목들을 모니터링 리스트에 추가
        for stock in self.parent.daily.watchlist.get_stocks():
            self.monitor_list.append(stock)
            monitor_pdnos.add(stock.pdno)

        # 재고로 가지고 있는 건 모두 모니터링 리스트에 추가
        for stock in self.auth.portfolio.stocks:
            pdno = stock.get('pdno', '')
            prdt_name = stock.get('prdt_name', '')
            if pdno not in monitor_pdnos:
                self.monitor_list.append(SymbolItem(pdno, prdt_name))
                monitor_pdnos.add(pdno)

    def updated_portfolio(self):
        self.trade_reporter.set_account_balance(self.auth.portfolio.balance)

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
