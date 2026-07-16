from dataclasses import dataclass

@dataclass
class SwingIndicator:
    avg_5d: float = 0.0
    avg_20d: float = 0.0
    avg_30d: float = 0.0
    avg_vol_5d: float = 0.0
    valid: bool = False
