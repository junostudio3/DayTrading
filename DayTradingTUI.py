from __future__ import annotations

import time

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Footer, Header, Input, Label, RichLog, Static, TabbedContent, TabPane

from TradingEngine import TradingEngine


class OrderModal(ModalScreen[dict | None]):
    def __init__(self, side: str, pdno: str):
        super().__init__()
        self.side = side
        self.pdno = pdno

    def compose(self) -> ComposeResult:
        side_text = "매수" if self.side == "buy" else "매도"
        with Vertical(id="order-modal"):
            yield Label(f"{side_text} 주문: {self.pdno}")
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

        self.dismiss({"side": self.side, "pdno": self.pdno, "quantity": int(qty_input)})

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

    #log-tabs {
        height: 12;
        margin: 1 0 0 0;
    }

    .log-pane {
        border: solid #666666;
        padding: 0;
    }

    .log-pane RichLog {
        height: 1fr;
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
        self._watch_pdnos: list[str] = []
        self._holding_pdnos: list[str] = []
        self._rendered_log_sizes = {
            "logs": 0,
            "trade_logs": 0,
        }
        self._last_rendered_timestamp: float | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static("로딩 중...", id="summary")
        with Horizontal(id="tables"):
            yield DataTable(id="holdings")
            yield DataTable(id="watch")
        with TabbedContent(initial="trade-logs-pane", id="log-tabs"):
            with TabPane("거래 로그", id="trade-logs-pane", classes="log-pane"):
                yield RichLog(id="trade-logs", wrap=True, markup=False, auto_scroll=True)
            with TabPane("일반 로그", id="logs-pane", classes="log-pane"):
                yield RichLog(id="logs", wrap=True, markup=False, auto_scroll=True)
        yield Footer()

    def on_mount(self):
        holdings = self.query_one("#holdings", DataTable)
        watch = self.query_one("#watch", DataTable)

        holdings.cursor_type = "row"
        watch.cursor_type = "row"

        holdings.add_columns("종목", "이름", "수량", "매입가", "현재가", "손익률")
        watch.add_columns("종목", "이름", "현재가", "캔들수", "체결량", "진행")

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
        self._render_logs("logs", snapshot.get("logs", []))
        self._render_logs("trade-logs", snapshot.get("trade_logs", []))

    def _render_holdings(self, rows: list[dict]):
        table = self.query_one("#holdings", DataTable)
        table.clear()
        self._holding_pdnos = []
        for row in rows:
            pdno = row.get("pdno", "")
            self._holding_pdnos.append(pdno)
            purchase = row.get("purchase")
            current = row.get("current")
            profit_rate = row.get("profit_rate")
            table.add_row(
                pdno,
                row.get("name", pdno),
                str(row.get("qty", 0)),
                "-" if purchase is None else f"{purchase:,.0f}",
                "-" if current is None else f"{current:,.0f}",
                "-" if profit_rate is None else f"{profit_rate:.2f}%",
            )

    def _render_watch(self, rows: list[dict]):
        table = self.query_one("#watch", DataTable)
        table.clear()
        self._watch_pdnos = []
        for row in rows:
            pdno = row.get("pdno", "")
            self._watch_pdnos.append(pdno)
            price = row.get("price")
            step = row.get("step", "")
            table.add_row(
                pdno,
                row.get("name", pdno),
                "-" if price is None else f"{price:,.0f}",
                str(row.get("candles", 0)),
                # 체결량은 3자리마다 콤마로 구분해서 표시한다
                f"{row.get('volume', 0):,}",
                step
            )

    def _render_logs(self, widget_id: str, logs: list[str]):
        log_widget = self.query_one(f"#{widget_id}", RichLog)
        log_key = widget_id.replace("-", "_")
        rendered_log_size = self._rendered_log_sizes[log_key]
        if len(logs) < rendered_log_size:
            log_widget.clear()
            rendered_log_size = 0

        for line in logs[rendered_log_size:]:
            log_widget.write(line)
        self._rendered_log_sizes[log_key] = len(logs)

    def _selected_pdno(self, side: str) -> str | None:
        watch = self.query_one("#watch", DataTable)
        holdings = self.query_one("#holdings", DataTable)

        if side == "sell" and self.focused == holdings and self._holding_pdnos:
            row = holdings.cursor_row
            if 0 <= row < len(self._holding_pdnos):
                return self._holding_pdnos[row]

        if self._watch_pdnos:
            row = watch.cursor_row
            if 0 <= row < len(self._watch_pdnos):
                return self._watch_pdnos[row]
            return self._watch_pdnos[0]

        if side == "sell" and self._holding_pdnos:
            return self._holding_pdnos[0]

        return None

    def action_buy(self):
        pdno = self._selected_pdno("buy")
        if not pdno:
            self.notify("주문할 종목이 없습니다.", severity="warning")
            return

        self.push_screen(OrderModal("buy", pdno), self._on_order_modal_result)

    def action_sell(self):
        pdno = self._selected_pdno("sell")
        if not pdno:
            self.notify("주문할 종목이 없습니다.", severity="warning")
            return

        self.push_screen(OrderModal("sell", pdno), self._on_order_modal_result)

    def _on_order_modal_result(self, result: dict | None):
        if result is None:
            return

        self.engine.submit_order(result["side"], result["pdno"], result["quantity"])
        order_text = "매수" if result["side"] == "buy" else "매도"
        self.notify(f"{order_text} 주문 요청: {result['pdno']} x {result['quantity']}")
