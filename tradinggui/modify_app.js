const fs = require('fs');

let content = fs.readFileSync('/home/juncom/codes/DayTrading/tradinggui/src/App.tsx', 'utf8');

// Insert fetchWithAuth helper
const fetchWithAuthStr = `
const fetchWithAuth = async (url: string, options: any = {}) => {
  const token = localStorage.getItem('PULSE_TRADE_TOKEN');
  const headers = { ...options.headers, 'Authorization': \`Bearer \${token}\` };
  const res = await fetch(url, { ...options, headers });
  if (res.status === 401 || res.status === 403) {
    localStorage.removeItem('PULSE_TRADE_TOKEN');
    window.location.reload();
  }
  return res;
};
`;

content = content.replace("const API_BASE_URL", fetchWithAuthStr + "\nconst API_BASE_URL");

// Replace all fetch() calls with fetchWithAuth()
content = content.replace(/fetch\(\`/g, 'fetchWithAuth(`');

// Handle the App component to show token screen
const authScreenJSX = `
  const [authToken, setAuthToken] = useState<string | null>(localStorage.getItem('PULSE_TRADE_TOKEN'));
  const [tokenInput, setTokenInput] = useState('');

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
`;

content = content.replace("export default function App() {\n", "export default function App() {\n" + authScreenJSX);

fs.writeFileSync('/home/juncom/codes/DayTrading/tradinggui/src/App.tsx', content);
