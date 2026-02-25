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
from typing import Any, Optional

class DayTradingBot:
    def __init__(self):
        kosdq_records = load_kosdaq_master()

        # 관심 종목을 리스트로 수집
        kospi_wish_names = []
        kospi_wish_names += ["대한항공"]

        kosdq_wish_names = []
        kosdq_wish_names += ["인텍플러스", "고영", "펨트론"]

        self.monitor_list = []
        self.buy_list = []

        # 관심 종목 정보 수집
        for name in kospi_wish_names:
            results = find_kospi_by_name(name, load_kospi_master())
            if results is None or len(results) == 0:
                print(f"{name} 종목을 찾을 수 없습니다.")
                exit(1)
            else:
                self.buy_list.append(results[0])
                self.monitor_list.append(results[0])

        for name in kosdq_wish_names:
            results = find_kosdaq_by_name(name, kosdq_records)
            if results is None or len(results) == 0:
                print(f"{name} 종목을 찾을 수 없습니다.")
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

        # 아이템 별로 30일 평균가 조회
        #for stock in self.kosdq_buy_list:
        #    price = self.auth.price.get_average_price_30day(stock.mksc_shrn_iscd)
        #    print(f"관심 종목: [{stock.mksc_shrn_iscd}] {stock.hts_kor_isnm} / 30일 평균가: {price}")

    def run(self):
        # QLD ETF의 현재가 조회 (미국 주식 예시)
        #price = auth.price.get_current_overseas("QLD", "AMS")
        #print(f"QLD 현재가: {price}")

        self.display_account_info()
        while True:
            self.process_once()
            time.sleep(1)

    def display_account_info(self):
        print(f"예수금: {self.auth.account.dnca_tot_amt}")
        print(f"D+1 예수금: {self.auth.account.nxdy_excc_amt}")
        print(f"D+2 예수금: {self.auth.account.prvs_rcdl_excc_amt}")
        print("주식 잔고:", end=" ")
        if not self.auth.account.stocks:
            print("보유 주식이 없습니다.")
        else:
            for stock in self.auth.account.stocks:
                print(f"종목번호: {stock['pdno']}, 보유수량: {stock['hldg_qty']}, 매입평균가: {stock['pchs_avg_pric']}")

    def update_price(self, symbol: str):
        """단일 종목의 현재가 조회"""
        error_count = 0
        while error_count < 5:
            try:
                price = self.auth.price.get_current(symbol)
                break
            except Exception as e:
                error_count += 1
                if error_count >= 5:
                    print(f"Error fetching current price for {symbol} after 5 attempts: {e}")
                    return None

                time.sleep(1)  # 잠시 대기 후 재시도
                continue

        self.price_analysis.add_price(symbol, price)
        print(f"관심 종목: [{symbol}] / 현재가: {price}")
        return price

    def _stock_symbol(self, stock: Any) -> str:
        if isinstance(stock, dict):
            return stock.get('pdno', '')
        return getattr(stock, 'mksc_shrn_iscd', '')

    def _stock_name(self, stock: Any) -> str:
        if isinstance(stock, dict):
            return stock.get('prdt_name', stock.get('pdno', ''))
        return getattr(stock, 'hts_kor_isnm', self._stock_symbol(stock))

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
                    print("장이 쉬는 날입니다. 토요일과 일요일에는 동작하지 않습니다.")
                else:
                    print("장외 시간입니다. 9:00 ~ 15:30 사이에만 동작합니다.")
                self.price_analysis.save_cache()

            self.is_running = False
            return

        self.is_running = True
        self.auth.account.update_stock()

        # 관심 종목들 현재가 조회 및 분석
        for stock in self.monitor_list:
            symbol = self._stock_symbol(stock)
            if not symbol:
                continue
            self.update_price(symbol)

        # 관심 종목들 중 매수 추천이 있는 종목이 있는지 확인
        for stock in self.monitor_list:
            symbol = self._stock_symbol(stock)
            name = self._stock_name(stock)
            if not symbol:
                continue

            inventory = next((s for s in self.auth.account.stocks if s['pdno'] == symbol), None)
            if inventory is not None:
                continue  # 이미 재고가 있는 종목은 패스

            if self.price_analysis.is_purchase_recommended(symbol) is False:
                continue  # 매수 추천이 없는 종목은 패스

            if symbol not in self.price_analysis.items or not self.price_analysis.items[symbol].candle_stick_5minute:
                continue

            max_budget = 1000000  # 최대 투자 금액 (예: 100만원)
            current_price = self.price_analysis.items[symbol].candle_stick_5minute[-1].close_price
            quantity = int(max_budget // current_price)  # 최대 투자 금액으로 살 수 있는 수량 계산
            if quantity <= 0:
                continue

            # 구매
            self.buy(symbol, quantity, current_price)
            print(f"매수 주문: [{symbol}] {name} / 수량: {quantity} / 가격: {current_price}")
            self.auth.account.update_stock()

        # 관심 종목중 매도가 필요한 종목이 있는지 확인
        for stock in self.monitor_list:
            symbol = self._stock_symbol(stock)
            name = self._stock_name(stock)
            if not symbol:
                continue

            # 재고가 없는 종목은 패스
            inventory = next((s for s in self.auth.account.stocks if s['pdno'] == symbol), None)
            if inventory is None:
                continue

            # 매입가격
            purchase_price = float(inventory['pchs_avg_pric'])
            # 매입수량
            quantity = int(inventory['hldg_qty'])

            # 손절 추천이 있는 종목은 바로 매도
            if self.price_analysis.is_sell_stop_loss_recommended(symbol, purchase_price):
                current_price = self.price_analysis.items[symbol].candle_stick_5minute[-1].close_price if symbol in self.price_analysis.items and self.price_analysis.items[symbol].candle_stick_5minute else 0
                print(f"손절 추천: [{symbol}] {name} / 구매가: {purchase_price} / 현재가: {current_price}")
                self.immediately_sell(symbol, quantity)
                continue

            # 매도 추천이 없는 종목은 패스
            if not self.price_analysis.is_sell_recommended(symbol, purchase_price):
                continue

            if symbol not in self.price_analysis.items or not self.price_analysis.items[symbol].candle_stick_5minute:
                continue
            current_price = self.price_analysis.items[symbol].candle_stick_5minute[-1].close_price
            self.sell(symbol, quantity, current_price)
            print(f"매도 주문: [{symbol}] {name} / 수량: {quantity} / 가격: {current_price}")
            self.auth.account.update_stock()

        self.loop_count += 1
        if self.loop_count % 60 == 0:
            self.price_analysis.save_cache()

    def get_dashboard_snapshot(self):
        symbol_to_name = {}
        watch_symbols = []
        for item in self.monitor_list:
            symbol = self._stock_symbol(item)
            if not symbol:
                continue
            symbol_to_name[symbol] = self._stock_name(item)
            if symbol not in watch_symbols:
                watch_symbols.append(symbol)

        watch_rows = []
        for symbol in watch_symbols:
            item = self.price_analysis.items.get(symbol)
            current_price = None
            buy_recommended = False
            sell_recommended = False
            stop_loss_recommended = False
            if item is not None and item.candle_stick_5minute:
                current_price = item.candle_stick_5minute[-1].close_price
                buy_recommended = self.price_analysis.is_purchase_recommended(symbol)

                inventory = next((s for s in self.auth.account.stocks if s['pdno'] == symbol), None)
                if inventory is not None:
                    purchase_price = float(inventory['pchs_avg_pric'])
                    sell_recommended = self.price_analysis.is_sell_recommended(symbol, purchase_price)
                    stop_loss_recommended = self.price_analysis.is_sell_stop_loss_recommended(symbol, purchase_price)

            watch_rows.append({
                "symbol": symbol,
                "name": symbol_to_name.get(symbol, symbol),
                "price": current_price,
                "buy": buy_recommended,
                "sell": sell_recommended,
                "stop": stop_loss_recommended,
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
            price = self.update_price(symbol)
            if price is None:
                raise RuntimeError("현재가를 가져오지 못해 주문할 수 없습니다.")

        result = self.buy(symbol, quantity, price)
        self.auth.account.update_stock()
        return result

    def place_manual_sell(self, symbol: str, quantity: int):
        if quantity <= 0:
            raise ValueError("수량은 1 이상이어야 합니다.")
        if not self.is_market_open():
            raise ValueError("장외 시간에는 주문할 수 없습니다.")

        inventory = next((s for s in self.auth.account.stocks if s['pdno'] == symbol), None)
        if inventory is None:
            raise ValueError("보유하지 않은 종목입니다.")

        holding_qty = int(inventory.get('hldg_qty', 0))
        if quantity > holding_qty:
            raise ValueError(f"보유 수량({holding_qty})을 초과하여 매도할 수 없습니다.")

        if symbol in self.price_analysis.items and self.price_analysis.items[symbol].candle_stick_5minute:
            price = self.price_analysis.items[symbol].candle_stick_5minute[-1].close_price
        else:
            price = self.update_price(symbol)
            if price is None:
                raise RuntimeError("현재가를 가져오지 못해 주문할 수 없습니다.")

        result = self.sell(symbol, quantity, price)
        self.auth.account.update_stock()
        return result

    def update_sell_list(self):
        self.auth.account.update_stock()

        # self.kosdq_monitor_list에 매도 리스트 업데이트
        self.monitor_list = []
        # 먼저 매수 리스트에 있는 종목들을 모니터링 리스트에 추가
        for item in self.buy_list:
            self.monitor_list.append(item)

        # 재고로 가지고 있는 건 모두 모니터링 리스트에 추가
        for stock in self.auth.account.stocks:
            if stock['pdno'] not in [self._stock_symbol(item) for item in self.monitor_list]:
                self.monitor_list.append(stock)
                

    def buy(self, symbol: str, quantity: int, price: float):
        """현금 매수 주문"""
        while True:
            try:
                return self.auth.order.buy_order_cash(symbol, quantity, price)
            except Exception as e:
                print(f"매수 주문 실패: {e}")
                time.sleep(1)  # 잠시 대기 후 재시도
                continue

    def sell(self, symbol: str, quantity: int, price: float):
        """현금 매도 주문"""
        while True:
            try:
                return self.auth.order.sell_order_cash(symbol, quantity, price)
            except Exception as e:
                print(f"매도 주문 실패: {e}")
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
                print(f"즉시 매도 주문 실패: {e}")
                time.sleep(1)  # 잠시 대기 후 재시도
                continue

if __name__ == "__main__":
    bot = DayTradingBot()
    bot.run()
