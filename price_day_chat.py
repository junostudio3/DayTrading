from kis_api.info_kosdaq import load_kosdaq_master
from kis_api.info_kospi import load_kospi_master
from kis_api.kis_user import KisAuth, KisUserManager, KisUser
from kis_api.market_data_service import MarketDataService
from common_structure import SwingIndicator
from KisKey import mysql_host
from KisKey import mysql_port
from KisKey import mysql_user
from KisKey import mysql_password
from KisKey import mysql_database

import pymysql
import time


class PriceDayChat:
    def __init__(self, market_data_service: MarketDataService):
        self.market_data_service = market_data_service
        # API 트래픽 경감을 위한 메모리 동기화 기록 딕셔너리 (하루 1회만 호출)
        self.last_sync_date = {}

        # DB 테이블이 없으면 생성한다
        try:
            connection = pymysql.connect(
                    host=mysql_host,
                    port=mysql_port,
                    user=mysql_user,
                    password=mysql_password,
                    database=mysql_database,
                    cursorclass=pymysql.cursors.DictCursor
                )
            with connection:
                with connection.cursor() as cursor:
                    sql = """
                        CREATE TABLE IF NOT EXISTS `pulsetrade.daycandle` (
                            pdno VARCHAR(20) NOT NULL,
                            date DATE NOT NULL,
                            stck_oprc DOUBLE NOT NULL,
                            stck_hgpr DOUBLE NOT NULL,
                            stck_lwpr DOUBLE NOT NULL,
                            stck_clpr DOUBLE NOT NULL,
                            acml_vol BIGINT NOT NULL,
                            PRIMARY KEY (pdno, date)
                        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
                    """
                    cursor.execute(sql)
                connection.commit()
        except Exception as e:
            print(f"DB 테이블 생성 실패: {e}")

    def get_past_avg_stck_clpr(self, pdno: str, now: float, days: int) -> float:
        """
        [주의] 장중 실시간 갱신되는 오늘자 일봉 캔들은 노이즈(Whipsaw)를 유발하므로
        지표 계산에서 원천 배제되며 오직 '어제까지의 확정된 데이터'로만 평균을 구합니다.
        """
        if not self.prepare_past_data(pdno, now):
            return 0.0
        
        today_date = time.strftime("%Y%m%d", time.localtime(now))
        try:
            connection = pymysql.connect(
                host=mysql_host, port=mysql_port, user=mysql_user,
                password=mysql_password, database=mysql_database,
                cursorclass=pymysql.cursors.DictCursor
            )
            with connection:
                with connection.cursor() as cursor:
                    sql = """
                        SELECT AVG(stck_clpr) AS avg_clpr 
                        FROM (
                            SELECT stck_clpr FROM `pulsetrade.daycandle` 
                            WHERE pdno=%s AND date < %s 
                            ORDER BY date DESC LIMIT %s
                        ) AS subquery
                    """
                    cursor.execute(sql, (pdno, today_date, days))
                    result = cursor.fetchone()
                    if result and result.get("avg_clpr") is not None:
                        return float(result["avg_clpr"])
        except Exception as e:
            print(f"DB에서 과거 평균 종가 조회 실패: {e}")
        return 0.0

    def get_past_swing_indicators(self, pdno: str, now: float) -> SwingIndicator:
        """
        한 번의 쿼리로 5이평, 20이평, 30이평, 최근 5일 평균 거래량을 구해 반환합니다.
        [주의] 당일 장중 데이터는 지표 왜곡을 막기 위해 계산에서 배제합니다 (date < today).
        """
        result_ind = SwingIndicator(valid=False)

        if not self.prepare_past_data(pdno, now):
            return result_ind
        
        today_date = time.strftime("%Y%m%d", time.localtime(now))
        try:
            connection = pymysql.connect(
                host=mysql_host, port=mysql_port, user=mysql_user,
                password=mysql_password, database=mysql_database,
                cursorclass=pymysql.cursors.DictCursor
            )
            with connection:
                with connection.cursor() as cursor:
                    sql_check = "SELECT COUNT(*) AS count FROM `pulsetrade.daycandle` WHERE pdno=%s AND date < %s"
                    cursor.execute(sql_check, (pdno, today_date))
                    cnt_res = cursor.fetchone()
                    if cnt_res is None or cnt_res.get("count", 0) < 30:
                        return result_ind

                    sql = """
                        SELECT 
                            (SELECT AVG(stck_clpr) FROM (SELECT stck_clpr FROM `pulsetrade.daycandle` WHERE pdno=%s AND date < %s ORDER BY date DESC LIMIT 5) as t) as avg_5d,
                            (SELECT AVG(stck_clpr) FROM (SELECT stck_clpr FROM `pulsetrade.daycandle` WHERE pdno=%s AND date < %s ORDER BY date DESC LIMIT 20) as t) as avg_20d,
                            (SELECT AVG(stck_clpr) FROM (SELECT stck_clpr FROM `pulsetrade.daycandle` WHERE pdno=%s AND date < %s ORDER BY date DESC LIMIT 30) as t) as avg_30d,
                            (SELECT AVG(acml_vol) FROM (SELECT acml_vol FROM `pulsetrade.daycandle` WHERE pdno=%s AND date < %s ORDER BY date DESC LIMIT 5) as t) as avg_vol_5d
                    """
                    cursor.execute(sql, (pdno, today_date, pdno, today_date, pdno, today_date, pdno, today_date))
                    row = cursor.fetchone()
                    if row:
                        result_ind.avg_5d = float(row["avg_5d"] or 0)
                        result_ind.avg_20d = float(row["avg_20d"] or 0)
                        result_ind.avg_30d = float(row["avg_30d"] or 0)
                        result_ind.avg_vol_5d = float(row["avg_vol_5d"] or 0)
                        result_ind.valid = True

        except Exception as e:
            print(f"DB에서 과거 스윙 지표 조회 실패: {e}")
            
        return result_ind

    def prepare_past_data(self, pdno: str, now: float) -> bool:
        """
        API 트래픽 제한을 방지하기 위해 메모리 변수 기반으로 하루 최대 1번만 과거 데이터를 갱신합니다.
        """
        today_date = time.strftime("%Y%m%d", time.localtime(now))
        
        # 오늘 이미 동기화했다면 API를 호출하지 않고 스킵 (트래픽 최적화)
        if self.last_sync_date.get(pdno) == today_date:
            return True

        try:
            connection = pymysql.connect(
                    host=mysql_host, port=mysql_port, user=mysql_user,
                    password=mysql_password, database=mysql_database,
                    cursorclass=pymysql.cursors.DictCursor
                )
            with connection:
                # 100일 전 데이터부터 수집
                start_date = time.strftime("%Y%m%d", time.localtime(now - 100 * 24 * 3600))
                
                daily_item_chart_price = self.market_data_service.get_daily_item_chart_price(pdno, start_date, today_date)
                if daily_item_chart_price is None or len(daily_item_chart_price) == 0:
                    return False
                    
                for day_data in daily_item_chart_price:
                    stck_oprc = float(day_data.get("stck_oprc", "0"))
                    stck_hgpr = float(day_data.get("stck_hgpr", "0"))
                    stck_lwpr = float(day_data.get("stck_lwpr", "0"))
                    stck_clpr = float(day_data.get("stck_clpr", "0"))
                    acml_vol = int(day_data.get("acml_vol", "0"))
                    sql = """
                        INSERT INTO `pulsetrade.daycandle` (pdno, date, stck_oprc, stck_hgpr, stck_lwpr, stck_clpr, acml_vol)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        ON DUPLICATE KEY UPDATE
                            stck_oprc=VALUES(stck_oprc),
                            stck_hgpr=VALUES(stck_hgpr),
                            stck_lwpr=VALUES(stck_lwpr),
                            stck_clpr=VALUES(stck_clpr),
                            acml_vol=VALUES(acml_vol)
                    """
                    with connection.cursor() as cursor:
                        cursor.execute(sql, (pdno, day_data.get("stck_bsop_date", ""), stck_oprc, stck_hgpr, stck_lwpr, stck_clpr, acml_vol))
                connection.commit()
                
                # 성공 시 동기화 일자 기록
                self.last_sync_date[pdno] = today_date
                return True
        except Exception as e:
            print(f"DB 데이터 준비 실패: {e}")
        return False


class PriceDayChatUpdater:
    def __init__(self, auth: KisAuth):
        kosdq_records = load_kosdaq_master()
        kospi_records = load_kospi_master()
        self.all_valid_records = kospi_records + kosdq_records
        market_data_service = MarketDataService(auth)
        self.price_day_chat = PriceDayChat(market_data_service)
        self.update_item_index = 0

    def update_once(self) -> bool:
        if len(self.all_valid_records) == 0:
            return True

        record = self.all_valid_records[self.update_item_index]
        pdno = getattr(record, 'mksc_shrn_iscd', '')
        name = getattr(record, 'hts_kor_isnm', '')
        print(f"업데이트 대상 종목: {pdno} ({name})")

        self.price_day_chat.prepare_past_data(pdno, time.time())
        self.update_item_index += 1

        if self.update_item_index >= len(self.all_valid_records):
            self.update_item_index = 0
            return True

        return False


if __name__ == "__main__":
    user_manager = KisUserManager()
    user_manager.load("./KisKey.json")
    if len(user_manager.users) == 0:
        print("사용자 정보가 없습니다. KisKey.json 파일을 확인하세요.")
        exit()

    user = user_manager.users[0]
    updater = PriceDayChatUpdater(user.auth)
    updater.update_once()
