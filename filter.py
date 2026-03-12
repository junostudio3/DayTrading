class SymbolFilter:
    def is_not_interested(name: str) -> bool:
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

        return False
