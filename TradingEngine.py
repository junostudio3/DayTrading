import copy
import queue
import threading
import time
from typing import Any

from DayTradingBot import DayTradingBot


class TradingEngine:
    def __init__(self, bot: DayTradingBot, interval_seconds: int = 1):
        self.bot = bot
        # hook engine logging into the bot so that any message the bot emits
        # via its `log` attribute will be funneled through _append_log.
        # This allows automated orders from the bot to appear in engine logs.
        self.bot.log = self._append_log

        self.interval_seconds = max(1, min(5, interval_seconds))
        self._stop_event = threading.Event()
        self._order_queue: queue.Queue[dict[str, Any]] = queue.Queue()
        self._snapshot_lock = threading.Lock()
        self._latest_snapshot: dict[str, Any] = {}
        self._logs: list[str] = []
        self._thread = threading.Thread(target=self._run_loop, daemon=True)

    def start(self):
        if not self._thread.is_alive():
            self._thread = threading.Thread(target=self._run_loop, daemon=True)
            self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._thread.is_alive():
            self._thread.join(timeout=3)
        self.bot.price_analysis.save_cache()

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
                with self._snapshot_lock:
                    self._latest_snapshot = snapshot
            except Exception as e:
                self._append_log(f"엔진 오류: {e}")

            for _ in range(self.interval_seconds * 10):
                if self._stop_event.is_set():
                    break
                time.sleep(0.1)

        self._append_log("거래 엔진 종료")
