from KisAuth import KisAuth
from KisKey import app_account
from KisKey import app_domain
from KisKey import app_is_virtual
from KisKey import app_key
from KisKey import app_secret
from InfoKosdaq import find_by_name, load_kosdaq_master
from PriceAnalysis import PriceAnalysis
import time

kosdq_records = load_kosdaq_master()

# 관심 종목을 리스트로 수집
kosdq_wish_names = ["인텍플러스"]
kosdq_wish_list = []

# 관심 종목 정보 수집
for name in kosdq_wish_names:
    results = find_by_name(name, kosdq_records)
    if results is None or len(results) == 0:
        print(f"{name} 종목을 찾을 수 없습니다.")
        exit(1)
    else:
        kosdq_wish_list.append(results[0])

auth = KisAuth(app_key, app_secret, app_account, app_is_virtual, app_domain)

# QLD ETF의 현재가 조회 (미국 주식 예시)
#price = auth.price.get_current_overseas("QLD", "AMS")
#print(f"QLD 현재가: {price}")

auth.account.update()
print(f"예수금: {auth.account.dnca_tot_amt}")
print(f"D+1 예수금: {auth.account.nxdy_excc_amt}")
print(f"D+2 예수금: {auth.account.prvs_rcdl_excc_amt}")

# 아이템 별로 현재가를 수집한다
price_analysis = PriceAnalysis()

for stock in kosdq_wish_list:
        price = auth.price.get_average_price_30day(stock.mksc_shrn_iscd)
        print(f"관심 종목: [{stock.mksc_shrn_iscd}] {stock.hts_kor_isnm} / 30일 평균가: {price}")

while True:
    # 관심 종목들의 현재가 조회
    for stock in kosdq_wish_list:
        error_count = 0
        while True:
            try:
                price = auth.price.get_current(stock.mksc_shrn_iscd)
                break
            except Exception as e:
                if error_count >= 5:
                    print(f"Error fetching current price for {stock.mksc_shrn_iscd} after 5 attempts: {e}")

                time.sleep(1)  # 잠시 대기 후 재시도
                continue

        price_analysis.add_price(stock.mksc_shrn_iscd, price)
        print(f"관심 종목: [{stock.mksc_shrn_iscd}] {stock.hts_kor_isnm} / 현재가: {price}")

    # 1초마다 갱신
    time.sleep(1)
