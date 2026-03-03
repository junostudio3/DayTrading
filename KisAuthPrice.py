from KisAuth import KisAuth
import datetime
import time

class KisAuthPrice:
    def __init__(self, auth: KisAuth):
        self.auth = auth

    def get_average_price_30day(self, symbol: str):
        """30일 평균가 조회"""

        params = {
            "fid_cond_mrkt_div_code": "J", # 시장 구분 (예: J:KRX, NX:NXT, UN:통합)
            "fid_input_iscd": symbol,
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

    def get_one_minute_candlestick(self, symbol: str, hour: int, minute: int):
        """1분봉 조회"""

        # fid_input_hour_1은 조회 시작 시간을 HHMMSS 형식으로 입력
        input_hour = f"{hour:02d}{minute:02d}00"

        params = {
            "fid_cond_mrkt_div_code": "J", # 시장 구분 (예: J:KRX, NX:NXT, UN:통합)
            "fid_input_iscd": symbol,
            "fid_input_hour_1": input_hour, # 조회 시작 시간 (HHMMSS)
            "fid_pw_data_incu_yn": "N", # 과거 데이터 포함 여부 (Y: 포함, N: 미포함)
            "fid_etc_cls_code": "",
        }

        tr_id = "FHKST03010200" if self.auth.is_virtual else "FHKST03010200"

        response = self.auth.request("/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice",
                                     tr_id, # 국내 주식 1분봉 조회 트랜잭션 ID
                                     params=params)

        if response.status_code == 200:
            data = response.json()
            if data.get("rt_cd") == "0" and "output2" in data and isinstance(data["output2"], list):
                return data["output2"]
            raise Exception(f"Failed to get candlestick data: {data.get('msg_cd')} {data.get('msg1')}")
        else:
            raise Exception(f"Failed to get candlestick data: {response.status_code} {response.text}")

    def get_current(self, symbol: str):
        price, _ = self.get_current_price_and_accumulated_volume(symbol)
        return price

    def get_current_price_and_accumulated_volume(self, symbol: str):
        """현재가와 누적 거래량 조회"""

        params = {
            "fid_cond_mrkt_div_code": "J", # 시장 구분 (예: J:KRX, NX:NXT, UN:통합)
            "fid_input_iscd": symbol
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

    def get_current_overseas(self, symbol: str, exchange: str):
        """현재가 조회 """

        params = {
            "AUTH": "",
            "EXCD": exchange,
            "SYMB": symbol
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
