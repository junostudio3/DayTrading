from DayTradingBot import DayTradingBot
from trading_engine import TradingEngine
from tui_app import DayTradingTUI


if __name__ == "__main__":
    bot = DayTradingBot()
    engine = TradingEngine(bot, interval_seconds=3)
    app = DayTradingTUI(engine)
    app.run()
