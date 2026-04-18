"""
KOSDAQ 종목 마스터 파일(kosdaq_code.mst) 파서
구조체 ST_KSQ_CODE 기반으로 파싱
레코드 크기: 282 bytes + \n = 283 bytes
"""

import os
from dataclasses import dataclass
from typing import List, Optional
from filter import SymbolFilter

# ──────────────────────────────────────────────
# 필드 정의 (이름, 바이트 길이)
# ──────────────────────────────────────────────
_FIELDS = [
    ("mksc_shrn_iscd",       9),   # 단축코드
    ("stnd_iscd",           12),   # 표준코드
    ("hts_kor_isnm",        40),   # 한글종목명
    ("scrt_grp_cls_code",    2),   # 증권그룹구분코드
    ("avls_scal_cls_code",   1),   # 시가총액 규모 구분 코드
    ("bstp_larg_div_code",   4),   # 지수업종 대분류 코드
    ("bstp_medm_div_code",   4),   # 지수 업종 중분류 코드
    ("bstp_smal_div_code",   4),   # 지수업종 소분류 코드
    ("vntr_issu_yn",         1),   # 벤처기업 여부
    ("low_current_yn",       1),   # 저유동성종목 여부
    ("krx_issu_yn",          1),   # KRX 종목 여부
    ("etp_prod_cls_code",    1),   # ETP 상품구분코드
    ("krx100_issu_yn",       1),   # KRX100 종목 여부
    ("krx_car_yn",           1),   # KRX 자동차 여부
    ("krx_smcn_yn",          1),   # KRX 반도체 여부
    ("krx_bio_yn",           1),   # KRX 바이오 여부
    ("krx_bank_yn",          1),   # KRX 은행 여부
    ("etpr_undt_objt_co_yn", 1),   # 기업인수목적회사여부
    ("krx_enrg_chms_yn",     1),   # KRX 에너지 화학 여부
    ("krx_stel_yn",          1),   # KRX 철강 여부
    ("short_over_cls_code",  1),   # 단기과열종목구분코드
    ("krx_medi_cmnc_yn",     1),   # KRX 미디어 통신 여부
    ("krx_cnst_yn",          1),   # KRX 건설 여부
    ("invt_alrm_yn",         1),   # 투자주의환기종목여부
    ("krx_scrt_yn",          1),   # KRX 증권 구분
    ("krx_ship_yn",          1),   # KRX 선박 구분
    ("krx_insu_yn",          1),   # KRX섹터지수 보험여부
    ("krx_trnp_yn",          1),   # KRX섹터지수 운송여부
    ("ksq150_nmix_yn",       1),   # KOSDAQ150지수여부
    ("stck_sdpr",            9),   # 주식 기준가
    ("frml_mrkt_deal_qty_unit", 5),# 정규 시장 매매 수량 단위
    ("ovtm_mrkt_deal_qty_unit", 5),# 시간외 시장 매매 수량 단위
    ("trht_yn",              1),   # 거래정지 여부
    ("sltr_yn",              1),   # 정리매매 여부
    ("mang_issu_yn",         1),   # 관리 종목 여부
    ("mrkt_alrm_cls_code",   2),   # 시장 경고 구분 코드
    ("mrkt_alrm_risk_adnt_yn", 1), # 시장 경고위험 예고 여부
    ("insn_pbnt_yn",         1),   # 불성실 공시 여부
    ("byps_lstn_yn",         1),   # 우회 상장 여부
    ("flng_cls_code",        2),   # 락구분 코드
    ("fcam_mod_cls_code",    2),   # 액면가 변경 구분 코드
    ("icic_cls_code",        2),   # 증자 구분 코드
    ("marg_rate",            3),   # 증거금 비율
    ("crdt_able",            1),   # 신용주문 가능 여부
    ("crdt_days",            3),   # 신용기간
    ("prdy_vol",            12),   # 전일 거래량
    ("stck_fcam",           12),   # 주식 액면가
    ("stck_lstn_date",       8),   # 주식 상장 일자
    ("lstn_stcn",           15),   # 상장 주수(천)
    ("cpfn",                21),   # 자본금
    ("stac_month",           2),   # 결산 월
    ("po_prc",               7),   # 공모 가격
    ("prst_cls_code",        1),   # 우선주 구분 코드
    ("ssts_hot_yn",          1),   # 공매도과열종목여부
    ("stange_runup_yn",      1),   # 이상급등종목여부
    ("krx300_issu_yn",       1),   # KRX300 종목 여부
    ("sale_account",         9),   # 매출액
    ("bsop_prfi",            9),   # 영업이익
    ("op_prfi",              9),   # 경상이익
    ("thtr_ntin",            5),   # 당기순이익
    ("roe",                  9),   # ROE(자기자본이익률)
    ("base_date",            8),   # 기준년월
    ("prdy_avls_scal",       9),   # 전일기준 시가총액 (억)
    ("grp_code",             3),   # 그룹사 코드
    ("co_crdt_limt_over_yn", 1),   # 회사신용한도초과여부
    ("secu_lend_able_yn",    1),   # 담보대출가능여부
    ("stln_able_yn",         1),   # 대주가능여부
]

RECORD_SIZE = sum(size for _, size in _FIELDS)  # 282
RECORD_SIZE_WITH_LF = RECORD_SIZE + 1            # 283 (레코드 끝 \n 포함)
ENCODING = "cp949"

# ──────────────────────────────────────────────
# 데이터 클래스
# ──────────────────────────────────────────────
@dataclass
class KosdaqCode:
    mksc_shrn_iscd: str        # 단축코드
    stnd_iscd: str             # 표준코드
    hts_kor_isnm: str          # 한글종목명
    scrt_grp_cls_code: str     # 증권그룹구분코드
    avls_scal_cls_code: str    # 시가총액 규모 구분
    bstp_larg_div_code: str    # 지수업종 대분류
    bstp_medm_div_code: str    # 지수업종 중분류
    bstp_smal_div_code: str    # 지수업종 소분류
    vntr_issu_yn: str          # 벤처기업 여부
    low_current_yn: str        # 저유동성종목 여부
    krx_issu_yn: str           # KRX 종목 여부
    etp_prod_cls_code: str     # ETP 상품구분코드
    krx100_issu_yn: str        # KRX100 종목 여부
    krx_car_yn: str            # KRX 자동차 여부
    krx_smcn_yn: str           # KRX 반도체 여부
    krx_bio_yn: str            # KRX 바이오 여부
    krx_bank_yn: str           # KRX 은행 여부
    etpr_undt_objt_co_yn: str  # 기업인수목적회사여부
    krx_enrg_chms_yn: str      # KRX 에너지 화학 여부
    krx_stel_yn: str           # KRX 철강 여부
    short_over_cls_code: str   # 단기과열종목구분코드
    krx_medi_cmnc_yn: str      # KRX 미디어 통신 여부
    krx_cnst_yn: str           # KRX 건설 여부
    invt_alrm_yn: str          # 투자주의환기종목여부
    krx_scrt_yn: str           # KRX 증권 구분
    krx_ship_yn: str           # KRX 선박 구분
    krx_insu_yn: str           # KRX섹터지수 보험여부
    krx_trnp_yn: str           # KRX섹터지수 운송여부
    ksq150_nmix_yn: str        # KOSDAQ150지수여부
    stck_sdpr: str             # 주식 기준가
    frml_mrkt_deal_qty_unit: str  # 정규 시장 매매 수량 단위
    ovtm_mrkt_deal_qty_unit: str  # 시간외 시장 매매 수량 단위
    trht_yn: str               # 거래정지 여부
    sltr_yn: str               # 정리매매 여부
    mang_issu_yn: str          # 관리 종목 여부
    mrkt_alrm_cls_code: str    # 시장 경고 구분 코드
    mrkt_alrm_risk_adnt_yn: str # 시장 경고위험 예고 여부
    insn_pbnt_yn: str          # 불성실 공시 여부
    byps_lstn_yn: str          # 우회 상장 여부
    flng_cls_code: str         # 락구분 코드
    fcam_mod_cls_code: str     # 액면가 변경 구분 코드
    icic_cls_code: str         # 증자 구분 코드
    marg_rate: str             # 증거금 비율
    crdt_able: str             # 신용주문 가능 여부
    crdt_days: str             # 신용기간
    prdy_vol: str              # 전일 거래량
    stck_fcam: str             # 주식 액면가
    stck_lstn_date: str        # 주식 상장 일자
    lstn_stcn: str             # 상장 주수(천)
    cpfn: str                  # 자본금
    stac_month: str            # 결산 월
    po_prc: str                # 공모 가격
    prst_cls_code: str         # 우선주 구분 코드
    ssts_hot_yn: str           # 공매도과열종목여부
    stange_runup_yn: str       # 이상급등종목여부
    krx300_issu_yn: str        # KRX300 종목 여부
    sale_account: str          # 매출액
    bsop_prfi: str             # 영업이익
    op_prfi: str               # 경상이익
    thtr_ntin: str             # 당기순이익
    roe: str                   # ROE(자기자본이익률)
    base_date: str             # 기준년월
    prdy_avls_scal: str        # 전일기준 시가총액 (억)
    grp_code: str              # 그룹사 코드
    co_crdt_limt_over_yn: str  # 회사신용한도초과여부
    secu_lend_able_yn: str     # 담보대출가능여부
    stln_able_yn: str          # 대주가능여부


# ──────────────────────────────────────────────
# 파서 함수
# ──────────────────────────────────────────────
def _parse_record(raw: bytes) -> KosdaqCode:
    """282바이트 원시 레코드 → KosdaqCode 객체"""
    values = {}
    offset = 0
    for name, size in _FIELDS:
        chunk = raw[offset: offset + size]
        # 한글종목명은 CP949, 나머지는 ASCII
        if name == "hts_kor_isnm":
            text = chunk.decode(ENCODING, errors="replace").strip()
        else:
            text = chunk.decode("ascii", errors="replace").strip()
        values[name] = text
        offset += size
    return KosdaqCode(**values)


def load_kosdaq_master(filepath: str = None) -> List[KosdaqCode]:
    """
    KOSDAQ 종목 마스터 파일을 읽어 KosdaqCode 리스트를 반환한다.

    Parameters
    ----------
    filepath : str, optional
        MST 파일 경로. None이면 기본 경로(./information/kosdaq_code.mst)를 사용한다.

    Returns
    -------
    List[KosdaqCode]
        파싱된 종목 정보 리스트
    """
    if filepath is None:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        filepath = os.path.join(base_dir, "cache", "information", "kosdaq_code.mst")

    records: List[KosdaqCode] = []

    with open(filepath, "rb") as f:
        while True:
            raw = f.read(RECORD_SIZE_WITH_LF)
            if not raw:
                break
            if len(raw) < RECORD_SIZE:
                break  # 불완전한 레코드 무시
            record = _parse_record(raw[:RECORD_SIZE])
            name = record.hts_kor_isnm
            if SymbolFilter.is_not_interested_by_name(name):
                continue
            if SymbolFilter.is_not_interested_by_record(record):
                continue
            records.append(record)

    return records


def find_by_code(code: str, records: List[KosdaqCode]) -> Optional[KosdaqCode]:
    """단축코드 또는 표준코드로 종목 검색"""
    code = code.strip()
    for r in records:
        if r.mksc_shrn_iscd == code or r.stnd_iscd == code:
            return r
    return None


def find_kosdaq_by_name(name: str, records: List[KosdaqCode]) -> List[KosdaqCode]:
    """한글종목명 부분 문자열로 종목 검색"""
    return [r for r in records if name in r.hts_kor_isnm]


# ──────────────────────────────────────────────
# 간단한 동작 확인 (직접 실행 시)
# ──────────────────────────────────────────────
if __name__ == "__main__":
    records = load_kosdaq_master()
    print(f"총 {len(records)}개 종목 로드 완료")

    # 앞 5개 출력
    for r in records[:5]:
        print(f"  [{r.mksc_shrn_iscd}] {r.hts_kor_isnm} / 상장일:{r.stck_lstn_date} / 기준가:{r.stck_sdpr}")

    # 인텍플러스 검색
    print("\n인텍플러스 검색:")
    results = find_kosdaq_by_name("인텍플러스", records)
    for r in results:
        print(f"  [{r.mksc_shrn_iscd}] {r.hts_kor_isnm} / 상장일:{r.stck_lstn_date} / 기준가:{r.stck_sdpr}")
