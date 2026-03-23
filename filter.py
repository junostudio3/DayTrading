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
        # 가격이 너무 큰 종목은 피한다 (하드코딩)
        if price > 25000:
            return True

        # 가격이 너무 낮은 종목은 % 계산시 작은 값으로도 큰 변동이 발생할 수 있으므로 피한다 (하드코딩)
        if price <= 7000:
            return True

        return False
