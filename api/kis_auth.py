from datetime import datetime, timedelta
import os
import requests
import json


class KisAuth:
    def __init__(self, app_id, api_key, secret_key, account, is_virtual, domain):
        self.app_id = app_id
        self.api_key = api_key
        self.secret_key = secret_key
        self.is_virtual = is_virtual
        self.custtype = "P"  # 고객구분 (P: 개인, B: 법인)
        self.domain = domain

        # cache 폴더는 현재 디렉토리에 생성됩니다. 필요에 따라 경로를 변경할 수 있습니다.
        self.cache_dir = f"./cache/{self.app_id}/"
        if not os.path.exists(self.cache_dir):
            os.makedirs(self.cache_dir)
        
        self.token_cache_file = os.path.join(self.cache_dir, "access_token.json")

        from api.kis_auth_account import KisAuthAccount
        self.account = KisAuthAccount(self, account)

        from api.kis_auth_order import KisAuthOrder
        self.order = KisAuthOrder(self)
    
    def delete_token(self):
        # 토큰 캐시 파일 삭제
        if os.path.exists(self.token_cache_file):
            os.remove(self.token_cache_file)

    def _get_access_token(self):
        # 캐시된 토큰이 유효한지 확인
        if os.path.exists(self.token_cache_file):
            with open(self.token_cache_file, "r") as f:
                token_data = json.load(f)

            # 토큰이 아직 유효한지 확인 (예: 1시간 유효)
            expires_at = datetime.fromisoformat(token_data["expires_at"])
            if datetime.now() < expires_at - timedelta(minutes=5):  # 만료 5분 전까지 유효하다고 간주
                return token_data["access_token"]

        response = requests.post(
            f"{self.domain}/oauth2/token",
            data={
                "grant_type": "client_credentials",
                "appkey": self.api_key,
                "appsecret": self.secret_key
            },
            timeout=10
        )
        if response.status_code == 200:
            token_info = response.json()
            access_token = token_info["access_token"]
            expires_in = token_info["expires_in"]

            # 토큰과 만료 시간을 캐시에 저장
            token_data = {
                "access_token": access_token,
                "expires_at": (datetime.now() + timedelta(seconds=expires_in)).isoformat()
            }
            with open(self.token_cache_file, "w") as f:
                json.dump(token_data, f)

            return access_token
        else:
            raise Exception(f"Failed to get access token: {response.status_code} {response.text}")

    def request(self, url, tr_id, headers=None, params=None):
        if headers is None:
            headers = {}

        #headers에 authorization, appkey, appsecret를 포함시킨다
        headers.update({
            "authorization": f"Bearer {self._get_access_token()}",
            "appkey": self.api_key,
            "appsecret": self.secret_key,
            "custtype": self.custtype,
            "tr_id": tr_id
        })

        return requests.get(f"{self.domain}{url}", headers=headers, params=params, timeout=10)

    def request_post(self, url, tr_id, headers, params=None):
        #headers에 authorization, appkey, appsecret를 포함시킨다
        headers.update({
            "authorization": f"Bearer {self._get_access_token()}",
            "appkey": self.api_key,
            "appsecret": self.secret_key,
            "custtype": self.custtype,
            "tr_id": tr_id
        })

        return requests.post(f"{self.domain}{url}", headers=headers, data=json.dumps(params), timeout=10)