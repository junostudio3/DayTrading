from api.kis_user import KisUser
from trade_bot_daily import TradeBotDaily
from watchlist import Watchlist

class TradeBotDailyComm:
    def __init__(self, parent):
        self.parent = parent
        self.watchlist = Watchlist("./cache/watchlist.json")
        self.bots: dict[str, TradeBotDaily] = {}
        # app_id 별로 봇이 몇 번 프로세스에 진입했는지 카운트하는 딕셔너리
        self.process_counters: dict[str, int] = {}

    def add_bot(self, user: KisUser):
        bot = TradeBotDaily(self.parent, user)
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

    def process_once(self, app_id: str, now: float):
        if app_id not in self.process_counters:
            self.process_counters[app_id] = 0
        self.process_counters[app_id] = (self.process_counters[app_id] + 1) % 20

        bot = self.bots.get(app_id)
        if bot:
            if self.process_counters[app_id] == 0:
                # 수동 매수/매도가 있었을 수 있으므로
                # 20회에 한 번씩 계좌 업데이트를 하자
                bot.update_portfolio()
            bot.process_once(now)
