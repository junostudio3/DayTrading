from KisAuth import KisAuth
import enum

class OrderDivision(enum.Enum):
    SETTLE = "00"  # 지정가
    MARKET = "10"  # 시장가

class KisAuthOrder:
    def __init__(self, auth: KisAuth):
        self.auth = auth

    # 매수 주문
    def buy_order_cash(self, symbol: str, quantity: int, price: float, division: OrderDivision = OrderDivision.SETTLE):
        """현금 매수 주문"""
        return self.order_cash(symbol, quantity, price, is_buy=True, division=division)
    
    # 매도 주문
    def sell_order_cash(self, symbol: str, quantity: int, price: float, division: OrderDivision = OrderDivision.SETTLE):
        """현금 매도 주문"""
        return self.order_cash(symbol, quantity, price, is_buy=False, division=division)
    
    def immediately_sell(self, symbol: str, quantity: int):
        """즉시 매도 주문 (시장가)"""
        return self.order_cash(symbol, quantity, price=0, is_buy=False, division=OrderDivision.MARKET)

    # 매수/매도 주문 관련
    def order_cash(self, symbol: str, quantity: int, price: float, is_buy: bool, division: OrderDivision):
        """현금 매수/매도 주문"""

        if self.auth.is_virtual and division == OrderDivision.MARKET:
            # 모의 투자에서는 시장가 주문이 지원되지 않으므로, 지정가 주문으로 대체한다.
            # 시장가 주문 대신 현재가로 지정가 주문을 한다.
            price = int(self.auth.price.get_current(symbol))
            division = OrderDivision.SETTLE

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
            if data.get("rt_cd") == "0":
                return data
            else:
                raise Exception(f"Failed to place {order_type} order: {data.get('msg_cd')} {data.get('msg1')}")
        else:
            raise Exception(f"Failed to place {order_type} order: {response.status_code} {response.text}")
