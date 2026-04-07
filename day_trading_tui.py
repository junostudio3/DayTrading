from __future__ import annotations

import time
import httpx

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Footer, Header, Input, Label, RichLog, Static, TabbedContent, TabPane

API_BASE_URL = "http://127.0.0.1:1530"

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

    #left-tabs {
        width: 1fr;
        height: 1fr;
        border: solid #666666;
    }

    #left-tabs > TabPane {
        padding: 0;
    }

    #holdings, #graph {
        width: 1fr;
        height: 1fr;
    }
    
    #watch {
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

    def __init__(self):
        super().__init__()
        self.client = httpx.AsyncClient(base_url=API_BASE_URL, timeout=3.0)
        self._watch_pdnos: list[str] = []
        self._holding_pdnos: list[str] = []
        self._rendered_log_sizes = {
            "logs": 0,
            "trade_logs": 0,
        }
        self._last_rendered_timestamp: float | None = None
        self._server_connected: bool = True

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static("로딩 중...", id="summary")
        with Horizontal(id="tables"):
            with TabbedContent(initial="holdings-pane", id="left-tabs"):
                with TabPane("보유주식", id="holdings-pane"):
                    yield DataTable(id="holdings")
                with TabPane("그래프", id="graph-pane"):
                    yield Static("", id="graph")
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

        self.set_interval(1.0, self.refresh_dashboard)

    def _set_server_status(self, is_connected: bool):
        if self._server_connected == is_connected:
            return
        
        self._server_connected = is_connected
        summary = self.query_one("#summary", Static)
        
        if not is_connected:
            summary.update("[bold red on white] ❌ 서버 연결 끊김! 서버 상태를 확인하세요. [/bold red on white]")
            summary.styles.background = "red"
            summary.styles.color = "white"
        else:
            summary.styles.background = "transparent"
            summary.styles.color = "auto"
            
    async def on_unmount(self):
        await self.client.aclose()

    async def refresh_dashboard(self):
        try:
            resp = await self.client.get("/snapshot")
            if resp.status_code != 200:
                self._set_server_status(False)
                return
            snapshot = resp.json()
            self._set_server_status(True)
        except Exception:
            self._set_server_status(False)
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
            f"총평가금액:{account.get('tot_evlu_amt', 0):,.0f} | 예수금: {account.get('cash', 0):,.0f} | D+1: {account.get('d1', 0):,.0f} | D+2: {account.get('d2', 0):,.0f}"
        )

        self._render_holdings(snapshot.get("holdings", []))
        self._render_watch(snapshot.get("watch", []))
        self._render_logs("logs", snapshot.get("logs", []))
        self._render_logs("trade-logs", snapshot.get("trade_logs", []))
        
        # Async call for graph
        await self._render_graph_async()

    def _render_holdings(self, rows: list[dict]):
        table = self.query_one("#holdings", DataTable)
        current_row = table.cursor_row
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
        if rows and current_row >= 0:
            table.move_cursor(row=min(current_row, len(rows) - 1))

    def _render_watch(self, rows: list[dict]):
        table = self.query_one("#watch", DataTable)
        current_row = table.cursor_row
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
                f"{row.get('volume', 0):,}",
                step
            )
        if rows and current_row >= 0:
            table.move_cursor(row=min(current_row, len(rows) - 1))

    async def _render_graph_async(self):
        graph = self.query_one("#graph", Static)
        
        watch_table = self.query_one("#watch", DataTable)
        if not self._watch_pdnos:
            return
            
        row_idx = watch_table.cursor_row
        if 0 <= row_idx < len(self._watch_pdnos):
            pdno = self._watch_pdnos[row_idx]
        else:
            pdno = self._watch_pdnos[0]
            
        try:
            resp = await self.client.get(f"/candles/{pdno}")
            if resp.status_code != 200:
                graph.update("데이터 요청 실패")
                return
            c_list = resp.json()
        except Exception:
            graph.update("서버 연결 실패")
            return
            
        if not c_list:
            graph.update("데이터가 없습니다.")
            return

        from datetime import datetime
        import plotext as plt

        dates = [datetime.fromtimestamp(c['end_time']).strftime('%d/%m/%Y %H:%M:%S') if c.get('end_time') else "" for c in c_list]
        prices = {
            "Open": [c['open_price'] for c in c_list],
            "High": [c['high_price'] for c in c_list],
            "Low": [c['low_price'] for c in c_list],
            "Close": [c['close_price'] for c in c_list],
        }
        
        plt.clf()
        plt.theme("dark")
        plt.date_form('d/m/Y H:M:S')
        
        try:
            width, height = graph.size
            plt.plotsize(max(10, width), max(5, height - 2))
        except Exception:
            plt.plotsize(80, 20)

        plt.candlestick(dates, prices)
        plt.title(f"{pdno} 5분봉 차트")
        
        from rich.text import Text
        ansi_str = plt.build()
        graph.update(Text.from_ansi(ansi_str))

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

    async def _on_order_modal_result(self, result: dict | None):
        if result is None:
            return

        try:
            resp = await self.client.post("/order", json={
                "side": result["side"],
                "pdno": result["pdno"],
                "quantity": result["quantity"]
            })
            if resp.status_code == 200:
                order_text = "매수" if result["side"] == "buy" else "매도"
                self.notify(f"{order_text} 주문 요청 완료: {result['pdno']} x {result['quantity']}")
            else:
                self.notify(f"주문 요청 실패: {resp.text}", severity="error")
        except Exception as e:
            self.notify(f"서버와의 통신 오류: {e}", severity="error")

if __name__ == "__main__":
    app = DayTradingTUI()
    app.run()
