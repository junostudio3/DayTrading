"""
KOSPI 종목 마스터 파일(kospi_code.mst) 파서
구조체 ST_KSP_CODE 기반으로 파싱
레코드 크기: 288 bytes + \n = 289 bytes
"""

import os
from dataclasses import dataclass
from filter import SymbolFilter
from typing import List, Optional

# ──────────────────────────────────────────────
# 필드 정의 (이름, 바이트 길이)
# ──────────────────────────────────────────────
_FIELDS = [
		("mksc_shrn_iscd", 9),
		("stnd_iscd", 12),
		("hts_kor_isnm", 40),
		("scrt_grp_cls_code", 2),
		("avls_scal_cls_code", 1),
		("bstp_larg_div_code", 4),
		("bstp_medm_div_code", 4),
		("bstp_smal_div_code", 4),
		("mnin_cls_code_yn", 1),
		("low_current_yn", 1),
		("sprn_strr_nmix_issu_yn", 1),
		("kospi200_apnt_cls_code", 1),
		("kospi100_issu_yn", 1),
		("kospi50_issu_yn", 1),
		("krx_issu_yn", 1),
		("etp_prod_cls_code", 1),
		("elw_pblc_yn", 1),
		("krx100_issu_yn", 1),
		("krx_car_yn", 1),
		("krx_smcn_yn", 1),
		("krx_bio_yn", 1),
		("krx_bank_yn", 1),
		("etpr_undt_objt_co_yn", 1),
		("krx_enrg_chms_yn", 1),
		("krx_stel_yn", 1),
		("short_over_cls_code", 1),
		("krx_medi_cmnc_yn", 1),
		("krx_cnst_yn", 1),
		("krx_fnnc_svc_yn", 1),
		("krx_scrt_yn", 1),
		("krx_ship_yn", 1),
		("krx_insu_yn", 1),
		("krx_trnp_yn", 1),
		("sri_nmix_yn", 1),
		("stck_sdpr", 9),
		("frml_mrkt_deal_qty_unit", 5),
		("ovtm_mrkt_deal_qty_unit", 5),
		("trht_yn", 1),
		("sltr_yn", 1),
		("mang_issu_yn", 1),
		("mrkt_alrm_cls_code", 2),
		("mrkt_alrm_risk_adnt_yn", 1),
		("insn_pbnt_yn", 1),
		("byps_lstn_yn", 1),
		("flng_cls_code", 2),
		("fcam_mod_cls_code", 2),
		("icic_cls_code", 2),
		("marg_rate", 3),
		("crdt_able", 1),
		("crdt_days", 3),
		("prdy_vol", 12),
		("stck_fcam", 12),
		("stck_lstn_date", 8),
		("lstn_stcn", 15),
		("cpfn", 21),
		("stac_month", 2),
		("po_prc", 7),
		("prst_cls_code", 1),
		("ssts_hot_yn", 1),
		("stange_runup_yn", 1),
		("krx300_issu_yn", 1),
		("kospi_issu_yn", 1),
		("sale_account", 9),
		("bsop_prfi", 9),
		("op_prfi", 9),
		("thtr_ntin", 5),
		("roe", 9),
		("base_date", 8),
		("prdy_avls_scal", 9),
		("grp_code", 3),
		("co_crdt_limt_over_yn", 1),
		("secu_lend_able_yn", 1),
		("stln_able_yn", 1),
]

RECORD_SIZE = sum(size for _, size in _FIELDS)  # 288
RECORD_SIZE_WITH_LF = RECORD_SIZE + 1  # 289 (레코드 끝 \n 포함)
ENCODING = "cp949"


@dataclass
class KospiCode:
		mksc_shrn_iscd: str
		stnd_iscd: str
		hts_kor_isnm: str
		scrt_grp_cls_code: str
		avls_scal_cls_code: str
		bstp_larg_div_code: str
		bstp_medm_div_code: str
		bstp_smal_div_code: str
		mnin_cls_code_yn: str
		low_current_yn: str
		sprn_strr_nmix_issu_yn: str
		kospi200_apnt_cls_code: str
		kospi100_issu_yn: str
		kospi50_issu_yn: str
		krx_issu_yn: str
		etp_prod_cls_code: str
		elw_pblc_yn: str
		krx100_issu_yn: str
		krx_car_yn: str
		krx_smcn_yn: str
		krx_bio_yn: str
		krx_bank_yn: str
		etpr_undt_objt_co_yn: str
		krx_enrg_chms_yn: str
		krx_stel_yn: str
		short_over_cls_code: str
		krx_medi_cmnc_yn: str
		krx_cnst_yn: str
		krx_fnnc_svc_yn: str
		krx_scrt_yn: str
		krx_ship_yn: str
		krx_insu_yn: str
		krx_trnp_yn: str
		sri_nmix_yn: str
		stck_sdpr: str
		frml_mrkt_deal_qty_unit: str
		ovtm_mrkt_deal_qty_unit: str
		trht_yn: str
		sltr_yn: str
		mang_issu_yn: str
		mrkt_alrm_cls_code: str
		mrkt_alrm_risk_adnt_yn: str
		insn_pbnt_yn: str
		byps_lstn_yn: str
		flng_cls_code: str
		fcam_mod_cls_code: str
		icic_cls_code: str
		marg_rate: str
		crdt_able: str
		crdt_days: str
		prdy_vol: str
		stck_fcam: str
		stck_lstn_date: str
		lstn_stcn: str
		cpfn: str
		stac_month: str
		po_prc: str
		prst_cls_code: str
		ssts_hot_yn: str
		stange_runup_yn: str
		krx300_issu_yn: str
		kospi_issu_yn: str
		sale_account: str
		bsop_prfi: str
		op_prfi: str
		thtr_ntin: str
		roe: str
		base_date: str
		prdy_avls_scal: str
		grp_code: str
		co_crdt_limt_over_yn: str
		secu_lend_able_yn: str
		stln_able_yn: str


def _parse_record(raw: bytes) -> KospiCode:
		"""288바이트 원시 레코드 → KospiCode 객체"""
		values = {}
		offset = 0
		for name, size in _FIELDS:
				chunk = raw[offset: offset + size]
				if name == "hts_kor_isnm":
						text = chunk.decode(ENCODING, errors="replace").strip()
				else:
						text = chunk.decode("ascii", errors="replace").strip()
				values[name] = text
				offset += size
		return KospiCode(**values)


def load_kospi_master(filepath: str = None) -> List[KospiCode]:
		"""
		KOSPI 종목 마스터 파일을 읽어 KospiCode 리스트를 반환한다.

		Parameters
		----------
		filepath : str, optional
			MST 파일 경로. None이면 기본 경로(./information/kospi_code.mst)를 사용한다.

		Returns
		-------
		List[KospiCode]
			파싱된 종목 정보 리스트
		"""
		if filepath is None:
				base_dir = os.path.dirname(os.path.abspath(__file__))
				filepath = os.path.join(base_dir, "information", "kospi_code.mst")

		records: List[KospiCode] = []

		with open(filepath, "rb") as f:
				while True:
					raw = f.read(RECORD_SIZE_WITH_LF)
					if not raw:
							break
					if len(raw) < RECORD_SIZE:
							break
					record = _parse_record(raw[:RECORD_SIZE])
					name = record.hts_kor_isnm
					if SymbolFilter.is_not_interested_by_name(name):
							continue

					records.append(record)

		return records


def find_by_code(code: str, records: List[KospiCode]) -> Optional[KospiCode]:
		"""단축코드 또는 표준코드로 종목 검색"""
		code = code.strip()
		for record in records:
				if record.mksc_shrn_iscd == code or record.stnd_iscd == code:
						return record
		return None


def find_kospi_by_name(name: str, records: List[KospiCode]) -> List[KospiCode]:
		"""한글종목명 동일한 종목 검색 """
		return [record for record in records if record.hts_kor_isnm == name.strip()]


if __name__ == "__main__":
		records = load_kospi_master()
		print(f"총 {len(records)}개 종목 로드 완료")

		for record in records[:5]:
				print(
					f"  [{record.mksc_shrn_iscd}] {record.hts_kor_isnm} "
					f"/ 상장일:{record.stck_lstn_date} / 기준가:{record.stck_sdpr}"
				)

				print("\n삼성전자 검색:")
				results = find_kospi_by_name("삼성전자", records)
				for record in results:
						print(
							f"  [{record.mksc_shrn_iscd}] {record.hts_kor_isnm} "
							f"/ 상장일:{record.stck_lstn_date} / 기준가:{record.stck_sdpr}"
						)
