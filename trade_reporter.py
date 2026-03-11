from common_structure import AccountBalance
from common_structure import SymbolItem
import time
from enum import Enum, auto

class TradeType(Enum):
    BUY = auto()
    BUY_CANCELLED = auto()
    BUY_COMPLETED = auto()
    SELL = auto()
    IMMEDIATE_SELL = auto()
    SELL_CANCELLED = auto()
    SELL_COMPLETED = auto()

    def get_kr_text(self):
        if self == TradeType.BUY:
            return "매수 주문"
        elif self == TradeType.BUY_CANCELLED:
            return "매수 주문 취소"
        elif self == TradeType.BUY_COMPLETED:
            return "매수 체결"
        elif self == TradeType.SELL:
            return "매도 주문"
        elif self == TradeType.IMMEDIATE_SELL:
            return "즉시 매도 주문"
        elif self == TradeType.SELL_CANCELLED:
            return "매도 주문 취소"
        elif self == TradeType.SELL_COMPLETED:
            return "매도 체결"
        else:
            return "알 수 없는 거래 유형"


class TradeReporter:
    def __init__(self, bot):
        self.bot = bot
        self.account_balance: AccountBalance = None

    def set_account_balance(self, account_balance: AccountBalance):
        self.account_balance = account_balance

    def add(self, trade_type: TradeType, symbol_item: SymbolItem, quantity: int, price: int, text: str = ""):
        log_text = trade_type.get_kr_text()
        quantity_text = f"이미 체결된 수량: {quantity}" if trade_type in [TradeType.BUY_CANCELLED, TradeType.SELL_CANCELLED] else f"수량: {quantity}"
        log_text = f"{log_text} / {quantity_text} / 가격: {price}"
        if text:
            log_text += f" / 사유: {text}"
        self._add_log(symbol_item, log_text)

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
                if self.account_balance is None:
                    f.write(f"[{timestamp}] {text}\n")
                else:
                    f.write(f"[{timestamp}] [{self.account_balance.dnca_tot_amt} / D+1: {self.account_balance.nxdy_excc_amt} / D+2: {self.account_balance.prvs_rcdl_excc_amt}] / {text}\n")
        except Exception as e:
            print(f"Failed to write trade log to {log_file_path}: {e}")

