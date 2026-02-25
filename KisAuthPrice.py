from KisAuth import KisAuth


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

    def get_current(self, symbol: str):
        """현재가 조회 """

        params = {
            "fid_cond_mrkt_div_code": "J", # 시장 구분 (예: J:KRX, NX:NXT, UN:통합)
            "fid_input_iscd": symbol
        }

        response = self.auth.request("/uapi/domestic-stock/v1/quotations/inquire-price",
                                     "FHKST01010100", # 국내 주식 현재가 조회 트랜잭션 ID
                                     params=params)

        if response.status_code == 200:
            data = response.json()
            if data.get("rt_cd") == "0" and "output" in data and "stck_prpr" in data["output"]:
                price = float(data["output"]["stck_prpr"])
                return price
            else:
                raise Exception(f"Failed to get current price: {data.get('msg_cd')} {data.get('msg1')}")
        else:
            raise Exception(f"Failed to get current price: {response.status_code} {response.text}")

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
