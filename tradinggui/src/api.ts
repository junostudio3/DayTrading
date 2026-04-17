export const API_BASE_URL = 'https://juncom.duckdns.org/day-trading-api';

export const fetchWithAuth = async (url: string, options: any = {}) => {
  const token = localStorage.getItem('PULSE_TRADE_TOKEN');
  const headers = { ...options.headers, 'Authorization': `Bearer ${token}` };
  const res = await fetch(url, { ...options, headers });
  if (res.status === 401 || res.status === 403) {
    localStorage.removeItem('PULSE_TRADE_TOKEN');
    window.location.reload();
  }
  return res;
};

export const fetchCandles = async (pdno: string) => {
  const res = await fetchWithAuth(`${API_BASE_URL}/candles/${pdno}`);
  return res.json();
};

export const fetchAccountHistory = async (userId: string) => {
  const res = await fetchWithAuth(`${API_BASE_URL}/account_history?app_id=${userId}`);
  return res.json();
};

export const fetchUsers = async () => {
  const res = await fetchWithAuth(`${API_BASE_URL}/users`);
  return res.json();
};

export const fetchSnapshot = async (selectedUser: string) => {
  const res = await fetchWithAuth(`${API_BASE_URL}/snapshot?app_id=${selectedUser}`);
  return res; // We return the raw response because App.tsx checks res.ok
};

export const submitOrderRequest = async (selectedUser: string, side: string, pdno: string, quantity: number) => {
  return fetchWithAuth(`${API_BASE_URL}/order`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      app_id: selectedUser,
      side,
      pdno,
      quantity,
    }),
  });
};
