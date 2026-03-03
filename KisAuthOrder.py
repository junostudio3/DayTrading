from KisAuth import KisAuth
import enum
import datetime

class OrderDivision(enum.Enum):
    SETTLE = "00"  # 지정가
    MARKET = "10"  # 시장가

class KisAuthOrder:
    def __init__(self, auth: KisAuth):
        self.auth = auth

    # 매수 주문
    def buy_order_cash(self, symbol: str, quantity: int, price: int, division: OrderDivision = OrderDivision.SETTLE):
        """현금 매수 주문"""
        return self.order_cash(symbol, quantity, price, is_buy=True, division=division)
    
    # 매도 주문
    def sell_order_cash(self, symbol: str, quantity: int, price: int, division: OrderDivision = OrderDivision.SETTLE):
        """현금 매도 주문"""
        return self.order_cash(symbol, quantity, price, is_buy=False, division=division)
    
    def immediately_sell(self, symbol: str, quantity: int):
        """즉시 매도 주문 (시장가)"""
        return self.order_cash(symbol, quantity, price=0, is_buy=False, division=OrderDivision.MARKET)
    
    # 매수/매도 체결 확인
    def order_check(self, pd_no: str, order_no: str, is_buy: bool):
        """주문 체결 확인"""

        tr_id = "VTTC0081R" if self.auth.is_virtual else "TTTC0081R"
        today = datetime.datetime.now().strftime("%Y%m%d")

        response = self.auth.request(
            url="/uapi/domestic-stock/v1/trading/inquire-daily-ccld",
            tr_id=tr_id,  # 주문 상세 조회 트랜잭션 ID
            params={
                "CANO": self.auth.account.account,  # 계좌번호 체계(8-2)의 앞 8자리
                "ACNT_PRDT_CD": "01",  # 계좌번호 체계(8-2)의 뒤 2자리
                "INQR_STRT_DT": today,  # 조회 시작일 (YYYYMMDD)
                "INQR_END_DT": today,  # 조회 종료일 (YYYYMMDD)
                "SLL_BUY_DVSN_CD": "02" if is_buy else "01",  # 매도/매수 구분 코드 (00: 전체, 01: 매도, 02: 매수)
                "INQR_DVSN": "00",  # 조회 구분 (00: 역순, 01: 순차)
                "PDNO": pd_no, # 종목번호
                "CCLD_DVSN": "00",  # 체결 구분 (00: 전체, 01: 체결, 02: 미체결)
                "ORD_GNO_BRNO": "", # 주문시 한국투자증권 시스템에서 지정된 영업점코드
                "ODNO": order_no, # 주문번호
                "INQR_DVSN_3": "00", # 조회구분3 (00: 전체, 01: 현금, 02: 융자, 03: 대출, 04: 대주)
                "INQR_DVSN_1": "", # 연속조회구분1 (공란)
                "CTX_AREA_FK100": "", # 연속조회검색조건100 (공란)
                "CTX_AREA_NK100": "", # 연속조회키100 (공란)
            }
        )

        if response.status_code == 200:
            data = response.json()
            if data.get("rt_cd") == "0" and "output1" in data:
                return data["output1"]

        raise Exception(f"Failed to check order: {response.status_code} {response.text}")

    # 매수/매도 주문 관련
    def order_cash(self, symbol: str, quantity: int, price: int, is_buy: bool, division: OrderDivision):
        """현금 매수/매도 주문"""

        if self.auth.is_virtual and division == OrderDivision.MARKET:
            # 모의 투자에서는 시장가 주문이 지원되지 않으므로, 지정가 주문으로 대체한다.
            # 시장가 주문 대신 현재가로 지정가 주문을 한다.
            candle = self.auth.price.get_one_minute_candlestick(symbol, datetime.datetime.now().hour, datetime.datetime.now().minute)
            if candle and len(candle) > 0 and "stck_prpr" in candle[0]:
                price = int(candle[0]["stck_prpr"])
                division = OrderDivision.SETTLE
            else:
                raise ValueError("캔들스틱 데이터를 가져오지 못했습니다.")

        params = {
            "CANO": self.auth.account.account,  # 계좌번호 체계(8-2)의 앞 8자리
            "ACNT_PRDT_CD": "01",  # 계좌번호 체계(8-2)의 뒤 2자리
            "PDNO": symbol,  # 종목번호
            "ORD_DVSN": division.value,
            "ORD_QTY": str(quantity),  # 주문수량
            "ORD_UNPR": str(price),  # 주문가격
            #"EXCG_ID_DVSN_CD": "KRX",  # 거래소 구분 코드 (KRX: 한국거래소) 미지정시 KRX로 간주
        }

        if is_buy:
            order_type = "buy"
            trid = "VTTC0012U" if self.auth.is_virtual else "TTTC0012U"
        else:
            order_type = "sell"
            trid = "VTTC0011U" if self.auth.is_virtual else "TTTC0011U"

        response = self.auth.request_post("/uapi/domestic-stock/v1/trading/order-cash", trid, headers={
            "content-type": "application/json; charset=utf-8",
        }, params=params)

        if response.status_code == 200:
            data = response.json()
            if data.get("rt_cd") == "0" and "output" in data:
                return data["output"]
            else:
                raise Exception(f"Failed to place {order_type} order: {data.get('msg_cd')} {data.get('msg1')}")
        else:
            raise Exception(f"Failed to place {order_type} order: {response.status_code} {response.text}")
