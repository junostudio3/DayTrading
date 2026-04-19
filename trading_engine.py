import copy
import queue
import threading
import time
import traceback
from typing import Any
from telegram import Telegram

from day_trading_bot import DayTradingBot


class TradingEngine:
    def __init__(self, bot: DayTradingBot, interval_seconds: int = 1):
        self.bot = bot
        # 엔진에서 발생하는 모든 로그 메시지가 _append_log를 통해 처리되도록 봇의 log 속성을 후킹합니다.
        # 이렇게 하면 봇에서 발생하는 자동 주문 관련 메시지도 엔진 로그에 나타나게 됩니다.
        self.bot.set_logger(self._append_log)
        self.bot.set_trade_logger(self._append_trade_log)

        self.interval_seconds = max(1, min(5, interval_seconds))
        self._stop_event = threading.Event()
        self._order_queue: queue.Queue[dict[str, Any]] = queue.Queue()
        self._snapshot_lock = threading.Lock()
        self._latest_snapshots: dict[str, dict[str, Any]] = {}
        self._logs: list[str] = []
        self._trade_logs: list[str] = []
        self._thread = threading.Thread(target=self._run_loop, daemon=True)

    def start(self):
        if not self._thread.is_alive():
            self._thread = threading.Thread(target=self._run_loop, daemon=True)
            self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._thread.is_alive():
            self._thread.join(timeout=3)


    def get_user_ids(self) -> list[str]:
        return self.bot.get_user_app_ids()

    def submit_order(self, app_id: str, side: str, pdno: str, quantity: int):
        self._order_queue.put({"app_id": app_id, "side": side, "pdno": pdno, "quantity": quantity})

    def get_snapshot(self, app_id: str) -> dict[str, Any]:
        with self._snapshot_lock:
            return copy.deepcopy(self._latest_snapshots.get(app_id, {}))

    def _append_log(self, message: str):
        timestamp = time.strftime("%H:%M:%S")
        self._logs.append(f"[{timestamp}] {message}")
        if len(self._logs) > 300:
            self._logs = self._logs[-300:]

    def _append_trade_log(self, message: str):
        timestamp = time.strftime("%H:%M:%S")
        self._trade_logs.append(f"[{timestamp}] {message}")
        if len(self._trade_logs) > 300:
            self._trade_logs = self._trade_logs[-300:]

    def _process_orders(self):
        while True:
            try:
                order = self._order_queue.get_nowait()
            except queue.Empty:
                break

            app_id = order.get("app_id", "")
            side = order.get("side", "")
            pdno = order.get("pdno", "")
            quantity = int(order.get("quantity", 0))

            try:
                if side == "buy":
                    self.bot.place_manual_buy(app_id, pdno, quantity)
                    self._append_log(f"[{app_id}] 수동 매수 완료: {pdno}, 수량 {quantity}")
                elif side == "sell":
                    self.bot.place_manual_sell(app_id, pdno, quantity)
                    self._append_log(f"[{app_id}] 수동 매도 완료: {pdno}, 수량 {quantity}")
                else:
                    self._append_log(f"알 수 없는 주문 타입: {side}")
            except Exception as e:
                self._append_log(f"[{app_id}] 주문 실패: {pdno} / {e}")

    def _run_loop(self):
        self._append_log("거래 엔진 시작")
        user_app_id_list = self.bot.get_user_app_ids()
        if len(user_app_id_list) == 0:
            self._append_log("경고: 등록된 사용자 앱이 없습니다. 엔진이 정상적으로 작동하려면 최소한 하나의 사용자 앱이 필요합니다.")
            return

        user_index = 0

        while not self._stop_event.is_set():
            app_id = user_app_id_list[user_index]

            try:
                self._process_orders()
                if user_index == 0:
                    now = time.time()
                    self.bot.update_market_and_stock_data(now)

                self.bot.process_once(app_id)
                time.sleep(0.5)

                snapshot = self.bot.get_dashboard_snapshot(app_id)
                snapshot["logs"] = self._logs[-100:]
                snapshot["trade_logs"] = self._trade_logs[-100:]
                with self._snapshot_lock:
                    self._latest_snapshots[app_id] = snapshot
            except Exception as e:
                err_msg = f"엔진 오류: {e}"
                self._append_log(err_msg)
                
                # 파일로도 명시적으로 콜스택을 남깁니다
                try:
                    with open("log/server_crash.log", "a") as f:
                        f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {err_msg}\n")
                        tb_str = traceback.format_exc()
                        f.write(tb_str)
                        f.write("-" * 80 + "\n")
                        
                    # 텔레그램 크래시 알림 전송 (콜스택이 너무 길 수 있으므로 3800자로 자름)
                    Telegram.send_message(f"🚨 <b>[엔진 루프 크래시 발생]</b>\n<pre>{tb_str[:3800]}</pre>")
                except Exception:
                    pass

            for _ in range(self.interval_seconds * 10):
                if self._stop_event.is_set():
                    break
                time.sleep(0.1)
            
            # 다음 사용자로 넘어감
            user_index = (user_index + 1) % len(user_app_id_list)

        self._append_log("거래 엔진 종료")
