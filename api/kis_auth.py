from datetime import datetime, timedelta
import os
import requests
import json
import threading
import time


class KisAuth:
    def __init__(self, app_id, api_key, secret_key, account, is_virtual, domain):
        self.app_id = app_id
        self.api_key = api_key
        self.secret_key = secret_key
        self.is_virtual = is_virtual
        self.custtype = "P"  # 고객구분 (P: 개인, B: 법인)
        self.domain = domain

        self._token_lock = threading.Lock()
        self._rate_limit_lock = threading.Lock()
        self._request_timestamps = []
        self._max_requests_per_second = 1 if self.is_virtual else 15

        # cache 폴더는 현재 디렉토리에 생성됩니다. 필요에 따라 경로를 변경할 수 있습니다.
        self.cache_dir = f"./cache/{self.app_id}/"
        if not os.path.exists(self.cache_dir):
            os.makedirs(self.cache_dir)
        
        self.token_cache_file = os.path.join(self.cache_dir, "access_token.json")

        from api.kis_auth_portfolio import KisAuthPortfolio
        self.portfolio = KisAuthPortfolio(self, account)

        from api.kis_auth_order import KisAuthOrder
        self.order = KisAuthOrder(self)

    def update_balance(self, logger = None, retry_count=-1) -> bool:
        try_count = 0
        while True:
            try:
                self.portfolio.update_balance()
                return True
            except Exception as e:
                if try_count == 0:
                    # 첫 번째 실패 시에만 로그를 남기고 토큰을 삭제한다.
                    if logger:
                        logger(f"계좌 정보 업데이트 실패: {e}")
                    self.delete_token() # 토큰이 문제가 있을 수 있으니 삭제해서 다음 시도시 재발급 받도록 한다.
                if retry_count >=0 and try_count >= retry_count:
                    if logger:
                        logger(f"계좌 정보 업데이트 실패: {e} (최대 재시도 횟수 초과)")
                    return False
                time.sleep(1)  # 잠시 대기 후 재시도
                try_count += 1

    def update_stocks(self, logger = None, retry_count=-1) -> bool:
        try_count = 0
        while True:
            try:
                self.portfolio.update_stocks()
                return True
            except Exception as e:
                if try_count == 0:
                    # 첫 번째 실패 시에만 로그를 남기고 토큰을 삭제한다.
                    if logger:
                        logger(f"주식 정보 업데이트 실패: {e}")
                    self.delete_token() # 토큰이 문제가 있을 수 있으니 삭제해서 다음 시도시 재발급 받도록 한다.
                if retry_count >=0 and try_count >= retry_count:
                    if logger:
                        logger(f"주식 정보 업데이트 실패: {e} (최대 재시도 횟수 초과)")
                    return False
                time.sleep(1)  # 잠시 대기 후 재시도
                try_count += 1

    def delete_token(self):
        # 토큰 캐시 파일 삭제
        with self._token_lock:
            if os.path.exists(self.token_cache_file):
                os.remove(self.token_cache_file)

    def _get_access_token(self):
        with self._token_lock:
            # 캐시된 토큰이 유효한지 확인
            if os.path.exists(self.token_cache_file):
                with open(self.token_cache_file, "r") as f:
                    token_data = json.load(f)

                # 토큰이 아직 유효한지 확인 (예: 1시간 유효)
                expires_at = datetime.fromisoformat(token_data["expires_at"])
                if datetime.now() < expires_at - timedelta(minutes=5):  # 만료 5분 전까지 유효하다고 간주
                    return token_data["access_token"]

            try:
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
            except Exception as e:
                raise Exception(f"Error while getting access token: {e}")

    def _wait_for_rate_limit(self):
        with self._rate_limit_lock:
            while True:
                now = time.time()
                self._request_timestamps = [t for t in self._request_timestamps if now - t < 1.0]
                if len(self._request_timestamps) < self._max_requests_per_second:
                    self._request_timestamps.append(now)
                    break
                
                sleep_time = 1.0 - (now - self._request_timestamps[0])
                if sleep_time > 0:
                    time.sleep(sleep_time)

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
        
        self._wait_for_rate_limit()

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
        
        self._wait_for_rate_limit()

        return requests.post(f"{self.domain}{url}", headers=headers, data=json.dumps(params), timeout=10)