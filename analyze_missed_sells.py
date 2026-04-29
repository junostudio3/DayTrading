import sqlite3
import datetime
import os

target_date_str = "2026-04-29"
target_date = datetime.datetime.strptime(target_date_str, "%Y-%m-%d")
start_ts = target_date.timestamp()
end_ts = (target_date + datetime.timedelta(days=1)).timestamp()

trades = [
    {"pdno": "092460", "name": "한라IMS", "buy_time": "09:06:51", "sell_time": "09:21:41", "buy_price": 21250, "sell_price": 20750},
    {"pdno": "222080", "name": "씨아이에스", "buy_time": "12:42:51", "sell_time": "14:47:38", "buy_price": 18900, "sell_price": 18600},
    {"pdno": "077360", "name": "덕산하이메탈", "buy_time": "12:49:45", "sell_time": "15:04:41", "buy_price": 17750, "sell_price": 17750},
    {"pdno": "006340", "name": "대원전선", "buy_time": "13:19:09", "sell_time": "14:00:48", "buy_price": 12590, "sell_price": 12780},
]

for t in trades:
    pdno = t['pdno']
    buy_time = datetime.datetime.strptime(f"{target_date_str} {t['buy_time']}", "%Y-%m-%d %H:%M:%S").timestamp()
    sell_time = datetime.datetime.strptime(f"{target_date_str} {t['sell_time']}", "%Y-%m-%d %H:%M:%S").timestamp()
    
    db_path = f"cache/price_analysis/{pdno}.db"
    if not os.path.exists(db_path):
        print(f"DB not found: {db_path}")
        continue
        
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    
    cur.execute('''
        SELECT start_time, open_price, high_price, low_price, close_price 
        FROM candles 
        WHERE start_time >= ? AND start_time <= ?
        ORDER BY start_time ASC
    ''', (buy_time - 600, sell_time + 600))
    
    rows = cur.fetchall()
    
    print(f"=== {t['name']} ({pdno}) ===")
    print(f"매수: {t['buy_price']}원 ({t['buy_time']}), 매도: {t['sell_price']}원 ({t['sell_time']})")
    
    max_high = 0
    max_high_time = ""
    
    for r in rows:
        st_val = datetime.datetime.fromtimestamp(r[0]).strftime('%H:%M:%S')
        o, h, l, c = r[1], r[2], r[3], r[4]
        
        marker = ""
        if r[0] >= buy_time and r[0] <= sell_time:
            marker = " (보유중)"
            if h > max_high:
                max_high = h
                max_high_time = st_val
                
        print(f"[{st_val}] O:{o} H:{h} L:{l} C:{c}{marker}")
        
    if max_high > 0:
        profit_pct = (max_high / t['buy_price'] - 1) * 100
        loss_pct = (t['sell_price'] / t['buy_price'] - 1) * 100
        print(f"-> 매수 이후 최고가: {max_high}원 ({max_high_time}) / 잠재 최고수익률: {profit_pct:.2f}%")
        print(f"-> 실제 매도수익률: {loss_pct:.2f}%")
    print("\n")
    conn.close()
