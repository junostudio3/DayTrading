from api.kis_auth import KisAuth
import time

class KisUser:
    def __init__(self, id, key, secret, account, is_virtual, log):
        self.app_id = f"{id}-{account}"
        self.app_key = key
        self.app_secret = secret
        self.app_account = account
        self.app_is_virtual = is_virtual
        self.log = log

        if self.app_is_virtual:
            self.app_domain = "https://openapivts.koreainvestment.com:29443"
        else:
            self.app_domain = "https://openapi.koreainvestment.com:9443"

        self.auth = KisAuth(self.app_id, self.app_key, self.app_secret, self.app_account, self.app_is_virtual, self.app_domain)

    def update_account(self, retry_count=-1) -> bool:
        try_count = 0
        while True:
            try:
                self.auth.account.update()
                return True
            except Exception as e:
                if try_count == 0:
                    # 첫 번째 실패 시에만 로그를 남기고 토큰을 삭제한다.
                    self.log(f"계좌 정보 업데이트 실패: {e}")
                    self.auth.delete_token() # 토큰이 문제가 있을 수 있으니 삭제해서 다음 시도시 재발급 받도록 한다.
                if retry_count >=0 and try_count >= retry_count:
                    self.log(f"계좌 정보 업데이트 실패: {e} (최대 재시도 횟수 초과)")
                    return False
                time.sleep(1)  # 잠시 대기 후 재시도
                try_count += 1

class KisUserManager:
    def __init__(self):
        self.users: list[KisUser] = []

    def add_user(self, user : KisUser):
        self.users.append(user)

    def find_user(self, app_id) -> KisUser:
        for user in self.users:
            if user.app_id == app_id:
                return user
        return None

    def set_logger(self, log):
        for user in self.users:
            user.log = log

