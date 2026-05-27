from google_ai_helper import GoogleAiHelper
from google_ai_helper import GoogleAiOptions
from KisKey import google_api_key
from typing import Optional
import time
import json


class WatchlistAIComments:
    def __init__(self, file_path: str):
        self.google_ai_helper = GoogleAiHelper(api_key=google_api_key, options=GoogleAiOptions())
        self.comments: dict[str, str] = {}
        self.comments_updated_time: dict[str, float] = {}
        self.request_ids: dict[str, str] = {}
        self.file_path = file_path
        self.load(file_path)

    def get_ai_comment(self, prdt_name: str) -> Optional[str]:
        if prdt_name in self.comments:
            if time.time() - self.comments_updated_time.get(prdt_name, 0) < 60 * 60 * 12: # 12시간 이내에 업데이트된 코멘트는 재사용한다
                return self.comments[prdt_name]
            # 오래된 코멘트는 삭제한다
            del self.comments[prdt_name]
            del self.comments_updated_time[prdt_name]
            self.save(self.file_path)
        
        if self.request_ids.get(prdt_name, "") != "":
            # AI 코멘트 요청이 이미 된 종목은 결과가 나왔는지 확인한다
            ai_result = self.google_ai_helper.get_response(self.request_ids[prdt_name])
            if ai_result is not None:
                self.comments[prdt_name] = ai_result
                self.comments_updated_time[prdt_name] = time.time()
                del self.request_ids[prdt_name] # 결과를 받았으므로 ID 제거
                self.save(self.file_path) # AI 코멘트가 업데이트된 종목은 저장한다

            return ai_result

        # AI 코멘트가 없는 경우 새로 요청한다
        request_id = self.google_ai_helper.request_swing_stack_check(prdt_name)
        self.request_ids[prdt_name] = request_id
        return None

    def load(self, file_path: str):
        # json 파일에서 AI 코멘트를 불러오는 로직을 구현한다
        try:
            with open(file_path, "r") as f:
                data = json.load(f)
                self.comments = data.get("comments", {})
                self.comments_updated_time = data.get("comments_updated_time", {})
        except FileNotFoundError:
            # 파일이 없는 경우 빈 딕셔너리로 초기화한다
            self.comments = {}
            self.comments_updated_time = {}

    def save(self, file_path: str):
        # AI 코멘트를 json 파일로 저장하는 로직을 구현한다
        data = {
            "comments": self.comments,
            "comments_updated_time": self.comments_updated_time,
        }
        with open(file_path, "w") as f:
            json.dump(data, f, indent=4)
