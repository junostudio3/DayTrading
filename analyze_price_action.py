import sqlite3
import datetime
import os
import argparse

"""
[analyze_price_action.py]
특정 종목(pdno)의 특정 시간대(매수~매도 시점 등) 프라이스 액션(5분봉)을 SQLite 캐시 DB를 통해 조회하고,
해당 구간 내 최고가, 최저가, 그리고 잠재 최고 수익률을 분석하는 유틸리티 스크립트입니다.

사용법:
python3 analyze_price_action.py --pdno 140670 --date 2026-05-08 --buy "10:39:26" --sell "11:31:43" --buy-price 17220
"""

def main():
    parser = argparse.ArgumentParser(description="특정 종목의 보유 구간 내 프라이스 액션을 분석합니다.")
    parser.add_argument("--pdno", type=str, required=True, help="종목코드 (예: 140670)")
    parser.add_argument("--date", type=str, required=True, help="분석 날짜 (예: 2026-05-08)")
    parser.add_argument("--buy", type=str, required=True, help="매수 시간 (예: 10:39:26)")
    parser.add_argument("--sell", type=str, required=True, help="매도 시간 (예: 11:31:43)")
    parser.add_argument("--buy-price", type=float, default=0.0, help="매수 가격 (지정 시 수익률 계산)")
    parser.add_argument("--padding", type=int, default=600, help="조회 전후 여유 시간 (초 단위, 기본 600초)")
    
    args = parser.parse_args()

    target_date_str = args.date
    buy_time_str = f"{target_date_str} {args.buy}"
    sell_time_str = f"{target_date_str} {args.sell}"

    try:
        buy_time = datetime.datetime.strptime(buy_time_str, "%Y-%m-%d %H:%M:%S").timestamp()
        sell_time = datetime.datetime.strptime(sell_time_str, "%Y-%m-%d %H:%M:%S").timestamp()
    except ValueError as e:
        print(f"시간 파싱 오류: {e}. 'YYYY-MM-DD' 와 'HH:MM:SS' 형식을 지켜주세요.")
        return

    db_path = f"cache/price_analysis/{args.pdno}.db"
    
    print(f"=== 프라이스 액션 분석: {args.pdno} ===")
    print(f"DB File : {db_path}")
    print(f"기간    : {buy_time_str} ~ {sell_time_str}")
    
    if not os.path.exists(db_path):
        print(f"⚠️ 데이터베이스 파일을 찾을 수 없습니다: {db_path}")
        return

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute('''
        SELECT start_time, open_price, high_price, low_price, close_price 
        FROM candles 
        WHERE start_time >= ? AND start_time <= ?
        ORDER BY start_time ASC
    ''', (buy_time - args.padding, sell_time + args.padding))
    
    rows = cur.fetchall()
    
    if not rows:
        print("해당 구간의 캔들 데이터가 존재하지 않습니다.")
        conn.close()
        return

    max_high = 0
    max_high_time = ""
    min_low = float('inf')
    
    print("\n[시간] O(시가) H(고가) L(저가) C(종가) | 구분")
    print("-" * 50)
    for r in rows:
        st_val = datetime.datetime.fromtimestamp(r[0]).strftime('%H:%M:%S')
        o, h, l, c = r[1], r[2], r[3], r[4]
        
        is_holding = (r[0] >= buy_time) and (r[0] <= sell_time)
        marker = " (보유구간)" if is_holding else ""
        
        if is_holding:
            if h > max_high:
                max_high = h
                max_high_time = st_val
            if l < min_low:
                min_low = l
                
        print(f"[{st_val}] O:{o} H:{h} L:{l} C:{c}{marker}")
    
    print("-" * 50)
    if max_high > 0:
        print(f"-> 보유 구간 내 최고가 : {max_high}원 (발생 캔들: {max_high_time})")
        print(f"-> 보유 구간 내 최저가 : {min_low}원")
        if args.buy_price > 0:
            profit_pct = (max_high / args.buy_price - 1) * 100
            print(f"-> 잠재 최고 수익률    : +{profit_pct:.2f}% (매수가 {args.buy_price}원 기준)")

    conn.close()

if __name__ == "__main__":
    main()