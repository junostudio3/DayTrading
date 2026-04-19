import requests
import datetime as dt
from bs4 import BeautifulSoup
from bs4 import XMLParsedAsHTMLWarning
import pandas as pd
from datetime import datetime
import time
import os
import sys
import warnings
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

class TradingCalendar:
    #데이터를 요청하는 함수
    def get_request_query(self, url, operation, params, serviceKey):
        import urllib.parse as urlparse
        params = urlparse.urlencode(params)
        request_query = url + '/' + operation + '?' + params + '&' + 'serviceKey' + '=' + serviceKey
        return request_query
    
    #휴일정보를 받아 처리하는 함수
    def get_holiday(self, year, mykey) -> pd.DataFrame:
        date = []
        for month in range(1, 13): #1월부터 12월까지 for문으로 반복
            if month < 10:
                month = '0' + str(month)
            else:
                month = str(month)
            url = 'https://apis.data.go.kr/B090041/openapi/service/SpcdeInfoService'
            operation = 'getRestDeInfo'
            params = {'solYear': year, 'solMonth': month}
            #데이터 request
            request_query = self.get_request_query(url, operation, params, mykey)

            get_data = requests.get(request_query)

            if get_data.ok==True:
                soup = BeautifulSoup(get_data.content, 'html.parser')
                item = soup.find_all('item')
                #bs4를 통해 item 파싱
                for day in item:
                    #datetime을 이용하여 weekday 생성, 5:토, 6:일
                    weekday = datetime.strptime(day.locdate.string, '%Y%m%d').weekday()
                    dailyinfo = [day.locdate.string, weekday,day.datename.string, day.isholiday.string]
                    #dailyinfo를 date 리스트에 append
                    date.append(dailyinfo)
        #데이터프레임 만들기                
        df_holiday = pd.DataFrame(date,columns=['logdate', 'weekday','datename', 'isholiday'])
        return df_holiday

if __name__ == "__main__":
    # 여기서 수행시에는 상위 폴더를 환경 변수로 추가후 api 폴더에서 import 해야한다.
    # 현재 파일(__file__)의 절대 경로를 기준으로 상위 폴더 경로를 구함
    parent_dir = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))

    # 시스템 경로에 상위 폴더 추가
    if parent_dir not in sys.path:
        sys.path.append(parent_dir)

    from KisKey import data_go_kr_api_key

    calendar = TradingCalendar()
    res = calendar.get_holiday("2026", data_go_kr_api_key)
    print(res)
