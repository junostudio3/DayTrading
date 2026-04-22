from common_structure import AccountBalance
from common_structure import SymbolItem
import time
import os
from enum import Enum, auto
from filter import TradingParams
from telegram import Telegram

class TradeType(Enum):
    BUY = auto()
    BUY_CANCELLED = auto()
    BUY_COMPLETED = auto()
    SELL = auto()
    IMMEDIATE_SELL = auto()
    SELL_CANCELLED = auto()
    SELL_COMPLETED = auto()
    UNKNOWN_ERROR = auto()

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
        elif self == TradeType.UNKNOWN_ERROR:
            return "알 수 없는 거래 오류"
        else:
            return "알 수 없는 거래 유형"


class TradeReporter:
    def __init__(self, bot):
        self.bot = bot
        self.bot_parent = self.bot.parent
        self.account_balance: AccountBalance = None

        # app_id 별로 ./report/ 폴더 아래에 리포트 파일을 저장하기 위한 폴더 생성
        self.app_id = self.bot.app_id
        self.base_folder = f"./report/{self.app_id}"
        if not os.path.exists(self.base_folder):
            os.makedirs(self.base_folder)

    def set_account_balance(self, account_balance: AccountBalance):
        self.account_balance = account_balance

    def add(self, trade_type: TradeType, symbol_item: SymbolItem, quantity: int, price: int, text: str = ""):
        log_text = trade_type.get_kr_text()
        quantity_text = f"이미 체결된 수량: {quantity}" if trade_type in [TradeType.BUY_CANCELLED, TradeType.SELL_CANCELLED] else f"수량: {quantity}"
        log_text = f"{log_text} / {quantity_text} / 가격: {price}"
        
        # 특정 거래 유형에서 기술적 지표를 리포트에 추가
        if trade_type in [TradeType.BUY, TradeType.SELL, TradeType.IMMEDIATE_SELL]:
            # self.bot_parent.price_analysis.items에서 현재 지표 추출
            if symbol_item.pdno in self.bot_parent.price_analysis.items:
                p_item = self.bot_parent.price_analysis.items[symbol_item.pdno]
                indicators = p_item.get_current_indicators()
                if indicators:
                    ind_strs = []
                    for k, v in indicators.items():
                        if v is not None:
                            ind_strs.append(f"{k}:{v}")
                    if ind_strs:
                        log_text += f" / 지표: [{', '.join(ind_strs)}]"

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
        log_file_path = os.path.join(self.base_folder, f"{date_str}.txt")
        try:
            is_new_file = not os.path.exists(log_file_path)
            with open(log_file_path, "a", encoding="utf-8") as f:
                if is_new_file:
                    f.write(TradingParams.to_report_header() + "\n\n")
                timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
                if self.account_balance is None:
                    f.write(f"[{timestamp}] {text}\n")
                else:
                    f.write(f"[{timestamp}] [{self.account_balance.tot_evlu_amt}] / {text}\n")
                    
            # 텔레그램 알림 전송 (정상 기록된 경우)
            balance_str = self.account_balance.tot_evlu_amt if self.account_balance else "N/A"
            Telegram.send_message(f"🔔 <b>[거래 발생] {self.app_id}</b>\n[잔고: {balance_str}]\n{text}")
                    
        except Exception as e:
            print(f"Failed to write trade log to {log_file_path}: {e}")

