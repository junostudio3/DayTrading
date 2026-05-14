from api.info_kosdaq import load_kosdaq_master
from api.info_kospi import load_kospi_master
from api.kis_user import KisAuth, KisUserManager, KisUser
from api.market_data_service import MarketDataService
from KisKey import mysql_host
from KisKey import mysql_port
from KisKey import mysql_user
from KisKey import mysql_password
from KisKey import mysql_database

import pymysql
import time


class PriceDayCandle:
    def __init__(self):
        self.date:str = "" # 날짜 (YYYY-MM-DD)
        self.stck_oprc = 0.0 # 시가
        self.stck_hgpr = 0.0 # 고가
        self.stck_lwpr = 0.0 # 저가
        self.stck_clpr = 0.0 # 종가
        self.acml_vol = 0 # 누적 거래량


class PriceDayChat:
    def __init__(self, market_data_service: MarketDataService):
        self.market_data_service = market_data_service

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

    def collect(self, pdno: str, now: float) -> list[PriceDayCandle]:
        items = self._get_data(pdno, now)
        if items is not None:
            return items

        items: list[PriceDayCandle] = []
        # 최근 100일간의 일간 차트 가격을 조회한다.
        end_date = time.strftime("%Y%m%d", time.localtime(now))
        start_date = time.strftime("%Y%m%d", time.localtime(now - 100 * 24 * 3600))

        daily_item_chart_price = self.market_data_service.get_daily_item_chart_price(pdno, start_date, end_date)
        for day_data in daily_item_chart_price:
            candle = PriceDayCandle()
            candle.date = day_data.get("date", "")
            candle.stck_oprc = float(day_data.get("stck_oprc", "0"))
            candle.stck_hgpr = float(day_data.get("stck_hgpr", "0"))
            candle.stck_lwpr = float(day_data.get("stck_lwpr", "0"))
            candle.stck_clpr = float(day_data.get("stck_clpr", "0"))
            candle.acml_vol = int(day_data.get("acml_vol", "0"))
            items.append(candle)

        try:
            # DB에 조회한 데이터를 저장한다 (업데이트 또는 삽입)
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
                    for item in items:
                        stck_oprc = float(item.stck_oprc)
                        stck_hgpr = float(item.stck_hgpr)
                        stck_lwpr = float(item.stck_lwpr)
                        stck_clpr = float(item.stck_clpr)
                        acml_vol = int(item.acml_vol)

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
                        cursor.execute(sql, (pdno, item.date, stck_oprc, stck_hgpr, stck_lwpr, stck_clpr, acml_vol))
                connection.commit()
        except Exception as e:
            print(f"DB 저장 실패: {e}")

        return items

    def _get_data(self, pdno: str, now: float) -> list[PriceDayCandle]:
        end_date = time.strftime("%Y%m%d", time.localtime(now))
        start_date = time.strftime("%Y%m%d", time.localtime(now - 100 * 24 * 3600))
        # DB에서 조회해본다
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
                    sql = "SELECT date, stck_oprc, stck_hgpr, stck_lwpr, stck_clpr, acml_vol FROM `pulsetrade.daycandle` WHERE pdno=%s AND date >= %s AND date <= %s ORDER BY date DESC"
                    cursor.execute(sql, (pdno, start_date, end_date))
                    rows = cursor.fetchall()
                    
                    # 얻은 마지막 날짜가 end_date와 같거나 더 최신이면 DB에 100일치 데이터가 모두 있는 것으로 간주한다.
                    if len(rows) == 0:
                        return None
                    last_date_in_db = rows[0].get("date")
                    if last_date_in_db is None or last_date_in_db.strftime("%Y%m%d") < end_date:
                        return None

                    # DB에 100일치 데이터가 모두 있는 경우 DB에서 조회한 데이터를 반환한다.
                    items: list[PriceDayCandle] = []
                    for row in rows:
                        candle = PriceDayCandle()
                        candle.date = row['date'].strftime("%Y-%m-%d")
                        candle.stck_oprc = row['stck_oprc']
                        candle.stck_hgpr = row['stck_hgpr']
                        candle.stck_lwpr = row['stck_lwpr']
                        candle.stck_clpr = row['stck_clpr']
                        candle.acml_vol = row['acml_vol']
                        items.append(candle)
                    return items
        except Exception as e:
            return None


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

        self.price_day_chat.collect(pdno, time.time())
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
