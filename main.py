from KisAuth import KisAuth
from KisKey import app_account
from KisKey import app_domain
from KisKey import app_is_virtual
from KisKey import app_key
from KisKey import app_secret
from InfoKosdaq import find_kosdaq_by_name, load_kosdaq_master
from InfoKospi import find_kospi_by_name, load_kospi_master
from PriceAnalysis import PriceAnalysis
import time
from dataclasses import dataclass
from enum import Enum, auto
from typing import Any, Optional


class TradeStep(Enum):
    ORDER_BUY = auto()
    CHECK_BUY = auto()
    ORDER_SELL = auto()
    CHECK_SELL = auto()


@dataclass
class TradeState:
    step: TradeStep = TradeStep.ORDER_BUY
    buy_order_no: str = ""
    sell_order_no: str = ""

class DayTradingBot:
    def __init__(self, log_callback=None):
        # logger callback used for emitting messages; defaults to built-in print
        # TradingEngine will override this after construction so that all
        # bot-generated messages get forwarded to engine._append_log.
        self.log = log_callback or print

        kosdq_records = load_kosdaq_master()
        kospi_records = load_kospi_master()

        # 관심 종목을 리스트로 수집
        kospi_wish_names = []
        kospi_wish_names += ["대한항공"]

        kosdq_wish_names = []
        kosdq_wish_names += ["인텍플러스", "고영", "펨트론"]

        self.monitor_list = []
        self.buy_list = []
        self.price_update_interval_sec = 2.5
        self.last_price_update_at: dict[str, float] = {}

        # 관심 종목 정보 수집
        for name in kospi_wish_names:
            results = find_kospi_by_name(name, kospi_records)
            if results is None or len(results) == 0:
                self.log(f"{name} 종목을 찾을 수 없습니다.")
                exit(1)
            else:
                self.buy_list.append(results[0])
                self.monitor_list.append(results[0])

        for name in kosdq_wish_names:
            results = find_kosdaq_by_name(name, kosdq_records)
            if results is None or len(results) == 0:
                self.log(f"{name} 종목을 찾을 수 없습니다.")
                exit(1)
            else:
                self.buy_list.append(results[0])
                self.monitor_list.append(results[0])

        self.auth = KisAuth(app_key, app_secret, app_account, app_is_virtual, app_domain)
        self.auth.account.update()
        self.update_sell_list()

        self.price_analysis = PriceAnalysis("./cache/price_analysis_cache.json")
        self.loop_count = 0
        self.is_running = True
        self.symbol_states: dict[str, TradeState] = {}
        self.buy_fail_counts: dict[str, int] = {}

        # 초기에 관심 종목 주식을 가지고 있다면 step을 3으로 시작한다.
        for symbol in self.auth.account.stocks_by_symbol.keys():
            if symbol in [self._stock_symbol(item) for item in self.buy_list]:
                state = self._get_trade_state(symbol)
                state.step = TradeStep.ORDER_SELL

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

    def update_price(self, symbol: str, now: Optional[float] = None, force: bool = False, name: Optional[str] = None) -> Optional[float]:
        """단일 종목의 현재가 조회"""
        if now is None:
            now = time.time()

        cached_item = self.price_analysis.items.get(symbol)
        if not force:
            last_update_at = self.last_price_update_at.get(symbol, 0.0)
            if now - last_update_at < self.price_update_interval_sec:
                if cached_item is not None and cached_item.candle_stick_5minute:
                    return cached_item.candle_stick_5minute[-1].close_price

        error_count = 0
        while error_count < 5:
            try:
                current_time = time.localtime(now)
                hour = current_time.tm_hour
                minute = current_time.tm_min
                candle = self.auth.price.get_one_minute_candlestick(symbol, hour, minute)
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
                    self.log(f"Error fetching current price for {symbol} after 5 attempts: {e}")
                    return None

                time.sleep(1)  # 잠시 대기 후 재시도
                continue

        self.last_price_update_at[symbol] = now

        if self.price_analysis.add_price(symbol, price, volume, stick_time):
            # 가격이 업데이트된 경우에만 로그에 남기기에는 너무 많으므로 콘솔에 출력함

            if name is None:
                print(f"관심 종목: [{symbol}] / 현재가: {price} / 체결: {volume}")
            else:
                print(f"관심 종목: [{symbol}] {name} / 현재가: {price} / 체결: {volume}")
        return price

    def _stock_symbol(self, stock: Any) -> str:
        if isinstance(stock, dict):
            return stock.get('pdno', '')
        return getattr(stock, 'mksc_shrn_iscd', '')

    def _stock_name(self, stock: Any) -> str:
        if isinstance(stock, dict):
            return stock.get('prdt_name', stock.get('pdno', ''))
        return getattr(stock, 'hts_kor_isnm', self._stock_symbol(stock))

    def _find_inventory(self, symbol: str):
        return self.auth.account.stocks_by_symbol.get(symbol)

    def _get_trade_state(self, symbol: str) -> TradeState:
        if symbol not in self.symbol_states:
            self.symbol_states[symbol] = TradeState()
        return self.symbol_states[symbol]

    def _process_step_order_buy(self, symbol: str, name: str):
        state = self._get_trade_state(symbol)
        inventory = self._find_inventory(symbol)
        if inventory is not None:
            return

        if self.price_analysis.is_purchase_recommended(symbol) is False:
            return

        if symbol not in self.price_analysis.items or not self.price_analysis.items[symbol].candle_stick_5minute:
            return

        max_budget = 1000000
        current_price = int(self.price_analysis.items[symbol].candle_stick_5minute[-1].close_price)
        quantity = int(max_budget // current_price)
        if quantity <= 0:
            return

        fail_count = self.buy_fail_counts.get(symbol, 0)
        order_quantity = quantity
        if fail_count >= 10 and order_quantity > 1:
            order_quantity -= 1
            self.log(
                f"[{symbol}] {name} 매수 연속 실패 {fail_count}회로 수량을 1 감소하여 재시도합니다. "
                f"({quantity} -> {order_quantity})"
            )

        order = self.buy(symbol, order_quantity, current_price)
        if order is None:
            self.buy_fail_counts[symbol] = fail_count + 1
            self.log(
                f"매수 주문이 실패했습니다: [{symbol}] {name} / 수량: {order_quantity} / 가격: {current_price} "
                f"/ 연속 실패: {self.buy_fail_counts[symbol]}"
            )

            if self.buy_fail_counts[symbol] >= 20:
                self.log(f"[{symbol}] {name} 매수 연속 실패가 20회에 도달하여 Fail 관련 카운트를 초기화합니다.")
                self.buy_fail_counts[symbol] = 0  # 실패 카운트 초기화

            return

        self.buy_fail_counts[symbol] = 0

        order_no = order.get("ODNO", "")

        self.log(f"매수 주문: [{symbol}] {name} / 수량: {order_quantity} / 가격: {current_price}")
        state.buy_order_no = order_no
        state.step = TradeStep.CHECK_BUY

    def _process_step_buy_check(self, symbol: str, name: str):
        state = self._get_trade_state(symbol)
        if not state.buy_order_no:
            state.step = TradeStep.ORDER_BUY
            self.log(f"{symbol}] {name} 매수 체크하려 했으나 주문 번호가 없습니다. 매수 주문 단계로 이동합니다.")
            return

        if self.check_order_completed(symbol, state.buy_order_no, True):
            self.update_account_stock()
            state.buy_order_no = ""
            state.step = TradeStep.ORDER_SELL
            self.log(f"[{symbol}] {name} 매수 주문이 체결되었습니다. 매도 주문 단계로 이동합니다.")

    def _process_order_sell(self, symbol: str, name: str):
        state = self._get_trade_state(symbol)
        inventory = self._find_inventory(symbol)
        if inventory is None:
            state.step = TradeStep.ORDER_BUY
            state.sell_order_no = ""
            self.log(f"[{symbol}] {name} 매도를 준비하려 했으나 보유 수량이 없습니다. 매수 주문 단계로 이동합니다.")
            return

        purchase_price = float(inventory['pchs_avg_pric'])
        quantity = int(inventory['hldg_qty'])

        if self.price_analysis.is_sell_stop_loss_recommended(symbol, purchase_price):
            current_price = self.price_analysis.items[symbol].candle_stick_5minute[-1].close_price if symbol in self.price_analysis.items and self.price_analysis.items[symbol].candle_stick_5minute else 0
            order = self.immediately_sell(symbol, quantity)
            state.sell_order_no = order.get("ODNO", "") if isinstance(order, dict) else ""
            state.step = TradeStep.CHECK_SELL
            self.log(f"손절 추천: [{symbol}] {name} / 구매가: {purchase_price} / 현재가: {current_price}")
            self.log(f"즉시 매도 주문: [{symbol}] {name} / 수량: {quantity} / 가격: 시장가")
            return

        if not self.price_analysis.is_sell_recommended(symbol, purchase_price):
            return

        if symbol not in self.price_analysis.items or not self.price_analysis.items[symbol].candle_stick_5minute:
            return

        current_price = int(self.price_analysis.items[symbol].candle_stick_5minute[-1].close_price)
        order = self.sell(symbol, quantity, current_price)
        self.log(f"매도 주문: [{symbol}] {name} / 수량: {quantity} / 가격: {current_price}")
        state.sell_order_no = order.get("ODNO", "") if isinstance(order, dict) else ""
        state.step = TradeStep.CHECK_SELL

    def _process_step_sell_check(self, symbol: str, name: str):
        state = self._get_trade_state(symbol)
        if not state.sell_order_no:
            state.step = TradeStep.ORDER_BUY
            self.log(f"[{symbol}] {name} 매도 체크하려 했으나 주문 번호가 없습니다. 매수 주문 단계로 이동합니다.")
            return

        if self.check_order_completed(symbol, state.sell_order_no, False):
            self.update_account_stock()
            state.sell_order_no = ""
            state.step = TradeStep.ORDER_BUY
            self.log(f"[{symbol}] {name} 매도 주문이 체결되었습니다. 매수 주문 단계로 이동합니다.")

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
        now = time.time()

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

        # 종목별 상태머신 동작
        processed_symbols = set()
        for stock in self.monitor_list:
            symbol = self._stock_symbol(stock)
            name = self._stock_name(stock)
            if not symbol:
                continue
            if symbol in processed_symbols:
                continue
            processed_symbols.add(symbol)

            state = self._get_trade_state(symbol)

            # 모든 step: 현재가 조회 및 분석(update_price)
            self.update_price(symbol, now, name=name)
            step = state.step

            if step == TradeStep.ORDER_BUY:
                # step1: 매수 가능 확인 (매수 주문 후 step2)
                self._process_step_order_buy(symbol, name)
            elif step == TradeStep.CHECK_BUY:
                # step2: 체결 확인 자리(현재는 step3으로 패스)
                self._process_step_buy_check(symbol, name)
            elif step == TradeStep.ORDER_SELL:
                # step3: 매도 가능 확인 (매도 주문 후 step4)
                self._process_order_sell(symbol, name)
            elif step == TradeStep.CHECK_SELL:
                # step4: 체결 확인 자리(현재는 step1으로 패스)
                self._process_step_sell_check(symbol, name)
            else:
                state.step = TradeStep.ORDER_BUY

        self.loop_count += 1
        if self.loop_count % 60 == 0:
            self.price_analysis.save_cache()

    def get_dashboard_snapshot(self):
        symbol_to_name = {}
        watch_symbols = []
        watch_symbol_set = set()
        for item in self.monitor_list:
            symbol = self._stock_symbol(item)
            if not symbol:
                continue
            symbol_to_name[symbol] = self._stock_name(item)
            if symbol not in watch_symbol_set:
                watch_symbols.append(symbol)
                watch_symbol_set.add(symbol)

        watch_rows = []
        for symbol in watch_symbols:
            item = self.price_analysis.items.get(symbol)
            current_price = None
            candle_count = 0
            buy_recommended = False
            sell_recommended = False
            stop_loss_recommended = False
            if item is not None and item.candle_stick_5minute:
                candle_count = len(item.candle_stick_5minute)
                current_price = item.candle_stick_5minute[-1].close_price
                buy_recommended = self.price_analysis.is_purchase_recommended(symbol)

                inventory = self.auth.account.stocks_by_symbol.get(symbol)
                if inventory is not None:
                    purchase_price = float(inventory['pchs_avg_pric'])
                    sell_recommended = self.price_analysis.is_sell_recommended(symbol, purchase_price)
                    stop_loss_recommended = self.price_analysis.is_sell_stop_loss_recommended(symbol, purchase_price)

            watch_rows.append({
                "symbol": symbol,
                "name": symbol_to_name.get(symbol, symbol),
                "price": current_price,
                "candles": candle_count,
                "buy": buy_recommended,
                "sell": sell_recommended,
                "stop": stop_loss_recommended,
                "step": self._get_trade_state(symbol).step.name,
            })

        holdings_rows = []
        for stock in self.auth.account.stocks:
            symbol = stock.get('pdno', '')
            quantity = int(stock.get('hldg_qty', 0))
            purchase_price = float(stock.get('pchs_avg_pric', 0))
            current_price = None
            if symbol in self.price_analysis.items and self.price_analysis.items[symbol].candle_stick_5minute:
                current_price = self.price_analysis.items[symbol].candle_stick_5minute[-1].close_price

            profit_rate = None
            if current_price is not None and purchase_price > 0:
                profit_rate = ((current_price - purchase_price) / purchase_price) * 100

            holdings_rows.append({
                "symbol": symbol,
                "name": stock.get('prdt_name', symbol),
                "qty": quantity,
                "purchase": purchase_price,
                "current": current_price,
                "profit_rate": profit_rate,
            })

        return {
            "market_open": self.is_market_open(),
            "loop_count": self.loop_count,
            "account": {
                "cash": self.auth.account.dnca_tot_amt,
                "d1": self.auth.account.nxdy_excc_amt,
                "d2": self.auth.account.prvs_rcdl_excc_amt,
            },
            "watch": watch_rows,
            "holdings": holdings_rows,
            "timestamp": time.time(),
        }

    def place_manual_buy(self, symbol: str, quantity: int):
        if quantity <= 0:
            raise ValueError("수량은 1 이상이어야 합니다.")
        if not self.is_market_open():
            raise ValueError("장외 시간에는 주문할 수 없습니다.")

        if symbol in self.price_analysis.items and self.price_analysis.items[symbol].candle_stick_5minute:
            price = self.price_analysis.items[symbol].candle_stick_5minute[-1].close_price
        else:
            price = self.update_price(symbol, force=True)
            if price is None:
                raise RuntimeError("현재가를 가져오지 못해 주문할 수 없습니다.")

        result = self.buy(symbol, quantity, price)
        self.update_account_stock()
        return result

    def place_manual_sell(self, symbol: str, quantity: int):
        if quantity <= 0:
            raise ValueError("수량은 1 이상이어야 합니다.")
        if not self.is_market_open():
            raise ValueError("장외 시간에는 주문할 수 없습니다.")

        inventory = self.auth.account.stocks_by_symbol.get(symbol)
        if inventory is None:
            raise ValueError("보유하지 않은 종목입니다.")

        holding_qty = int(inventory.get('hldg_qty', 0))
        if quantity > holding_qty:
            raise ValueError(f"보유 수량({holding_qty})을 초과하여 매도할 수 없습니다.")

        if symbol in self.price_analysis.items and self.price_analysis.items[symbol].candle_stick_5minute:
            price = self.price_analysis.items[symbol].candle_stick_5minute[-1].close_price
        else:
            price = self.update_price(symbol, force=True)
            if price is None:
                raise RuntimeError("현재가를 가져오지 못해 주문할 수 없습니다.")

        result = self.sell(symbol, quantity, price)
        self.update_account_stock()
        return result

    def update_sell_list(self):
        self.update_account_stock()

        # self.kosdq_monitor_list에 매도 리스트 업데이트
        self.monitor_list = []
        monitor_symbols = set()
        # 먼저 매수 리스트에 있는 종목들을 모니터링 리스트에 추가
        for item in self.buy_list:
            self.monitor_list.append(item)
            symbol = self._stock_symbol(item)
            if symbol:
                monitor_symbols.add(symbol)

        # 재고로 가지고 있는 건 모두 모니터링 리스트에 추가
        for stock in self.auth.account.stocks:
            symbol = stock.get('pdno', '')
            if symbol and symbol not in monitor_symbols:
                self.monitor_list.append(stock)
                monitor_symbols.add(symbol)

    def update_account_stock(self):
        while True:
            try:
                self.auth.account.update_stock()
                break
            except Exception as e:
                self.log(f"계좌 정보 업데이트 실패: {e}")
                time.sleep(1)  # 잠시 대기 후 재시도
                continue

    def buy(self, symbol: str, quantity: int, price: int):
        """현금 매수 주문"""
        try:
            return self.auth.order.buy_order_cash(symbol, quantity, price)
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

    def sell(self, symbol: str, quantity: int, price: int):
        """현금 매도 주문"""
        while True:
            try:
                return self.auth.order.sell_order_cash(symbol, quantity, price)
            except Exception as e:
                self.log(f"매도 주문 실패: {e}")
                time.sleep(1)  # 잠시 대기 후 재시도
                continue
    
    def immediately_sell(self, symbol: str, quantity: int):
        """즉시 매도 주문 (시장가)"""
        while True:
            try:
                result = self.auth.order.immediately_sell(symbol, quantity)
                self.update_sell_list()
                return result
            except Exception as e:
                self.log(f"즉시 매도 주문 실패: {e}")
                time.sleep(1)  # 잠시 대기 후 재시도
                continue

if __name__ == "__main__":
    bot = DayTradingBot()
    bot.run()
