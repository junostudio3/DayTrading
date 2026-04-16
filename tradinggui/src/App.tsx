import { useState, useEffect, useRef } from 'react';
import { createChart, ColorType } from 'lightweight-charts';
import './App.css';

const API_BASE_URL = 'https://juncom.duckdns.org/day-trading-api';

const fetchWithAuth = async (url: string, options: any = {}) => {
  const token = localStorage.getItem('PULSE_TRADE_TOKEN');
  const headers = { ...options.headers, 'Authorization': `Bearer ${token}` };
  const res = await fetch(url, { ...options, headers });
  if (res.status === 401 || res.status === 403) {
    localStorage.removeItem('PULSE_TRADE_TOKEN');
    window.location.reload();
  }
  return res;
};

interface Account {
  tot_evlu_amt?: number;
  cash?: number;
  d1?: number;
  d2?: number;
}

interface Holding {
  pdno: string;
  name: string;
  qty: number;
  purchase: number;
  current: number;
  profit_rate: number;
}

interface WatchItem {
  pdno: string;
  name: string;
  price: number;
  candles: number;
  volume: number;
  step: string;
}

interface Snapshot {
  timestamp: number;
  account: Account;
  market_open: boolean;
  loop_count: number;
  holdings: Holding[];
  watch: WatchItem[];
  logs: string[];
  trade_logs: string[];
}

function ChartComponent({ pdno }: { pdno: string | null }) {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<any>(null);
  const seriesRef = useRef<any>(null);

  useEffect(() => {
    if (!chartContainerRef.current) return;
    
    const chart = createChart(chartContainerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: '#1E1E1E' },
        textColor: '#D9D9D9',
      },
      grid: {
        vertLines: { color: '#2B2B2B' },
        horzLines: { color: '#2B2B2B' },
      },
      width: chartContainerRef.current.clientWidth || 400,
      height: chartContainerRef.current.clientHeight || 300,
    });
    
    chartRef.current = chart;
    const candlestickSeries = chart.addCandlestickSeries({
      upColor: '#26a69a',
      downColor: '#ef5350',
      borderVisible: false,
      wickUpColor: '#26a69a',
      wickDownColor: '#ef5350',
    });
    seriesRef.current = candlestickSeries;

    const handleResize = () => {
      if (chartContainerRef.current) {
        chart.applyOptions({ width: chartContainerRef.current.clientWidth || 400, height: chartContainerRef.current.clientHeight || 300 });
      }
    };
    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      chart.remove();
    };
  }, []);

  useEffect(() => {
    if (!pdno || !seriesRef.current) return;

    fetchWithAuth(`${API_BASE_URL}/candles/${pdno}`)
      .then((res) => res.json())
      .then((data: any[]) => {
        if (data && data.length > 0) {
          const chartData = data.map((c) => ({
            time: c.end_time,
            open: c.open_price,
            high: c.high_price,
            low: c.low_price,
            close: c.close_price,
          }));
          seriesRef.current.setData(chartData);
          chartRef.current?.timeScale().fitContent();
        } else {
          seriesRef.current.setData([]);
        }
      })
      .catch((err) => console.error(err));
  }, [pdno]);

  return <div ref={chartContainerRef} style={{ width: '100%', height: '100%' }} />;
}

export default function App() {
  const [authToken, setAuthToken] = useState<string | null>(localStorage.getItem('PULSE_TRADE_TOKEN'));
  const [tokenInput, setTokenInput] = useState('');
  
  const [userIds, setUserIds] = useState<string[]>([]);
  const [selectedUser, setSelectedUser] = useState<string>('');
  const [isConnected, setIsConnected] = useState<boolean>(false);
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [selectedPdno, setSelectedPdno] = useState<string | null>(null);
  const [tab, setTab] = useState<'trade_logs' | 'logs'>('trade_logs');
  const [orderModal, setOrderModal] = useState<{ show: boolean; side: 'buy' | 'sell'; pdno: string | null }>({ show: false, side: 'buy', pdno: null });
  const [orderQty, setOrderQty] = useState<string>('');
  const tradeLogRef = useRef<HTMLDivElement>(null);
  const logsRef = useRef<HTMLDivElement>(null);

  if (!authToken) {
    return (
      <div className="modal-overlay">
        <div className="modal">
          <h2>인증 토큰 입력</h2>
          <input 
            type="password" 
            placeholder="하드코딩된 토큰을 입력하세요" 
            value={tokenInput} 
            onChange={(e) => setTokenInput(e.target.value)} 
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                localStorage.setItem('PULSE_TRADE_TOKEN', tokenInput);
                setAuthToken(tokenInput);
              }
            }}
            autoFocus 
          />
          <div className="modal-actions">
            <button className="btn-buy" onClick={() => {
              localStorage.setItem('PULSE_TRADE_TOKEN', tokenInput);
              setAuthToken(tokenInput);
            }}>접속</button>
          </div>
        </div>
      </div>
    );
  }

  useEffect(() => {
    fetchWithAuth(`${API_BASE_URL}/users`)
      .then((res) => res.json())
      .then((data) => {
        if (data && data.length > 0) {
          setUserIds(data);
          setSelectedUser(data[0]);
        }
      })
      .catch((err) => console.error("Failed to load users", err));
  }, []);

  useEffect(() => {
    if (!selectedUser) return;
    
    const fetchSnapshot = async () => {
      try {
        const res = await fetchWithAuth(`${API_BASE_URL}/snapshot?app_id=${selectedUser}`);
        if (res.ok) {
          const data = await res.json();
          setSnapshot(data);
          setIsConnected(true);
        } else {
          setIsConnected(false);
        }
      } catch (err) {
        setIsConnected(false);
      }
    };

    fetchSnapshot();
    const intervalId = setInterval(fetchSnapshot, 1000);
    return () => clearInterval(intervalId);
  }, [selectedUser]);

  useEffect(() => {
    if (tab === 'trade_logs' && tradeLogRef.current) {
      tradeLogRef.current.scrollTop = tradeLogRef.current.scrollHeight;
    } else if (tab === 'logs' && logsRef.current) {
      logsRef.current.scrollTop = logsRef.current.scrollHeight;
    }
  }, [snapshot?.trade_logs, snapshot?.logs, tab]);

  const submitOrder = async () => {
    if (!selectedUser || !orderModal.pdno) return;
    const qty = parseInt(orderQty, 10);
    if (isNaN(qty) || qty <= 0) {
      alert("수량은 1 이상의 숫자여야 합니다.");
      return;
    }

    try {
      const res = await fetchWithAuth(`${API_BASE_URL}/order`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          app_id: selectedUser,
          side: orderModal.side,
          pdno: orderModal.pdno,
          quantity: qty,
        }),
      });
      if (res.ok) {
        alert(`${orderModal.side === 'buy' ? '매수' : '매도'} 주문 요청 완료`);
        setOrderModal({ show: false, side: 'buy', pdno: null });
        setOrderQty('');
      } else {
        const text = await res.text();
        alert(`주문 요청 실패: ${text}`);
      }
    } catch (err) {
      alert(`서버와의 통신 오류: ${err}`);
    }
  };

  const account = snapshot?.account || {};
  const ts = snapshot?.timestamp ? new Date(snapshot.timestamp * 1000).toLocaleString() : '';

  return (
    <div className="app-container">
      <header className="header">
        <div className="header-left">
          <h1>Day Trading Dashboard</h1>
          <select value={selectedUser} onChange={(e) => setSelectedUser(e.target.value)}>
            {userIds.map((uid) => (
              <option key={uid} value={uid}>{uid}</option>
            ))}
          </select>
        </div>
        <div className={`status-summary ${isConnected ? 'connected' : 'disconnected'}`}>
          {isConnected ? (
            <span>
              {snapshot?.market_open ? '장중' : '장외'} | 루프: {snapshot?.loop_count || 0} | 갱신: {ts} | 
              총평가: {account.tot_evlu_amt?.toLocaleString() || 0} | 예수금: {account.cash?.toLocaleString() || 0} | 
              D+1: {account.d1?.toLocaleString() || 0} | D+2: {account.d2?.toLocaleString() || 0}
            </span>
          ) : (
            <span>❌ 서버 연결 끊김! 서버 상태를 확인하세요.</span>
          )}
        </div>
      </header>

      <div className="main-content">
        <div className="left-panel">
          <div className="section">
            <h2>보유주식 (Holdings)</h2>
            <div className="table-wrapper">
              <table>
                <thead>
                  <tr>
                    <th>종목</th>
                    <th>이름</th>
                    <th>수량</th>
                    <th>매입가</th>
                    <th>현재가</th>
                    <th>손익률</th>
                    <th>주문</th>
                  </tr>
                </thead>
                <tbody>
                  {snapshot?.holdings?.map((h) => (
                    <tr key={h.pdno} onClick={() => setSelectedPdno(h.pdno)} className={selectedPdno === h.pdno ? 'selected' : ''}>
                      <td>{h.pdno}</td>
                      <td>{h.name}</td>
                      <td>{h.qty}</td>
                      <td>{h.purchase?.toLocaleString()}</td>
                      <td>{h.current?.toLocaleString()}</td>
                      <td style={{ color: h.profit_rate > 0 ? '#ff4d4f' : h.profit_rate < 0 ? '#1890ff' : 'inherit' }}>
                        {h.profit_rate?.toFixed(2)}%
                      </td>
                      <td>
                        <button className="btn-buy" onClick={(e) => { e.stopPropagation(); setOrderModal({ show: true, side: 'buy', pdno: h.pdno }); }}>매수</button>
                        <button className="btn-sell" onClick={(e) => { e.stopPropagation(); setOrderModal({ show: true, side: 'sell', pdno: h.pdno }); }}>매도</button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
          <div className="section chart-section">
            <h2>그래프 ({selectedPdno || '종목 선택'})</h2>
            <div className="chart-container">
              <ChartComponent pdno={selectedPdno} />
            </div>
          </div>
        </div>

        <div className="right-panel">
          <div className="section">
            <h2>관심종목 (Watchlist)</h2>
            <div className="table-wrapper">
              <table>
                <thead>
                  <tr>
                    <th>종목</th>
                    <th>이름</th>
                    <th>현재가</th>
                    <th>캔들수</th>
                    <th>체결량</th>
                    <th>진행</th>
                    <th>주문</th>
                  </tr>
                </thead>
                <tbody>
                  {snapshot?.watch?.map((w) => (
                    <tr key={w.pdno} onClick={() => setSelectedPdno(w.pdno)} className={selectedPdno === w.pdno ? 'selected' : ''}>
                      <td>{w.pdno}</td>
                      <td>{w.name}</td>
                      <td>{w.price?.toLocaleString()}</td>
                      <td>{w.candles}</td>
                      <td>{w.volume?.toLocaleString()}</td>
                      <td>{w.step}</td>
                      <td>
                        <button className="btn-buy" onClick={(e) => { e.stopPropagation(); setOrderModal({ show: true, side: 'buy', pdno: w.pdno }); }}>매수</button>
                        <button className="btn-sell" onClick={(e) => { e.stopPropagation(); setOrderModal({ show: true, side: 'sell', pdno: w.pdno }); }}>매도</button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </div>

      <div className="logs-panel">
        <div className="tabs">
          <button className={tab === 'trade_logs' ? 'active' : ''} onClick={() => setTab('trade_logs')}>거래 로그</button>
          <button className={tab === 'logs' ? 'active' : ''} onClick={() => setTab('logs')}>일반 로그</button>
        </div>
        <div className="log-content-wrapper" ref={tab === 'trade_logs' ? tradeLogRef : logsRef}>
          {(tab === 'trade_logs' ? snapshot?.trade_logs : snapshot?.logs)?.map((log, i) => (
            <div key={i} className="log-line">{log}</div>
          ))}
        </div>
      </div>

      {orderModal.show && (
        <div className="modal-overlay">
          <div className="modal">
            <h2>{orderModal.side === 'buy' ? '매수' : '매도'} 주문: {orderModal.pdno}</h2>
            <input 
              type="number" 
              placeholder="수량 입력" 
              value={orderQty} 
              onChange={(e) => setOrderQty(e.target.value)} 
              autoFocus 
            />
            <div className="modal-actions">
              <button className="btn-buy" onClick={submitOrder}>확인</button>
              <button onClick={() => setOrderModal({ show: false, side: 'buy', pdno: null })}>취소</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
