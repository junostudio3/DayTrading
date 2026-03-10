from day_trading_bot import DayTradingBot
from trading_engine import TradingEngine
from day_trading_tui import DayTradingTUI


if __name__ == "__main__":
    bot = DayTradingBot()
    engine = TradingEngine(bot, interval_seconds=1)
    app = DayTradingTUI(engine)
    app.run()
