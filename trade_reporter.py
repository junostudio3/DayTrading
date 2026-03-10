from day_trading_bot import DayTradingBot
from symbol_item import SymbolItem
import time

class TradeReporter:
    def __init__(self, bot: DayTradingBot):
        self.bot = bot

    def add_buy_order(self, symbol_item: SymbolItem, quantity: int, price: int):
        text = f"매수 주문 / 수량: {quantity} / 가격: {price}"
        self._add_log(symbol_item, text)

    def add_buy_order_cncelled(self, symbol_item: SymbolItem, text: str):
        text = f"매수 주문 취소 / 사유: {text}"
        self._add_log(symbol_item, text)
        
    def add_buy_order_completed(self, symbol_item: SymbolItem):
        text = f"[매수 체결"
        self._add_log(symbol_item, text)

    def add_sell_order(self, symbol_item: SymbolItem, quantity: int, price: int):
        text = f"매도 주문 / 수량: {quantity} / 가격: {price}"
        self._add_log(symbol_item, text)

    def add_immediate_sell_order(self, symbol_item: SymbolItem, quantity: int, current_price: int):
        text = f"즉시 매도 주문 / 수량: {quantity} / 가격: 시장가 (모니터링된 가격: {current_price})"
        self._add_log(symbol_item, text)

    def add_sell_order_cancelled(self, symbol_item: SymbolItem, text: str):
        text = f"매도 주문 취소 / 사유: {text}"
        self._add_log(symbol_item, text)
  
    def add_sell_order_completed(self, symbol_item: SymbolItem):
        text = f"매도 체결"
        self._add_log(symbol_item, text)

    def _add_log(self, symbol_item: SymbolItem, text: str):
        text = f"[{symbol_item.pdno} {symbol_item.prdt_name}] {text}"
        trade_log = getattr(self.bot, "trade_log", None)
        if callable(trade_log):
            trade_log(text)
        else:
            self.bot.log(text)

        # ./report/ 폴더에 거래 기록을 텍스트 파일의 끝에 추가한다. (파일명: YYYY-MM-DD.txt)
        date_str = time.strftime("%Y-%m-%d", time.localtime())
        log_file_path = f"./report/{date_str}.txt"
        try:
            with open(log_file_path, "a", encoding="utf-8") as f:
                timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
                f.write(f"[{timestamp}] {text}\n")
        except Exception as e:
            print(f"Failed to write trade log to {log_file_path}: {e}")

