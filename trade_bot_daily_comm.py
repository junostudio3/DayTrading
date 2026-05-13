from api.kis_user import KisUser
from trade_bot_daily import TradeBotDaily
from watchlist import Watchlist

class TradeBotDailyComm:
    def __init__(self):
        self.watchlist = Watchlist("./cache/watchlist.json")
        self.bots: dict[str, TradeBotDaily] = {}

    def add_bot(self, parent, user: KisUser):
        bot = TradeBotDaily(parent, user)
        self.bots[user.app_id] = bot
    
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