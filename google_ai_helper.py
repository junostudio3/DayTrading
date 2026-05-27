# google gemini API를 사용한 AI 요청 클래스
import time
from google import genai
from google.genai import types
from KisKey import google_api_key

class GoogleAiOptions:
    def __init__(self):
        self.model = "gemini-3.5-flash"  
        self.request_per_minute = 2  # 분당 요청 수 제한
        self.thinking_level = "MEDIUM"  # 사고 수준(LOW, MEDIUM, HIGH)

class GoogleAiHelper:
    def __init__(self, api_key: str, options: GoogleAiOptions):
        self.api_key = api_key
        self.options = options
        self.request_times: list[float] = []
        # Client 초기화를 한 번만 하도록 수정
        self.client = genai.Client(api_key=self.api_key)

    def _request(self, prompt: str) -> str:
        current_time = time.time()
        # 1분 이내의 요청 시간 필터링
        self.request_times = [t for t in self.request_times if current_time - t < 60]

        if len(self.request_times) >= self.options.request_per_minute:
            time_to_wait = 60 - (current_time - self.request_times[0])
            time.sleep(time_to_wait)
            # 대기 후 현재 시간 갱신 
            self.request_times.append(time.time())
        else:
            self.request_times.append(current_time)

        # Google Search 도구 및 Thinking 설정 적용
        config = types.GenerateContentConfig(
            thinking_config=types.ThinkingConfig(
                thinking_level=self.options.thinking_level,
            ),
            tools=[
                types.Tool(googleSearch=types.GoogleSearch()),
            ],
        )

        # 간결하게 문자열 컨텐츠 넘기기
        response = self.client.models.generate_content(
            model=self.options.model,
            contents=prompt,
            config=config,
        )
        
        return response.text

    def request_swing_stack_check(self, stock_name: str) -> str:
        prompt = (
            f"{stock_name} 주식에 대한 최근 정보를 이용하여 투자에 대한 의견을 제시해줘.\n"
            f"현재가 기준 중장기 투자 관점으로 적정가를 어떻게 생각하는지 방향을 제시해줘.\n"
            f"텍스트로 3줄 정도로 요약해줘. 쓸대없는 말은 생략한다. (요약해 드립니다. 라든지)"
        )
        return self._request(prompt)

if __name__ == "__main__":
    options = GoogleAiOptions()
    ai_helper = GoogleAiHelper(api_key=google_api_key, options=options)
    result = ai_helper.request_swing_stack_check("티씨머티리얼즈")
    print(result)
