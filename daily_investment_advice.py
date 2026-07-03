from google_ai_helper import GoogleAiHelper
from google_ai_helper import GoogleAiOptions
from KisKey import google_api_key
from typing import Optional
import json
import time


class DailyInvestmentAdvice:
    def __init__(self, file_path: str):
        self.google_ai_helper = GoogleAiHelper(api_key=google_api_key, options=GoogleAiOptions())
        self.file_path = file_path
        self.advices: dict[str, str] = {}
        self.advice_dates: dict[str, str] = {}
        self.advice_updated_time: dict[str, float] = {}
        self.request_ids: dict[str, str] = {}
        self.load(file_path)

    def get_advice(self, app_id: str, portfolio) -> Optional[dict[str, str]]:
        current_time = time.time()
        local_time = time.localtime(current_time)
        today_str = time.strftime("%Y-%m-%d", local_time)

        existing_text = self.advices.get(app_id)
        existing_date = self.advice_dates.get(app_id)
        if existing_text and existing_date == today_str:
            return {
                "date": existing_date,
                "text": existing_text,
            }

        request_id = self.request_ids.get(app_id, "")
        if request_id != "":
            ai_result = self.google_ai_helper.get_response(request_id)
            if ai_result is not None:
                del self.request_ids[app_id]
                if not ai_result.startswith("Error:"):
                    self.advices[app_id] = ai_result
                    self.advice_dates[app_id] = today_str
                    self.advice_updated_time[app_id] = current_time
                    self.save(self.file_path)
            else:
                if existing_text and existing_date:
                    return {
                        "date": existing_date,
                        "text": existing_text,
                    }
                return None

        if local_time.tm_hour >= 10:
            # 오늘 조언이 없고 10시 이후면 하루 1회 요청을 시작한다.
            if app_id not in self.request_ids:
                self.request_ids[app_id] = self.google_ai_helper.request_swing_stack_check_with_price(portfolio)

        if existing_text and existing_date:
            return {
                "date": existing_date,
                "text": existing_text,
            }
        return None

    def load(self, file_path: str):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.advices = data.get("advices", {})
                self.advice_dates = data.get("advice_dates", {})
                self.advice_updated_time = data.get("advice_updated_time", {})
        except FileNotFoundError:
            self.advices = {}
            self.advice_dates = {}
            self.advice_updated_time = {}

    def save(self, file_path: str):
        data = {
            "advices": self.advices,
            "advice_dates": self.advice_dates,
            "advice_updated_time": self.advice_updated_time,
        }
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)