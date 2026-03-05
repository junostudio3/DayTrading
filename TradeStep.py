from enum import Enum, auto


class TradeStep(Enum):
    JUDGE_STEP = auto()
    DECIDE_ON_PURCHASE = auto()
    WAIT_ACCEPT_PURCHASE = auto()
    DECIDE_ON_SELL = auto()
    WAIT_ACCEPT_SELL = auto()

    def GetAbbreviation(self) -> str:
        if self == TradeStep.JUDGE_STEP:
            return "판단"
        elif self == TradeStep.DECIDE_ON_PURCHASE:
            return "매수결정"
        elif self == TradeStep.WAIT_ACCEPT_PURCHASE:
            return "매수대기"
        elif self == TradeStep.DECIDE_ON_SELL:
            return "매도결정"
        elif self == TradeStep.WAIT_ACCEPT_SELL:
            return "매도대기"
        else:
            return "알 수 없음"