import sqlite3
import time
from common_structure import SymbolItem


# SymbolSnapshot
# SymbolSnapshot은 특정 시점에 대한 심볼의 가격과 거래량을 나타내는 클래스입니다.

class SymbolSnapshot:
    def __init__(self, symbol: SymbolItem, timestamp: float, price: int, volume: int):
        self.symbol = symbol
        self.timestamp = timestamp
        self.price = price
        self.volume = volume


# SymbolSnapshotCache
# SymbolSnapshotCache는 심볼 스냅샷을 캐싱하는 클래스입니다.
# SQLite 데이터베이스를 사용하여 심볼 스냅샷을 저장하고 검색하는 기능을 제공
# 같은 심볼에 대한 스냅샷은 가장 최근의 스냅샷으로 업데이트된다
# 가장 오래된 스냅샷을 가진 심볼을 찾기를 제공하여 이를 이용해 외부에서 오래된 스냅샷 순으로 심볼 정보를 갱신할 수 있도록 한다

class SymbolSnapshotCache:
    def __init__(self, db_path):
        self.db_path = db_path
        self._initialize_database()

    def _initialize_database(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS symbol_snapshots (
                pdno TEXT PRIMARY KEY,
                name TEXT,
                timestamp FLOAT,
                price INTEGER,
                volume INTEGER
            )
        ''')
        conn.commit()
        conn.close()

    def add_snapshot(self, snapshot: SymbolSnapshot):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO symbol_snapshots (pdno, name, timestamp, price, volume)
            VALUES (?, ?, ?, ?, ?)
        ''', (snapshot.symbol.pdno, snapshot.symbol.prdt_name, snapshot.timestamp, snapshot.price, snapshot.volume))
        conn.commit()
        conn.close()

    def is_exists(self, symbol: str) -> bool:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT 1 FROM symbol_snapshots WHERE pdno = ?', (symbol,))
        exists = cursor.fetchone() is not None
        conn.close()
        return exists

    def get_snapshot(self, symbol: str) -> SymbolSnapshot:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT pdno, name, timestamp, price, volume FROM symbol_snapshots WHERE pdno = ?', (symbol,))
        row = cursor.fetchone()
        conn.close()
        if row:
            symbol_item = SymbolItem(pdno=row[0], name=row[1])
            return SymbolSnapshot(symbol=symbol_item, timestamp=float(row[2]), price=int(row[3]), volume=int(row[4]))
        return None
    
    def get_all_snapshots(self) -> list[SymbolSnapshot]:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT pdno, name, timestamp, price, volume FROM symbol_snapshots')
        rows = cursor.fetchall()
        conn.close()
        snapshots = []
        for row in rows:
            symbol_item = SymbolItem(pdno=row[0], name=row[1])
            snapshot = SymbolSnapshot(symbol=symbol_item, timestamp=float(row[2]), price=int(row[3]), volume=int(row[4]))
            snapshots.append(snapshot)
        return snapshots
    
    def get_oldest_snapshot_symbol(self, min_age_seconds: float = 1800) -> SymbolItem:
        """가장 오래된 스냅샷의 심볼을 반환한다.
        min_age_seconds 이내에 갱신된 스냅샷은 건너뛴다(TTL)."""
        cutoff = time.time() - min_age_seconds
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            'SELECT pdno, name FROM symbol_snapshots WHERE timestamp < ? ORDER BY timestamp ASC LIMIT 1',
            (cutoff,)
        )
        row = cursor.fetchone()
        conn.close()
        if row:
            return SymbolItem(pdno=row[0], name=row[1])
        return None

    def get_high_volume_stale_symbol(self, min_age_seconds: float = 1800) -> SymbolItem:
        """TTL이 지난 스냅샷 중 거래량이 가장 높은 심볼을 반환한다.
        거래량 높은 종목을 우선적으로 갱신하기 위해 사용한다."""
        cutoff = time.time() - min_age_seconds
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            'SELECT pdno, name FROM symbol_snapshots WHERE timestamp < ? ORDER BY volume DESC LIMIT 1',
            (cutoff,)
        )
        row = cursor.fetchone()
        conn.close()
        if row:
            return SymbolItem(pdno=row[0], name=row[1])
        return None

    def remove_snapshot(self, symbol: str):
        """심볼 스냅샷을 삭제한다. 유효하지 않은 심볼이 캐시에 남아있는 경우 이를 제거하기 위해 사용한다."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM symbol_snapshots WHERE pdno = ?', (symbol,))
        conn.commit()
        conn.close()
