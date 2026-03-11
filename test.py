from day_trading_bot import DayTradingBot

def test_day_trading_bot():
    # DayTradingBot 인스턴스 생성
    bot = DayTradingBot()

    # 구매 테스트
    #order = bot.buy("064290", 1, 16000)
    #print("매수 주문 결과:", order)

    # 구매 체크
    check_order_result = bot.check_order_completed("064290","0000006992", True)
    success = check_order_result.rmn_qty == 0
    print("매수 주문 체결 여부:", success)

if __name__ == "__main__":
    test_day_trading_bot()
