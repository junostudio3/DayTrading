import requests
import datetime as dt
from datetime import datetime
from datetime import date
import time
import os
import sys
import xml.etree.ElementTree as ET

class SpecialDays:
    #데이터를 요청하는 함수
    def _get_request_query(url, operation, params, serviceKey):
        import urllib.parse as urlparse
        params = urlparse.urlencode(params)
        request_query = url + '/' + operation + '?' + params + '&' + 'serviceKey' + '=' + serviceKey
        return request_query

    @staticmethod
    def _normalize_target_date(target_date) -> datetime:
        if isinstance(target_date, time.struct_time):
            return datetime.fromtimestamp(time.mktime(target_date))
        if isinstance(target_date, datetime):
            return target_date
        if isinstance(target_date, date):
            return datetime.combine(target_date, datetime.min.time())
        if isinstance(target_date, str):
            normalized = target_date.strip().replace('-', '').replace('/', '').replace('.', '')
            return datetime.strptime(normalized, '%Y%m%d')
        raise TypeError("target_date must be a datetime, date, or YYYYMMDD string")

    @staticmethod
    def is_holiday(target_date, mykey) -> bool:
        normalized_date = SpecialDays._normalize_target_date(target_date)
        if normalized_date.weekday() >= 5:
            return True

        target_logdate = normalized_date.strftime('%Y%m%d')
        url = 'https://apis.data.go.kr/B090041/openapi/service/SpcdeInfoService'
        operation = 'getRestDeInfo'
        params = {
            'solYear': normalized_date.strftime('%Y'),
            'solMonth': normalized_date.strftime('%m'),
        }
        # time out : 30초
        request_query = SpecialDays._get_request_query(url, operation, params, mykey)

        get_data = requests.get(request_query, timeout=30)
        if get_data.ok is not True:
            raise Exception(f"공휴일 API 요청 실패: {get_data.status_code} - {get_data.text}")

        root = ET.fromstring(get_data.content)
        for day in root.findall('.//item'):
            locdate = day.findtext('locdate', '')
            is_holiday = day.findtext('isHoliday', '') or day.findtext('isholiday', '')
            if locdate == target_logdate and is_holiday == 'Y':
                return True
        return False

if __name__ == "__main__":
    # 여기서 수행시에는 상위 폴더를 환경 변수로 추가후 api 폴더에서 import 해야한다.
    # 현재 파일(__file__)의 절대 경로를 기준으로 상위 폴더 경로를 구함
    parent_dir = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))

    # 시스템 경로에 상위 폴더 추가
    if parent_dir not in sys.path:
        sys.path.append(parent_dir)

    from KisKey import data_go_kr_api_key

    now = datetime.now()
    is_holiday = SpecialDays.is_holiday(now, data_go_kr_api_key)
    print(is_holiday)

    is_holiday = SpecialDays.is_holiday("2026-12-25", data_go_kr_api_key)
    print(is_holiday)

