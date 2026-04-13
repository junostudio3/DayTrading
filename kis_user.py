from kis_auth import KisAuth
import time

class KisUser:
    def __init__(self, id, key, secret, account, is_virtual, log):
        self.app_id = id
        self.app_key = key
        self.app_secret = secret
        self.app_account = account
        self.app_is_virtual = is_virtual
        self.log = log

        if self.app_is_virtual:
            self.app_domain = "https://openapivts.koreainvestment.com:29443"
        else:
            self.app_domain = "https://openapi.koreainvestment.com:9443"

        self.auth = KisAuth(self.app_key, self.app_secret, self.app_account, self.app_is_virtual, self.app_domain)
        self.update_account()

    def update_account(self):
        try_count = 0
        while True:
            try:
                self.auth.account.update()
                break
            except Exception as e:
                if try_count >= 5:
                    self.log(f"계좌 정보 업데이트 실패: {e}")
                time.sleep(1)  # 잠시 대기 후 재시도
                try_count += 1

class KisUserManager:
    def __init__(self, log):
        self.log = log
        self.users: list[KisUser] = []

    def add_user(self, id, key, secret, account, is_virtual):
        user = KisUser(id, key, secret, account, is_virtual, self.log)
        self.users.append(user)

    def find_user(self, id) -> KisUser:
        for user in self.users:
            if user.app_id == id:
                return user
        return None

    def set_logger(self, log):
        self.log = log
        for user in self.users:
            user.log = log

