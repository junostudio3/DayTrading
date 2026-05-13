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

    def is_managing_pdno(self, app_id: str, pdno: str) -> bool:
        # 단타 봇이 관리하는 종목인지 확인
        bot = self.bots.get(app_id)
        if bot and pdno in bot.bot_purchased_pdnos:
            return True
        return False