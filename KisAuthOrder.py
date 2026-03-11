from KisAuth import KisAuth
import enum
import datetime
from typing import List, Optional


class OrderDivision(enum.Enum):
    SETTLE = "00"  # 지정가
    MARKET = "10"  # 시장가


class OrderCheckResult:
    def __init__(self):
        self.ord_unpr = 0  # 주문 가격
        self.rmn_qty = 0  # 잔량
        self.tot_ccld_qty = 0  # 총 체결 수량

    def add(self, other):
        if self.ord_unpr != other.ord_unpr:
            raise ValueError("주문 가격이 다릅니다.")

        self.rmn_qty += other.rmn_qty
        self.tot_ccld_qty += other.tot_ccld_qty

class KisAuthOrder:
    def __init__(self, auth: KisAuth):
        self.auth = auth

    # 매수 주문
    def buy_order_cash(self, pdno: str, quantity: int, price: int, division: OrderDivision = OrderDivision.SETTLE):
        """현금 매수 주문"""
        return self.order_cash(pdno, quantity, price, is_buy=True, division=division)
    
    # 매도 주문
    def sell_order_cash(self, pdno: str, quantity: int, price: int, division: OrderDivision = OrderDivision.SETTLE):
        """현금 매도 주문"""
        return self.order_cash(pdno, quantity, price, is_buy=False, division=division)
    
    def immediately_sell(self, pdno: str, quantity: int):
        """즉시 매도 주문 (시장가)"""
        return self.order_cash(pdno, quantity, price=0, is_buy=False, division=OrderDivision.MARKET)
    
    # 매수/매도 체결 확인
    def order_check(self, pd_no: str, order_no: str, is_buy: bool) -> List[OrderCheckResult]:
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
                results = []
                for item in data["output1"]:
                    result = OrderCheckResult()
                    result.ord_unpr = int(item.get("ord_unpr", 0))
                    result.rmn_qty = int(item.get("rmn_qty", 0))
                    result.tot_ccld_qty = int(item.get("tot_ccld_qty", 0))
                    results.append(result)
                return results

        raise Exception(f"Failed to check order: {response.status_code} {response.text}")
    
    # 주문 취소
    def cancel_order(self, order_no: str):
        """주문 취소"""

        tr_id = "VTTC0013U" if self.auth.is_virtual else "TTTC0013U"

        response = self.auth.request_post(
            url="/uapi/domestic-stock/v1/trading/order-rvsecncl",
            tr_id=tr_id,  # 주문 취소 트랜잭션 ID
            headers={
                "content-type": "application/json; charset=utf-8",
            },
            params={
                "CANO": self.auth.account.account,  # 계좌번호 체계(8-2)의 앞 8자리
                "ACNT_PRDT_CD": "01",  # 계좌번호 체계(8-2)의 뒤 2자리
                "KRX_FWDG_ORD_ORGNO": order_no,  # 한국거래소 주문번호 (주문 시 반환되는 주문번호)
                "ORGN_ODNO": order_no,  # 주문번호
                "ORD_DVSN": "00", # 주문구분 00: 지정가 이나 정정이 아니라 취소할 것이므로 의미 없음
                "RVSE_CNCL_DVSN_CD" : "02", # 정정취소구분코드 01: 정정, 02: 취소
                "ORD_QTY": "0", # 주문수량 (전부 취소할것이므로 의미 없음)
                "ORD_UNPR": "0", # 주문가격 (전부 취소할것이므로 의미 없음)
                "QTY_ALL_ORD_YN": "Y", # 잔량전부주문여부 (Y: 전량, N: 일부)
            }
        )

        if response.status_code == 200:
            data = response.json()
            if data.get("rt_cd") == "0":
                return True
            else:
                raise Exception(f"Failed to cancel order: {data.get('msg_cd')} {data.get('msg1')}")
        else:
            raise Exception(f"Failed to cancel order: {response.status_code} {response.text}")

    # 매수/매도 주문 관련
    def order_cash(self, pdno: str, quantity: int, price: int, is_buy: bool, division: OrderDivision):
        """현금 매수/매도 주문"""

        if self.auth.is_virtual and division == OrderDivision.MARKET:
            # 모의 투자에서는 시장가 주문이 지원되지 않으므로, 지정가 주문으로 대체한다.
            # 시장가 주문 대신 현재가 - 500원 (매수) 또는 현재가 + 500원 (매도)로 지정가 주문을 한다.
            candle = self.auth.price.get_one_minute_candlestick(pdno, datetime.datetime.now().hour, datetime.datetime.now().minute)
            if candle and len(candle) > 0 and "stck_prpr" in candle[0]:
                if is_buy:
                    price = max(int(candle[0]["stck_prpr"]) + 500, 100)
                else:
                    price = max(int(candle[0]["stck_prpr"]) - 500, 100) 
                division = OrderDivision.SETTLE
            else:
                raise ValueError("캔들스틱 데이터를 가져오지 못했습니다.")

        params = {
            "CANO": self.auth.account.account,  # 계좌번호 체계(8-2)의 앞 8자리
            "ACNT_PRDT_CD": "01",  # 계좌번호 체계(8-2)의 뒤 2자리
            "PDNO": pdno,  # 종목번호
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
