from DayTradingBot import DayTradingBot
from TradingEngine import TradingEngine
from DayTradingTUI import DayTradingTUI


if __name__ == "__main__":
    bot = DayTradingBot()
    engine = TradingEngine(bot, interval_seconds=1)
    app = DayTradingTUI(engine)
    app.run()
