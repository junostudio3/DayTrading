import copy
import queue
import threading
import time
import traceback
from typing import Any
from telegram_sender import send_telegram_message

from day_trading_bot import DayTradingBot


class TradingEngine:
    def __init__(self, bot: DayTradingBot, interval_seconds: int = 1):
        self.bot = bot
        # hook engine logging into the bot so that any message the bot emits
        # via its `log` attribute will be funneled through _append_log.
        # This allows automated orders from the bot to appear in engine logs.
        self.bot.set_logger(self._append_log)
        self.bot.set_trade_logger(self._append_trade_log)

        self.interval_seconds = max(1, min(5, interval_seconds))
        self._stop_event = threading.Event()
        self._order_queue: queue.Queue[dict[str, Any]] = queue.Queue()
        self._snapshot_lock = threading.Lock()
        self._latest_snapshot: dict[str, Any] = {}
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


    def submit_order(self, side: str, pdno: str, quantity: int):
        self._order_queue.put({"side": side, "pdno": pdno, "quantity": quantity})

    def get_snapshot(self) -> dict[str, Any]:
        with self._snapshot_lock:
            return copy.deepcopy(self._latest_snapshot)

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

            side = order.get("side", "")
            pdno = order.get("pdno", "")
            quantity = int(order.get("quantity", 0))

            try:
                if side == "buy":
                    self.bot.place_manual_buy(pdno, quantity)
                    self._append_log(f"수동 매수 완료: {pdno}, 수량 {quantity}")
                elif side == "sell":
                    self.bot.place_manual_sell(pdno, quantity)
                    self._append_log(f"수동 매도 완료: {pdno}, 수량 {quantity}")
                else:
                    self._append_log(f"알 수 없는 주문 타입: {side}")
            except Exception as e:
                self._append_log(f"주문 실패: {pdno} / {e}")

    def _run_loop(self):
        self._append_log("거래 엔진 시작")
        while not self._stop_event.is_set():
            try:
                self._process_orders()
                self.bot.process_once()
                snapshot = self.bot.get_dashboard_snapshot()
                snapshot["logs"] = self._logs[-100:]
                snapshot["trade_logs"] = self._trade_logs[-100:]
                with self._snapshot_lock:
                    self._latest_snapshot = snapshot
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
                    send_telegram_message(f"🚨 <b>[엔진 루프 크래시 발생]</b>\n<pre>{tb_str[:3800]}</pre>")
                except Exception:
                    pass

            for _ in range(self.interval_seconds * 10):
                if self._stop_event.is_set():
                    break
                time.sleep(0.1)

        self._append_log("거래 엔진 종료")
