from candlestick import Candlestick
from KisAuth import KisAuth
import datetime

class KisAuthPrice:
    def __init__(self, auth: KisAuth):
        self.auth = auth

    def get_average_price_30day(self, pdno: str):
        """30일 평균가 조회"""

        params = {
            "fid_cond_mrkt_div_code": "J", # 시장 구분 (예: J:KRX, NX:NXT, UN:통합)
            "fid_input_iscd": pdno,
            "fid_period_div_code": "W", # 기간 분류 코드 (D:30일, W:30주, M:30개월)
            "fid_org_adj_prc": "1", # 수정주가 여부 (0:미수정, 1:수정)
        }

        response = self.auth.request("/uapi/domestic-stock/v1/quotations/inquire-daily-price",
                                     "FHKST01010200", # 국내 주식 평균가 조회 트랜잭션 ID
                                     params=params)

        if response.status_code == 200:
            data = response.json()
            if data.get("rt_cd") == "0" and "output2" in data and "stck_oprc" in data["output2"]:
                return float(data["output2"]["stck_oprc"])
            raise Exception(f"Failed to get average price: {data.get('msg_cd')} {data.get('msg1')}")
        else:
            raise Exception(f"Failed to get average price: {response.status_code} {response.text}")
        
    def get_previous_day_price_and_volume(self, pdno: str):
        """전일 종가와 거래량 조회"""

        # inquire-daily-itemchartprice API를 사용하여 전일 종가와 거래량을 조회한다.
        # 일주일~어제까지 조회하자 (쉬는 날이 있을 수 있으므로)
        input_date1 = (datetime.datetime.now() - datetime.timedelta(days=7)).strftime("%Y%m%d")
        input_date2 = (datetime.datetime.now() - datetime.timedelta(days=1)).strftime("%Y%m%d")
        params = {
            "fid_cond_mrkt_div_code": "J", # 시장 구분 (예: J:KRX, NX:NXT, UN:통합)
            "fid_input_iscd": pdno,
            "fid_input_date_1": input_date1, # 조회 시작날짜 (YYYYMMDD)
            "fid_input_date_2": input_date2, # 조회 종료날짜 (YYYYMMDD)
           "fid_period_div_code": "D", # 기간 분류 코드 (D:일간, W:주간, M:월간)
            "fid_org_adj_prc": "1", # 수정주가 여부 (0:미수정, 1:수정)
        }

        response = self.auth.request("/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice",
                                     "FHKST03010100", # 국내 주식 일간 차트 가격 조회 트랜잭션 ID
                                     params=params)
        
        if response.status_code == 200:
            data = response.json()
            if data.get("rt_cd") == "0" and "output2" in data and isinstance(data["output2"], list) and len(data["output2"]) > 0:
                previous_day_data = data["output2"][0] # 가장 최근 일간 데이터 (전일 데이터)
                price = float(previous_day_data["stck_clpr"]) # 전일 종가
                volume = int(previous_day_data["acml_vol"]) # 누적 거래량
                return price, volume
            raise Exception(f"Failed to get previous day price and volume: {data.get('msg_cd')} {data.get('msg1')}")
        else:
            raise Exception(f"Failed to get previous day price and volume: {response.status_code} {response.text}")

    def get_one_minute_candlestick(self, pdno: str, hour: int, minute: int, include_past_data: bool = False) -> Candlestick:
        """1분봉 조회"""

        # fid_input_hour_1은 조회 시작 시간을 HHMMSS 형식으로 입력
        input_hour = f"{hour:02d}{minute:02d}00"

        params = {
            "fid_cond_mrkt_div_code": "J", # 시장 구분 (예: J:KRX, NX:NXT, UN:통합)
            "fid_input_iscd": pdno,
            "fid_input_hour_1": input_hour, # 조회 시작 시간 (HHMMSS)
            "fid_pw_data_incu_yn": "Y" if include_past_data else "N", # 과거 데이터 포함 여부 (Y: 포함, N: 미포함)
            "fid_etc_cls_code": "",
        }

        tr_id = "FHKST03010200" if self.auth.is_virtual else "FHKST03010200"

        response = self.auth.request("/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice",
                                     tr_id, # 국내 주식 1분봉 조회 트랜잭션 ID
                                     params=params)

        if response.status_code == 200:
            data = response.json()
            if data.get("rt_cd") == "0" and "output2" in data and isinstance(data["output2"], list):
                output = data["output2"]
                if output is None or len(output) == 0:
                    raise Exception(f"Failed to get candlestick data: data is empty")
                price = int(output[0]["stck_prpr"])
                low_price = int(output[0]["stck_lwpr"])
                high_price = int(output[0]["stck_hgpr"])
                volume = int(output[0]["cntg_vol"])
                stick_time = output[0]["stck_cntg_hour"] # 봉이 시작된 시간 (HHMMSS)
                candle = Candlestick(price, high_price, low_price, price, volume)
                # 캔들 시간은 now를 이용해 오늘날짜를 얻은 다음 stick_time 결합
                now = datetime.datetime.now()
                candle.start_time = datetime.datetime.strptime(f"{now.strftime('%Y%m%d')}{stick_time}", "%Y%m%d%H%M%S").timestamp()
                candle.end_time = candle.start_time
                return candle
            raise Exception(f"Failed to get candlestick data: {data.get('msg_cd')} {data.get('msg1')}")
        else:
            raise Exception(f"Failed to get candlestick data: {response.status_code} {response.text}")

    def get_current(self, pdno: str):
        price, _ = self.get_current_price_and_accumulated_volume(pdno)
        return price

    def get_current_price_and_accumulated_volume(self, pdno: str):
        """현재가와 누적 거래량 조회"""

        params = {
            "fid_cond_mrkt_div_code": "J", # 시장 구분 (예: J:KRX, NX:NXT, UN:통합)
            "fid_input_iscd": pdno
        }

        response = self.auth.request("/uapi/domestic-stock/v1/quotations/inquire-price-volume",
                                     "FHKST01010300", # 국내 주식 현재가 및 누적 거래량 조회 트랜잭션 ID
                                     params=params)

        if response.status_code == 200:
            data = response.json()
            if data.get("rt_cd") == "0" and "output" in data:
                price = float(data["output"]["stck_prpr"])
                volume = int(data["output"]["acml_vol"])
                return price, volume
            else:
                raise Exception(f"Failed to get current price and accumulated volume: {data.get('msg_cd')} {data.get('msg1')}")
        else:
            raise Exception(f"Failed to get current price and accumulated volume: {response.status_code} {response.text}")

    def get_current_overseas(self, pdno: str, exchange: str):
        """현재가 조회 """

        params = {
            "AUTH": "",
            "EXCD": exchange,
            "SYMB": pdno
        }

        response = self.auth.request("/uapi/overseas-price/v1/quotations/price",
                                     "HHDFS00000300", # 미국 주식 현재가 조회 트랜잭션 ID
                                     params=params)

        if response.status_code == 200:
            data = response.json()
            if data.get("rt_cd") == "0" and "output" in data and "last" in data["output"]:
                price = float(data["output"]["last"])
                return price
            else:
                raise Exception(f"Failed to get current price: {data.get('msg_cd')} {data.get('msg1')}")
        else:
            raise Exception(f"Failed to get current price: {response.status_code} {response.text}")
