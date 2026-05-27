from api.kis_auth import KisAuth
import os
import time


class KisUser:
    def __init__(self, id, key, secret, account, is_virtual, use_swing_bot, use_daily_bot, log):
        self.app_id = f"{id}-{account}"
        self.app_key = key
        self.app_secret = secret
        self.app_account = account
        self.app_is_virtual = is_virtual
        self.use_swing_bot = use_swing_bot
        self.use_daily_bot = use_daily_bot
        self.log = log

        if self.app_is_virtual:
            self.app_domain = "https://openapivts.koreainvestment.com:29443"
        else:
            self.app_domain = "https://openapi.koreainvestment.com:9443"

        self.auth = KisAuth(self.app_id, self.app_key, self.app_secret, self.app_account, self.app_is_virtual, self.app_domain)


class KisUserManager:
    def __init__(self):
        self.users: list[KisUser] = []
        self.app_id_to_user: dict[str, KisUser] = {}

    def load(self, json_path: str, logger = None) -> bool:
        if logger is None:
            logger = print

        # json_path 경로에 있는 JSON 파일에서 사용자 정보를 읽어와서 user_manager에 추가한다.
        # JSON 파일은 사용자 정보의 리스트 형태로 되어 있어야 한다.
        # 각 사용자 정보는 app_id, api_key, api_secret, account_number, is_virtual 필드를 포함해야 한다.
        start_time = time.time()
        import json
        if not os.path.exists(json_path):
            logger(f"사용자 정보 파일이 존재하지 않습니다: {json_path}")
            return False

        try:
            with open(json_path, "r") as f:
                users_data = json.load(f)
                if not "users" in users_data:
                    logger(f"사용자 정보 항목에 'users' 필드가 없습니다. 항목을 건너뜁니다: {users_data}")
                    return False

                for user_data in users_data["users"]:
                    is_virtual = user_data["is_virtual"]
                    user = KisUser(user_data["id"],
                        user_data["key"],
                        user_data["secret"],
                        user_data["account"],
                        is_virtual,
                        user_data["use_swing_bot"],
                        user_data["use_daily_bot"],
                        logger)
                    
                    is_valid = True
                    while True:
                        if user.auth.update_balance(logger=logger, retry_count=5):
                            break
                        if is_virtual:
                            # 모의투자 때문에 시작을 못하는 것은 좋지 않으므로
                            # 모의투자 계좌는 계좌 정보 업데이트에 실패하더라도 계속 진행한다.
                            is_valid = False
                            break
                        time.sleep(1)
                    if not is_valid:
                        logger(f"사용자 {user.app_id}는 모의투자 계좌가 계좌 정보 업데이트에 실패했습니다. 무시됩니다. 추후 확인하세요")
                        continue
                    self.add_user(user)
        except Exception as e:
            logger(f"사용자 정보 파일을 읽어오는 중 오류가 발생했습니다: {e}")
            return False
        print(f"[{time.time() - start_time:10.2f}초] 총 {len(self.users)}명의 사용자가 로드됨.")
        return True

    def add_user(self, user : KisUser):
        self.users.append(user)
        self.app_id_to_user[user.app_id] = user

    def find_user(self, app_id) -> KisUser:
        return self.app_id_to_user.get(app_id)

    def set_logger(self, log):
        for user in self.users:
            user.log = log

