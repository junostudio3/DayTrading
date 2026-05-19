from api.kis_user import KisUser
from common_structure import SymbolItem
from filter import SymbolFilter
from price_day_chat import PriceDayChat
from trade_bot_swing_watchlist import SwingWatchlist
from telegram import Telegram
from trade_bot_swing import TradeBotSwing
import time


class TradeBotSwingComm:
    def __init__(self, parent):
        from trade_bot import TradeBot
        self.parent: TradeBot = parent
        self.market_data_service = parent.market_data_service
        self.price_day_chat = PriceDayChat(self.market_data_service)
        self.watchlist = SwingWatchlist("./cache/swing_watchlist.json")
        self.bots: dict[str, TradeBotSwing] = {}
        # app_id 별로 스윙 봇이 몇 번 프로세스에 진입했는지 카운트하는 딕셔너리
        self.swing_process_counters: dict[str, int] = {}

    def add_bot(self, user: KisUser):
        bot = TradeBotSwing(self.parent, user)
        self.bots[user.app_id] = bot

    def check_stock(self, item: SymbolItem):
        if self.watchlist.is_existing(item.pdno):
            # 이미 모니터링 종목이므로 넘어감
            return
        
        if SymbolFilter.is_not_watched_by_name(item.prdt_name):
            # 이름 필터에 걸리는 종목이므로 넘어감
            return
        
        ind = self.price_day_chat.get_past_swing_indicators(item.pdno, time.time())
        if not ind.valid:
            # 30일치 일봉 등 데이터 부족시 모니터링 제외
            return

        for retry in range(3):
            try:
                current_price, current_volume = self.market_data_service.get_current_price_and_accumulated_volume(item.pdno)
                break
            except Exception as e:
                self.parent.log(f"종목 {item.pdno}의 현재가/거래량 조회 실패: {e}")
                if retry == 2:
                    return
        
        # 매수 후보 발굴 모니터링
        is_break_30d = current_price > ind.avg_30d
        is_trend_up = ind.avg_5d > ind.avg_20d
        is_volume_burst = current_volume > (ind.avg_vol_5d * 2.0)

        # 3조건 모두 만족 시 추천
        if is_break_30d and is_trend_up and is_volume_burst:
            if self.watchlist.update_stock(item.pdno, item.prdt_name, current_price, current_volume):
                msg = (f"📈 [Swing 추천] {item.prdt_name}({item.pdno})\n"
                       f"• 현재가: {current_price} 돌파 (5선 {ind.avg_5d:.0f} / 20선 {ind.avg_20d:.0f} / 30선 {ind.avg_30d:.0f})\n"
                       f"• 조건: 30선 돌파 & 상승 추세 & 거래량 2배 급증")
                Telegram.send_message(msg)

    def manual_buy(self, app_id: str, pdno: str, quantity: int, price: int = None):
        bot = self.bots.get(app_id)
        if bot:
            return bot.place_manual_buy(pdno, quantity, price)
        else:
            raise Exception(f"Bot with app_id {app_id} not found")
    
    def manual_sell(self, app_id: str, pdno: str, quantity: int, price: int = None):
        bot = self.bots.get(app_id)
        if bot:
            return bot.place_manual_sell(pdno, quantity, price)
        else:
            raise Exception(f"Bot with app_id {app_id} not found")

    def process_once(self, app_id: str, now: float):
        if app_id not in self.swing_process_counters:
            self.swing_process_counters[app_id] = 0

        self.swing_process_counters[app_id] = (self.swing_process_counters[app_id] + 1) % 20
        # 스윙 봇은 20회마다 한 번씩 프로세스에 진입하도록 하자
        if self.swing_process_counters[app_id] != 0:
            return

        bot = self.bots.get(app_id)
        if bot:
            bot.process_once(now)

    def set_logger(self, log):
        for bot in self.bots.values():
            bot.set_logger(log)

    def set_trade_logger(self, log):
        for bot in self.bots.values():
            bot.set_trade_logger(log)

    def update_tick(self, seconds: float):
        self.watchlist.tick(seconds)

    def display_account_info(self):
        for bot in self.bots.values():
            bot.display_account_info()