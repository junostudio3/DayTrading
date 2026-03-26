class TradingParams:
    """
    매매 알고리즘에 사용되는 튜닝 가능한 파라미터 모음.
    improvement_work.txt 개선 작업 시 이 값들의 변경 추이를 리포트 상단에 기록하여
    반복적인 쳇바퀴식 수정을 방지한다.
    """

    # ── 매수 필터 ──
    RSI_UPPER_LIMIT = 65            # 과매수 진입 차단 RSI 상한
    EMA20_DEVIATION_MAX = 0.02      # 20EMA 대비 현재가 이격도 상한 (추격매수 방지)
    EMA_GAP_MIN = 0.006             # 20EMA-60EMA 이격도 최소 비율 (추세 확인)
    TREND_VOLUME_RATIO = 1.3        # 추세 매수 거래량 배수 (10봉 평균 대비)
    BREAKOUT_VOLUME_RATIO = 1.5     # 돌파 매수 거래량 배수 (10봉 평균 대비)
    TREND_BULLISH_MIN = 2           # 추세 매수 시 최근 3봉 중 양봉 최소 개수
    MIN_CANDLE_COUNT = 60           # 분석에 필요한 최소 5분봉 개수

    # ── 매도 필터 ──
    TAKE_PROFIT_MIN = 0.015         # 익절 시작 수익률 (이하이면 홀딩)
    TAKE_PROFIT_FORCE = 0.03        # 즉시 익절 수익률

    # ── 손절 필터 ──
    STOP_LOSS_MIN = 0.015           # 최소 손절 비율
    STOP_LOSS_MAX = 0.05            # 최대 손절 비율
    ATR_MULTIPLIER = 2.5            # ATR 기반 손절 배수

    # ── 마감 시간 ──
    FORCE_SELL_HOUR = 15            # 이 시(hour) 이후 무조건 매도
    PURCHASE_OVERTIME_HOUR = 14     # 매수 중단 시(hour)
    PURCHASE_OVERTIME_MIN = 50      # 매수 중단 분(min)

    # ── 주문 타이밍 ──
    BUY_ORDER_TIMEOUT_SECONDS = 120     # 매수 주문 체결 대기 시간(초)
    SELL_ORDER_TIMEOUT_SECONDS = 60     # 매도 주문 체결 대기 시간(초)
    COOLDOWN_AFTER_CANCEL = 600         # 주문 취소 후 재진입 금지 시간(초)
    COOLDOWN_AFTER_SELL = 1800          # 매도 체결 후 재진입 금지 시간(초)

    # ── 종목 선정 필터 ──
    MAX_STOCK_PRICE = 25000         # 관심종목 가격 상한
    MIN_STOCK_PRICE = 7000          # 관심종목 가격 하한

    @classmethod
    def to_report_header(cls) -> str:
        """리포트 파일 상단에 기록할 파라미터 요약 문자열"""
        lines = [
            "=== Trading Parameters ===",
            f"RSI_UPPER_LIMIT={cls.RSI_UPPER_LIMIT}",
            f"EMA20_DEVIATION_MAX={cls.EMA20_DEVIATION_MAX}",
            f"EMA_GAP_MIN={cls.EMA_GAP_MIN}",
            f"TREND_VOLUME_RATIO={cls.TREND_VOLUME_RATIO}",
            f"BREAKOUT_VOLUME_RATIO={cls.BREAKOUT_VOLUME_RATIO}",
            f"TREND_BULLISH_MIN={cls.TREND_BULLISH_MIN}",
            f"MIN_CANDLE_COUNT={cls.MIN_CANDLE_COUNT}",
            f"TAKE_PROFIT_MIN={cls.TAKE_PROFIT_MIN}",
            f"TAKE_PROFIT_FORCE={cls.TAKE_PROFIT_FORCE}",
            f"STOP_LOSS_MIN={cls.STOP_LOSS_MIN}",
            f"STOP_LOSS_MAX={cls.STOP_LOSS_MAX}",
            f"ATR_MULTIPLIER={cls.ATR_MULTIPLIER}",
            f"FORCE_SELL_HOUR={cls.FORCE_SELL_HOUR}",
            f"BUY_ORDER_TIMEOUT={cls.BUY_ORDER_TIMEOUT_SECONDS}s",
            f"SELL_ORDER_TIMEOUT={cls.SELL_ORDER_TIMEOUT_SECONDS}s",
            f"COOLDOWN_AFTER_CANCEL={cls.COOLDOWN_AFTER_CANCEL}s",
            f"COOLDOWN_AFTER_SELL={cls.COOLDOWN_AFTER_SELL}s",
            f"STOCK_PRICE_RANGE={cls.MIN_STOCK_PRICE}~{cls.MAX_STOCK_PRICE}",
            "===========================",
        ]
        return "\n".join(lines)


class SymbolFilter:
    def is_not_interested_by_name(name: str) -> bool:
        if "(A" in name or "(C" in name or "-e" in name or "공모주" in name:
            # 공모펀드 등은 제외한다
            return True
        
        # 이름에 인버스 또는 레버가 포함된 종목은 피한다
        if "인버스" in name or "레버" in name:
            return True
        
        # ETF들은 단타에 적합하지 않으므로 다음으로 시작하는 종목은 제외한다
        if name.startswith("KODEX"):
            return True
        
        if name.startswith("TIGER"):
            return True
        
        if name.startswith("KBSTAR "):
            return True
        
        if name.startswith("RISE "):
            return True
        
        if name.startswith("ACE "):
            return True
        
        if name.startswith("ARIRANG "):
            return True
        
        # 1호,2호,3호,4호,5호의 이름이 포함된 종목도 피한다
        # 이런 종목들은 보통 공모펀드나 리츠 등으로 단타에 적합하지 않다
        for i in range(1, 6):
            if f"{i}호" in name:
                return True

        return False

    def is_not_interested_by_price(price: int) -> bool:
        if price > TradingParams.MAX_STOCK_PRICE:
            return True

        if price <= TradingParams.MIN_STOCK_PRICE:
            return True

        return False
