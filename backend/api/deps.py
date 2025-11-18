from fastapi import HTTPException, Query
from datetime import datetime
from typing import List, Optional

def parse_bbox(bbox_str: str) -> List[float]:
    try:
        parts = [float(p) for p in bbox_str.split(",")]
        assert len(parts) == 4
        lonmin, latmin, lonmax, latmax = parts
        if lonmin >= lonmax or latmin >= latmax:
            raise ValueError
        return parts
    except Exception:
        raise HTTPException(400, "bbox must be 'lonmin,latmin,lonmax,latmax'")

def validate_date(s: str, name: str) -> str:
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return s
    except ValueError:
        raise HTTPException(400, f"{name} must be YYYY-MM-DD")

# ===== Зависимости для FastAPI =====
def BBox(bbox: str = Query(..., description="lonmin,latmin,lonmax,latmax")) -> List[float]:
    return parse_bbox(bbox)

def Date(name: str):
    def _dep(**kwargs) -> str:
        # Получаем значение по имени параметра
        value = kwargs.get(name)
        if value is None:
            raise HTTPException(400, f"{name} is required")
        return validate_date(value, name)
    
    # Устанавливаем правильную сигнатуру для FastAPI
    from inspect import Parameter, Signature
    _dep.__signature__ = Signature([
        Parameter(name, Parameter.POSITIONAL_OR_KEYWORD, 
                 default=Query(..., description="YYYY-MM-DD"))
    ])
    return _dep

def OptionalDate(name: str):
    def _dep(**kwargs) -> Optional[str]:
        # Получаем значение по имени параметра
        value = kwargs.get(name)
        if value is None:
            return None
        return validate_date(value, name)
    
    # Устанавливаем правильную сигнатуру для FastAPI
    from inspect import Parameter, Signature
    _dep.__signature__ = Signature([
        Parameter(name, Parameter.POSITIONAL_OR_KEYWORD, 
                 default=Query(None, description="YYYY-MM-DD"))
    ])
    return _dep