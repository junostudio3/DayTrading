from api.kis_user import KisUser
from common_structure import SymbolItem
from trade_bot_swing import TradeBotSwing
from swing_watchlist import SwingWatchlist


class TradeBotSwingComm:
    def __init__(self):
        self.watchlist = SwingWatchlist("./cache/swing_watchlist.json")
        self.bots: dict[str, TradeBotSwing] = {}
        # app_id 별로 스윙 봇이 몇 번 프로세스에 진입했는지 카운트하는 딕셔너리
        self.swing_process_counters: dict[str, int] = {}

    def add_bot(self, parent, user: KisUser):
        bot = TradeBotSwing(parent, user)
        self.bots[user.app_id] = bot

    def check_stock(self, item: SymbolItem):
        pass # 아직 작업되지 않음

    def manual_buy(self, app_id: str, pdno: str, quantity: int):
        bot = self.bots.get(app_id)
        if bot:
            return bot.place_manual_buy(pdno, quantity)
        else:
            raise Exception(f"Bot with app_id {app_id} not found")
    
    def manual_sell(self, app_id: str, pdno: str, quantity: int):
        bot = self.bots.get(app_id)
        if bot:
            return bot.place_manual_sell(pdno, quantity)
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