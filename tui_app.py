from __future__ import annotations

import time

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Footer, Header, Input, Label, RichLog, Static

from trading_engine import TradingEngine


class OrderModal(ModalScreen[dict | None]):
    def __init__(self, side: str, symbol: str):
        super().__init__()
        self.side = side
        self.symbol = symbol

    def compose(self) -> ComposeResult:
        side_text = "매수" if self.side == "buy" else "매도"
        with Vertical(id="order-modal"):
            yield Label(f"{side_text} 주문: {self.symbol}")
            yield Input(placeholder="수량 입력", id="order-qty")
            with Horizontal():
                yield Button("확인", variant="success", id="confirm")
                yield Button("취소", variant="default", id="cancel")

    @on(Button.Pressed, "#confirm")
    def on_confirm(self):
        qty_input = self.query_one("#order-qty", Input).value.strip()
        if not qty_input.isdigit() or int(qty_input) <= 0:
            self.notify("수량은 1 이상의 숫자여야 합니다.", severity="error")
            return

        self.dismiss({"side": self.side, "symbol": self.symbol, "quantity": int(qty_input)})

    @on(Button.Pressed, "#cancel")
    def on_cancel(self):
        self.dismiss(None)


class DayTradingTUI(App):
    BINDINGS = [
        Binding("b", "buy", "매수"),
        Binding("s", "sell", "매도"),
        Binding("q", "quit", "종료"),
    ]

    CSS = """
    Screen {
        layout: vertical;
    }

    #summary {
        height: 4;
        border: solid #666666;
        margin: 0 0 1 0;
    }

    #tables {
        height: 1fr;
    }

    #holdings, #watch {
        width: 1fr;
        border: solid #666666;
    }

    #logs {
        height: 12;
        border: solid #666666;
        margin: 1 0 0 0;
    }

    #order-modal {
        align: center middle;
        width: 50;
        height: 12;
        padding: 1 2;
        border: solid #888888;
        background: $panel;
    }
    """

    def __init__(self, engine: TradingEngine):
        super().__init__()
        self.engine = engine
        self._watch_symbols: list[str] = []
        self._holding_symbols: list[str] = []
        self._rendered_log_size = 0
        self._last_rendered_timestamp: float | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static("로딩 중...", id="summary")
        with Horizontal(id="tables"):
            yield DataTable(id="holdings")
            yield DataTable(id="watch")
        yield RichLog(id="logs", wrap=True, markup=False, auto_scroll=True)
        yield Footer()

    def on_mount(self):
        holdings = self.query_one("#holdings", DataTable)
        watch = self.query_one("#watch", DataTable)

        holdings.cursor_type = "row"
        watch.cursor_type = "row"

        holdings.add_columns("종목", "이름", "수량", "매입가", "현재가", "손익률")
        watch.add_columns("종목", "이름", "현재가", "캔들수", "매수", "매도", "손절")

        self.engine.start()
        self.set_interval(1.0, self.refresh_dashboard)

    def on_unmount(self):
        self.engine.stop()

    def refresh_dashboard(self):
        snapshot = self.engine.get_snapshot()
        if not snapshot:
            return

        snapshot_timestamp = snapshot.get("timestamp")
        if snapshot_timestamp == self._last_rendered_timestamp:
            return
        self._last_rendered_timestamp = snapshot_timestamp

        account = snapshot.get("account", {})
        market_open = snapshot.get("market_open", False)
        loop_count = snapshot.get("loop_count", 0)
        ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(snapshot_timestamp or time.time()))
        market_text = "장중" if market_open else "장외"

        summary = self.query_one("#summary", Static)
        summary.update(
            f"상태: {market_text} | 루프: {loop_count} | 갱신: {ts}\n"
            f"예수금: {account.get('cash', 0):,.0f} | D+1: {account.get('d1', 0):,.0f} | D+2: {account.get('d2', 0):,.0f}"
        )

        self._render_holdings(snapshot.get("holdings", []))
        self._render_watch(snapshot.get("watch", []))
        self._render_logs(snapshot.get("logs", []))

    def _render_holdings(self, rows: list[dict]):
        table = self.query_one("#holdings", DataTable)
        table.clear()
        self._holding_symbols = []
        for row in rows:
            symbol = row.get("symbol", "")
            self._holding_symbols.append(symbol)
            purchase = row.get("purchase")
            current = row.get("current")
            profit_rate = row.get("profit_rate")
            table.add_row(
                symbol,
                row.get("name", symbol),
                str(row.get("qty", 0)),
                "-" if purchase is None else f"{purchase:,.0f}",
                "-" if current is None else f"{current:,.0f}",
                "-" if profit_rate is None else f"{profit_rate:.2f}%",
            )

    def _render_watch(self, rows: list[dict]):
        table = self.query_one("#watch", DataTable)
        table.clear()
        self._watch_symbols = []
        for row in rows:
            symbol = row.get("symbol", "")
            self._watch_symbols.append(symbol)
            price = row.get("price")
            table.add_row(
                symbol,
                row.get("name", symbol),
                "-" if price is None else f"{price:,.0f}",
                str(row.get("candles", 0)),
                "Y" if row.get("buy", False) else "N",
                "Y" if row.get("sell", False) else "N",
                "Y" if row.get("stop", False) else "N",
            )

    def _render_logs(self, logs: list[str]):
        log_widget = self.query_one("#logs", RichLog)
        if len(logs) < self._rendered_log_size:
            log_widget.clear()
            self._rendered_log_size = 0

        for line in logs[self._rendered_log_size:]:
            log_widget.write(line)
        self._rendered_log_size = len(logs)

    def _selected_symbol(self, side: str) -> str | None:
        watch = self.query_one("#watch", DataTable)
        holdings = self.query_one("#holdings", DataTable)

        if side == "sell" and self.focused == holdings and self._holding_symbols:
            row = holdings.cursor_row
            if 0 <= row < len(self._holding_symbols):
                return self._holding_symbols[row]

        if self._watch_symbols:
            row = watch.cursor_row
            if 0 <= row < len(self._watch_symbols):
                return self._watch_symbols[row]
            return self._watch_symbols[0]

        if side == "sell" and self._holding_symbols:
            return self._holding_symbols[0]

        return None

    def action_buy(self):
        symbol = self._selected_symbol("buy")
        if not symbol:
            self.notify("주문할 종목이 없습니다.", severity="warning")
            return

        self.push_screen(OrderModal("buy", symbol), self._on_order_modal_result)

    def action_sell(self):
        symbol = self._selected_symbol("sell")
        if not symbol:
            self.notify("주문할 종목이 없습니다.", severity="warning")
            return

        self.push_screen(OrderModal("sell", symbol), self._on_order_modal_result)

    def _on_order_modal_result(self, result: dict | None):
        if result is None:
            return

        self.engine.submit_order(result["side"], result["symbol"], result["quantity"])
        order_text = "매수" if result["side"] == "buy" else "매도"
        self.notify(f"{order_text} 주문 요청: {result['symbol']} x {result['quantity']}")
