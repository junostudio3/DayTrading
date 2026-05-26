from typing import Optional
from common_structure import SymbolItem
from telegram import Telegram
from api.kis_user import KisUser


class TradeBotSwing:
    def __init__(self, parent, user: KisUser):
        self.parent = parent
        self.log = parent.log
        self.trade_log = parent.trade_log
        self.user = user
        self.auth = user.auth
        self.app_id = user.app_id

        self.loop_count = 0
        self.notified_sell_candidates = set()
        self.monitor_list: list[SymbolItem] = []

        self.update_monitoring_list()

    def set_logger(self, log):
        self.log = log

    def set_trade_logger(self, log):
        self.trade_log = log

    def update_balance(self, retry_count: int = 5):
        return self.auth.update_balance(logger=self.log, retry_count=retry_count)

    def display_account_info(self):
        self.log("Swing 봇 주식 잔고:")
        if not self.auth.portfolio.stocks:
            self.log("보유 주식이 없습니다.")
        else:
            for stock in self.auth.portfolio.stocks:
                # 단타 봇이 관리하지 않는 종목만
                if self.parent.daily.is_managing_pdno(self.app_id, stock['pdno']):
                    continue
                self.log(f"Swing 대상 - 종목번호: {stock['pdno']} {stock['prdt_name']}, 보유수량: {stock['hldg_qty']}, 매입평균가: {stock['pchs_avg_pric']}")

    def update_monitoring_list(self):
        new_list = []
        stocks_list = self.parent.swing.watchlist.get_stocks()
        for watchlist_item in stocks_list:
            if not any(x.pdno == watchlist_item.pdno for x in new_list):
                new_list.append(SymbolItem(watchlist_item.pdno, watchlist_item.prdt_name))

        self.monitor_list = new_list

    def process_once(self, now: float):
        self.loop_count += 1
        
        self.update_monitoring_list()

        # 현재 주기적인 체결 잔고 동기화는 단타봇이 진행하므로 생략
        for symbol_item in self.monitor_list:
            self._process_step_judge(symbol_item, now)

    def _find_inventory(self, pdno: str):
        return self.auth.portfolio.stocks_by_pdno.get(pdno)

    def _process_step_judge(self, symbol_item: SymbolItem, now: float):
        pdno = symbol_item.pdno
        inventory = self._find_inventory(pdno)

        current_price = None
        if pdno in self.parent.price_analysis.items and self.parent.price_analysis.items[pdno].candle_stick_5minute:
            current_price = self.parent.price_analysis.items[pdno].candle_stick_5minute[-1].close_price

        if current_price is None:
            return

        # 30일 이평선
        avg_30d = None
        for retry in range(3):
            try:
                avg_30d = self.parent.market_data_service.get_average_price_30day(pdno)
                break
            except Exception as e:
                if retry == 2:
                    self.parent.log(f"종목 {pdno}의 30일 평균가 조회 실패: {e}")
                    return

        if avg_30d is None or avg_30d <= 0:
            return

        if inventory is not None:
            # 매도 권장 모니터링 #1 (다음의 조건 모두 만족 시 매도 권장)
            # : 가격이 30일 이평선 밑으로 떨어지면 알림
            # : 가격이 5% 이상 하락하면 알림
            pchs_avg_pric: float = float(inventory.get('pchs_avg_pric'))
            if current_price < avg_30d and current_price < pchs_avg_pric * 0.95:
                if pdno not in self.notified_sell_candidates:
                    msg = f"📉 [Swing 매도 권장] {symbol_item.prdt_name}({pdno})\n현재가({current_price})가 30일 평균가({avg_30d})를 하회했고 구매 당시보다 5%이상 하락 했습니다."
                    Telegram.send_message(msg)
                    self.notified_sell_candidates.add(pdno)

            if current_price > pchs_avg_pric * 1.10:
                if pdno not in self.notified_sell_candidates:
                    msg = f"📈 [Swing 매도 권장] {symbol_item.prdt_name}({pdno})\n현재가({current_price})가 구매 당시보다 10%이상 상승 했습니다."
                    Telegram.send_message(msg)
                    self.notified_sell_candidates.add(pdno)

    def place_manual_buy(self, pdno: str, quantity: int, input_price: int = None):
        if quantity <= 0:
            raise ValueError("수량은 1 이상이어야 합니다.")
        
        symbol_item = self.parent.price_analysis.items[pdno].symbol_item
        if input_price:
            price = input_price
        else:
            price = self.parent.price_analysis.items[pdno].candle_stick_5minute[-1].close_price

        result = self.auth.order.buy_order_cash(symbol_item.pdno, quantity, price)
        self.update_balance()
        return result

    def place_manual_sell(self, pdno: str, quantity: int, input_price: int = None):
        if quantity <= 0:
            raise ValueError("수량은 1 이상이어야 합니다.")
        
        symbol_item = self.parent.price_analysis.items[pdno].symbol_item
        if input_price:
            price = input_price
        else:
            price = self.parent.price_analysis.items[pdno].candle_stick_5minute[-1].close_price

        return self.auth.order.sell_order_cash(symbol_item.pdno, quantity, price)

    def get_dashboard_snapshot(self) -> Optional[dict]:
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
                "step": "-",
            })

        return {
            "swing_watch": watch_rows
        }