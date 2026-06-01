# google gemini API를 사용한 AI 요청 클래스
import time
import threading
import queue
import uuid
from google import genai
from google.genai import types
from KisKey import google_api_key

class GoogleAiOptions:
    def __init__(self):
        self.model = "gemini-3.5-flash"  
        self.request_per_minute = 1  # 분당 요청 수 제한
        self.thinking_level = "MEDIUM"  # 사고 수준(LOW, MEDIUM, HIGH)

class GoogleAiHelper:
    def __init__(self, api_key: str, options: GoogleAiOptions):
        self.api_key = api_key
        self.options = options
        self.request_times: list[float] = []
        self.client = genai.Client(api_key=self.api_key)
        
        # 비동기 처리를 위한 큐와 결과 저장 딕셔너리
        self.request_queue = queue.Queue()
        self.results = {}
        
        # 백그라운드 워커 스레드 시작 (데몬 스레드)
        self.worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self.worker_thread.start()

    def _worker_loop(self):
        # 큐에 쌓인 요청을 순차적으로 처리하는 백그라운드 작업 루프
        while True:
            req_id, prompt = self.request_queue.get()
            if req_id is None:  # 종료 신호
                break
                
            try:
                self.results[req_id] = self._process_request(prompt)
            except Exception as e:
                self.results[req_id] = f"Error: {e}"
            finally:
                self.request_queue.task_done()

    def _process_request(self, prompt: str) -> str:
        # 기존의 실제 API 호출부 및 Rate Limit 로직
        current_time = time.time()
        self.request_times = [t for t in self.request_times if current_time - t < 60]

        if len(self.request_times) >= self.options.request_per_minute:
            time_to_wait = 60 - (current_time - self.request_times[0])
            time.sleep(time_to_wait)
            self.request_times.append(time.time())
        else:
            self.request_times.append(current_time)

        config = types.GenerateContentConfig(
            thinking_config=types.ThinkingConfig(
                thinking_level=self.options.thinking_level,
            ),
            tools=[
                types.Tool(googleSearch=types.GoogleSearch()),
            ],
        )

        response = self.client.models.generate_content(
            model=self.options.model,
            contents=prompt,
            config=config,
        )
        
        return response.text

    def _request(self, prompt: str) -> str:
        # 요청을 큐에 삽입하고 고유 ID를 반환
        req_id = str(uuid.uuid4())
        self.request_queue.put((req_id, prompt))
        return req_id

    def get_response(self, request_id: str) -> str | None:
        # ID에 해당하는 작업이 완료되었으면 결과 문자열 반환, 아니면 None (nullptr) 반환
        return self.results.get(request_id)

    def request_swing_stack_check(self, prdt_name: str, purchase_price: int = None, quantity: int = None) -> str:
        prompt = f"{prdt_name} 주식에 대한 최근 정보를 이용하여 투자에 대한 의견을 제시해줘.\n"
        if purchase_price is not None and quantity is not None:
            prompt += f"현재 매입가는 {purchase_price}원, 수량은 {quantity}주 보유하고 있어.\n"

        prompt += (
            f"{prdt_name} 주식에 대한 최근 정보를 이용하여 투자에 대한 의견을 제시해줘.\n"
            f"현재가 기준 중장기 투자 관점으로 적정가를 어떻게 생각하는지 방향을 제시해줘.\n"
            f"쓸대없는 말은 생략한다. (요약해 드립니다. 라든지)\n"
            f"가장먼저 현재가 기준 <구매추천> 등을 먼저 표기하고 텍스트로 총 3줄 정도로 요약해줘."
        )

        return self._request(prompt)

if __name__ == "__main__":
    options = GoogleAiOptions()
    ai_helper = GoogleAiHelper(api_key=google_api_key, options=options)
    
    # 요청을 큐에 넣고 ID 획득
    req_id = ai_helper.request_swing_stack_check("티씨머티리얼즈")
    print(f"작업이 백그라운드 큐에 등록되었습니다. (ID: {req_id})")
    
    # 결과 대기 플로우 (Non-blocking 확인용 데모)
    while True:
        result = ai_helper.get_response(req_id)
        if result is not None:
            print("\n\n[ AI 응답 결과 ]")
            print(result)
            break
        
        print(".", end="", flush=True)
        time.sleep(1)
