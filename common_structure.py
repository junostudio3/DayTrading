# StockItem - 주식 종목을 담는 클래스

class SymbolItem:
    def __init__(self, pdno: str, name: str):
        self.pdno = pdno # 종목 코드
        self.prdt_name = name # 종목명


class AccountBalance:
    def __init__(self):
        self.tot_evlu_amt = 0  # 총평가금액
        self.dnca_tot_amt = 0  # 예수금총액
        self.nxdy_excc_amt = 0  # D+1 예수금 (익일정산금액)
        self.prvs_rcdl_excc_amt = 0  # D+2 예수금 (가수도정산금액)
