from KisAuth import KisAuth
import requests


class KisAuthPrice:
    def __init__(self, auth: KisAuth):
        self.auth = auth

    def get_current(self, symbol: str):
        """현재가 조회 """

        headers = {
            "authorization": f"Bearer {self.auth.get_access_token()}",
            "appkey": self.auth.api_key,
            "appsecret": self.auth.secret_key,
            "tr_id": "FHKST01010100", # 국내 주식 현재가 조회 트랜잭션 ID
        }

        params = {
            "fid_cond_mrkt_div_code": "J", # 시장 구분 (예: J:KRX, NX:NXT, UN:통합)
            "fid_input_iscd": symbol
        }
        response = requests.get(f"{self.auth.domain}/uapi/domestic-stock/v1/quotations/inquire-price", headers=headers, params=params)
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

        headers = {
            "authorization": f"Bearer {self.auth.get_access_token()}",
            "appkey": self.auth.api_key,
            "appsecret": self.auth.secret_key,
            "tr_id": "HHDFS00000300" # 미국 주식 현재가 조회 트랜잭션 ID
        }

        params = {
            "AUTH": "",
            "EXCD": exchange,
            "SYMB": symbol
        }

        response = requests.get(f"{self.auth.domain}/uapi/overseas-price/v1/quotations/price", headers=headers, params=params)
        if response.status_code == 200:
            data = response.json()
            if data.get("rt_cd") == "0" and "output" in data and "last" in data["output"]:
                price = float(data["output"]["last"])
                return price
            else:
                raise Exception(f"Failed to get current price: {data.get('msg_cd')} {data.get('msg1')}")
        else:
            raise Exception(f"Failed to get current price: {response.status_code} {response.text}")
