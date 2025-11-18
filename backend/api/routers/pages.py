# backend/api/routers/pages.py
from fastapi import APIRouter
from fastapi.responses import FileResponse
from pathlib import Path

router = APIRouter()
FRONT_DIR = Path(__file__).resolve().parents[3] / "frontend"
ASSETS_DIR = FRONT_DIR / "assets"

@router.get("/", include_in_schema=False)
def index_page():
    return FileResponse(FRONT_DIR / "index.html")

@router.get("/ndvi", include_in_schema=False)
def ndvi_page():
    return FileResponse(FRONT_DIR / "ndvi.html")

@router.get("/biopar", include_in_schema=False)
def biopar_page():
    return FileResponse(FRONT_DIR / "biopar.html")

@router.get("/header", include_in_schema=False)
def biopar_page():
    return FileResponse(FRONT_DIR / "header.html")
