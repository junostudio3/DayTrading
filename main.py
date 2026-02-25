from KisAuth import KisAuth
from KisKey import app_account
from KisKey import app_domain
from KisKey import app_is_virtual
from KisKey import app_key
from KisKey import app_secret
from InfoKosdaq import find_by_name, load_kosdaq_master
from PriceAnalysis import PriceAnalysis
import time

class DayTradingBot:
    def __init__(self):
        kosdq_records = load_kosdaq_master()

        # 관심 종목을 리스트로 수집
        kosdq_wish_names = ["인텍플러스"]
        self.kosdq_monitor_list = []
        self.kosdq_buy_list = []

        # 관심 종목 정보 수집
        for name in kosdq_wish_names:
            results = find_by_name(name, kosdq_records)
            if results is None or len(results) == 0:
                print(f"{name} 종목을 찾을 수 없습니다.")
                exit(1)
            else:
                self.kosdq_buy_list.append(results[0])
                self.kosdq_monitor_list.append(results[0])

        self.auth = KisAuth(app_key, app_secret, app_account, app_is_virtual, app_domain)
        self.auth.account.update()
        self.update_sell_list()

        self.price_analysis = PriceAnalysis("./cache/price_analysis_cache.json")

        # 아이템 별로 30일 평균가 조회
        #for stock in self.kosdq_buy_list:
        #    price = self.auth.price.get_average_price_30day(stock.mksc_shrn_iscd)
        #    print(f"관심 종목: [{stock.mksc_shrn_iscd}] {stock.hts_kor_isnm} / 30일 평균가: {price}")

    def run(self):
        # QLD ETF의 현재가 조회 (미국 주식 예시)
        #price = auth.price.get_current_overseas("QLD", "AMS")
        #print(f"QLD 현재가: {price}")

        self.display_account_info()
        loop_count = 0

        while True:
            now = time.time()

            # 9:00 ~ 15:30 사이에만 동작하도록 설정
            if time.localtime(now).tm_hour < 9 or (time.localtime(now).tm_hour == 15 and time.localtime(now).tm_min > 30) or time.localtime(now).tm_hour > 15:
                # 장외 시간에는 동작하지 않음
                time.sleep(60)
                continue

            # 관심 종목들 현재가 조회 및 분석
            for stock in self.kosdq_monitor_list:
                self.update_price(stock.mksc_shrn_iscd)

            # 관심 종목들 중 매수 추천이 있는 종목이 있는지 확인
            for stock in self.kosdq_monitor_list:
                inventory = next((s for s in self.auth.account.stocks if s['pdno'] == stock.mksc_shrn_iscd), None)
                if inventory is not None:
                    continue  # 이미 재고가 있는 종목은 패스

                if self.price_analysis.is_purchase_recommended(stock.mksc_shrn_iscd) is False:
                    continue  # 매수 추천이 없는 종목은 패스

                max_budget = 1000000  # 최대 투자 금액 (예: 100만원)
                current_price = self.price_analysis.items[stock.mksc_shrn_iscd].candle_stick_5minute[-1].close_price
                quantity = int(max_budget // current_price)  # 최대 투자 금액으로 살 수 있는 수량 계산

                # 구매
                self.buy(stock.mksc_shrn_iscd, quantity, current_price)
                print(f"매수 주문: [{stock.mksc_shrn_iscd}] {stock.hts_kor_isnm} / 수량: {quantity} / 가격: {current_price}")
            
            # 관심 종목중 매도가 필요한 종목이 있는지 확인
            for stock in self.kosdq_monitor_list:
                # 재고가 없는 종목은 패스
                # self.auth.account.stocks 리스트중 ['pdno']가 stock.mksc_shrn_iscd인 항목을 찾는다
                inventory = next((s for s in self.auth.account.stocks if s['pdno'] == stock.mksc_shrn_iscd), None)
                if inventory is None:
                    continue

                # 매입가격
                purchase_price = float(inventory['pchs_avg_pric'])
                # 매입수량
                quantity = int(inventory['hldg_qty'])

                # 손절 추천이 있는 종목은 바로 매도
                if self.price_analysis.is_sell_stop_loss_recommended(stock.mksc_shrn_iscd, purchase_price):
                    print(f"손절 추천: [{stock.mksc_shrn_iscd}] {stock.hts_kor_isnm} / 구매가: {purchase_price} / 현재가: {self.price_analysis.items[stock.mksc_shrn_iscd].candle_stick_5minute[-1].close_price}")
                    self.immediately_sell(stock.mksc_shrn_iscd, quantity)
                    continue

                # 매도 추천이 없는 종목은 패스
                if not self.price_analysis.is_sell_recommended(stock.mksc_shrn_iscd, purchase_price):
                    continue

            # 1초마다 갱신
            time.sleep(1)
            loop_count += 1
            if loop_count % 60 == 0:
                # 1분마다 캐시 저장
                self.price_analysis.save_cache()

    def display_account_info(self):
        print(f"예수금: {self.auth.account.dnca_tot_amt}")
        print(f"D+1 예수금: {self.auth.account.nxdy_excc_amt}")
        print(f"D+2 예수금: {self.auth.account.prvs_rcdl_excc_amt}")
        print("주식 잔고:", end=" ")
        if not self.auth.account.stocks:
            print("보유 주식이 없습니다.")
        else:
            for stock in self.auth.account.stocks:
                print(f"종목번호: {stock['pdno']}, 보유수량: {stock['hldg_qty']}, 매입평균가: {stock['pchs_avg_pric']}")

    def update_price(self, symbol: str):
        """단일 종목의 현재가 조회"""
        error_count = 0
        while True:
            try:
                price = self.auth.price.get_current(symbol)
                break
            except Exception as e:
                if error_count >= 5:
                    print(f"Error fetching current price for {symbol} after 5 attempts: {e}")

                    time.sleep(1)  # 잠시 대기 후 재시도
                    continue

        self.price_analysis.add_price(symbol, price)
        print(f"관심 종목: [{symbol}] / 현재가: {price}")

    def update_sell_list(self):
        self.auth.account.update_stock()

        # self.kosdq_monitor_list에 매도 리스트 업데이트
        self.kosdq_monitor_list = []
        # 먼저 매수 리스트에 있는 종목들을 모니터링 리스트에 추가
        for item in self.kosdq_buy_list:
            self.kosdq_monitor_list.append(item)

        # 재고로 가지고 있는 건 모두 모니터링 리스트에 추가
        for stock in self.auth.account.stocks:
            if stock['pdno'] not in [item.mksc_shrn_iscd for item in self.kosdq_monitor_list]:
                self.kosdq_monitor_list.append(stock)
                

    def buy(self, symbol: str, quantity: int, price: float):
        """현금 매수 주문"""
        while True:
            try:
                return self.auth.order.buy_order_cash(symbol, quantity, price)
            except Exception as e:
                print(f"매수 주문 실패: {e}")
                time.sleep(1)  # 잠시 대기 후 재시도
                continue

    def sell(self, symbol: str, quantity: int, price: float):
        """현금 매도 주문"""
        while True:
            try:
                return self.auth.order.sell_order_cash(symbol, quantity, price)
            except Exception as e:
                print(f"매도 주문 실패: {e}")
                time.sleep(1)  # 잠시 대기 후 재시도
                continue
    
    def immediately_sell(self, symbol: str, quantity: int):
        """즉시 매도 주문 (시장가)"""
        while True:
            try:
                result = self.auth.order.immediately_sell(symbol, quantity)
                self.update_sell_list()
                return result
            except Exception as e:
                print(f"즉시 매도 주문 실패: {e}")
                time.sleep(1)  # 잠시 대기 후 재시도
                continue

if __name__ == "__main__":
    bot = DayTradingBot()
    bot.run()
