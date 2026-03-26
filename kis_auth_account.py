from kis_auth import KisAuth
from common_structure import AccountBalance
import requests


class KisAuthAccount:
    def __init__(self, auth: KisAuth, account):
        self.auth = auth
        self.account = account
        self.balance = AccountBalance()
        self.stocks = []  # 주식 잔고 정보
        self.stocks_by_pdno = {}  # {pdno: stock}

    def _rebuild_stocks_by_pdno(self):
        self.stocks_by_pdno = {
            stock.get("pdno", ""): stock
            for stock in self.stocks
            if stock.get("pdno", "")
        }

    def update(self):
        """계좌 정보 업데이트"""

        # 실계좌는 TTTC8434R, 모의계좌는 VTTC8434R
        tr_id = "VTTC8434R" if self.auth.is_virtual else "TTTC8434R"

        response = self.auth.request(
            url="/uapi/domestic-stock/v1/trading/inquire-balance",
            tr_id=tr_id,  # 계좌 정보 조회 트랜잭션 ID
            params={
                "CANO": self.account,  # 계좌번호 체계(8-2)의 앞 8자리
                "ACNT_PRDT_CD": "01",  # 계좌번호 체계(8-2)의 뒤 2자리
                "AFHR_FLPR_YN": "N",  # 시간외단일가, 거래소 여부 (N: 기본값)
                "FUND_STTL_ICLD_YN" : "N", # 펀드결제분포함 여부
                "PRCS_DVSN" : "00", # 처리구분 (00: 전일매매포함, 01: 전일매매제외)
                "CTX_AREA_FK100" : "", # 연속조회검색조건100
                "CTX_AREA_NK100" : "", # 연속조회키100

                # 변경이 필요없는 고정값
                "FNCG_AMT_AUTO_RDPT_YN" : "N",
                "OFL_YN" : "", # 오프라인 여부 (공란)
                "INQR_DVSN": "01",
                "UNPR_DVSN": "01",
            }
        )

        if response.status_code == 200:
            data = response.json()
            if data.get("rt_cd") == "0" and "output2" in data:
                output = data["output2"]
                # output은 리스트 형태이다.
                if isinstance(output, list) and len(output) > 0:
                    item = output[0]  # 첫 번째 항목을 사용
                    if item.get("tot_evlu_amt") is not None:
                        self.balance.tot_evlu_amt = float(item.get("tot_evlu_amt", 0)) # 총평가금액
                    if item.get("dnca_tot_amt") is not None:
                        self.balance.dnca_tot_amt = float(item.get("dnca_tot_amt", 0)) # 예수금총액
                    if item.get("nxdy_excc_amt") is not None:
                        self.balance.nxdy_excc_amt = float(item.get("nxdy_excc_amt", 0)) # 익일정산금액
                    if item.get("prvs_rcdl_excc_amt") is not None:
                        self.balance.prvs_rcdl_excc_amt = float(item.get("prvs_rcdl_excc_amt", 0)) # 가수도정산금액

    def update_stock(self):
        """주식 잔고 정보 업데이트"""
        tr_id = "VTTC8434R" if self.auth.is_virtual else "TTTC8434R"

        response = self.auth.request(
            url="/uapi/domestic-stock/v1/trading/inquire-balance",
            tr_id=tr_id,  # 계좌 정보 조회 트랜잭션 ID
            params={
                "CANO": self.account,  # 계좌번호 체계(8-2)의 앞 8자리
                "ACNT_PRDT_CD": "01",  # 계좌번호 체계(8-2)의 뒤 2자리
                "AFHR_FLPR_YN": "N",  # 시간외단일가, 거래소 여부 (N: 기본값)
                "FUND_STTL_ICLD_YN" : "N", # 펀드결제분포함 여부
                "PRCS_DVSN" : "00", # 처리구분 (00: 전일매매포함, 01: 전일매매제외)
                "CTX_AREA_FK100" : "", # 연속조회검색조건100
                "CTX_AREA_NK100" : "", # 연속조회키100

                # 변경이 필요없는 고정값
                "FNCG_AMT_AUTO_RDPT_YN" : "N",
                "OFL_YN" : "", # 오프라인 여부 (공란)
                "INQR_DVSN": "01",
                "UNPR_DVSN": "01",
            }
        )
        if response.status_code == 200:
            data = response.json()
            if data.get("rt_cd") == "0" and "output1" in data:
                output = data["output1"]
                # output은 리스트 형태이다.
                if isinstance(output, list):
                    self.stocks = output  # 잔고 정보 저장
                    self._rebuild_stocks_by_pdno()
                else:
                    self.stocks = []  # 잔고 정보가 없으면 빈 리스트로 초기화
                    self._rebuild_stocks_by_pdno()
            else:
                self.stocks = []  # 잔고 정보가 없으면 빈 리스트로 초기화
                self._rebuild_stocks_by_pdno()
        else:
            self.stocks = []  # 잔고 정보가 없으면 빈 리스트로 초기화
            self._rebuild_stocks_by_pdno()
            raise Exception(f"Failed to update stock balance: {response.status_code} {response.text}")
