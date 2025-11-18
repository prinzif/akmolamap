"""
/backend/biopar.py — BIOPAR (LAI, FAPAR, FCOVER, CCC, CWC) через openEO UDP.

Улучшенная версия с:
- Оптимизированным выбором разрешения для больших областей
- Улучшенной валидацией входных данных
- Расширенной классификацией статусов
- Детальными рекомендациями по типам BIOPAR
- Кэшированием статистики и GeoTIFF
- Обработкой ошибок и таймаутов

Возможности:
- Загрузка растров BIOPAR (GeoTIFF) для многоугольника и периода через openEO UDP
- Кэширование GeoTIFF и статистики (mean/median/std/percentiles)
- Временные ряды (разбиение периода на окна, вычисление средних по окнам)
- Классификация статуса для FAPAR/LAI/FCOVER/CCC/CWC
- Итоговый отчёт с рекомендациями

Требования:
- pip install openeo rasterio numpy scipy requests
- учётка Copernicus Data Space (OIDC). Для non-interactive аутентификации
  можно задать:
    CDSE_OIDC_CLIENT_ID
    CDSE_OIDC_CLIENT_SECRET (если нужно)
    CDSE_REFRESH_TOKEN (предпочтительно)
  Либо fallback на интерактивную авторизацию.
"""

from __future__ import annotations

import json
import hashlib
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from pathlib import Path

import numpy as np
from scipy import stats as scipy_stats

logger = logging.getLogger(__name__)

# --- Попытка импортов тяжёлых зависимостей ---
try:
    import rasterio
    from rasterio.mask import mask as rio_mask
    from rasterio.warp import transform_geom
    from rasterio.enums import Resampling
except ImportError:
    rasterio = None

import requests

# В начале backend/biopar.py добавьте:
from backend.biopar_sentinelhub import (
    fetch_biopar_geotiff as _fetch_sh,
    MosaickingOrder
)
from backend.settings import settings
from backend.constants import (
    STATUS_SUCCESS,
    STATUS_ERROR,
    STATUS_NO_DATA,
    BIOPAR_TYPES
)

# ---------- Константы и пути кэша ----------
CACHE_DIR = Path(__file__).resolve().parents[1] / "cache" / "biopar"
TIFF_CACHE_DIR = CACHE_DIR / "tiffs"
STATS_CACHE_DIR = CACHE_DIR / "stats"
TIFF_CACHE_DIR.mkdir(parents=True, exist_ok=True)
STATS_CACHE_DIR.mkdir(parents=True, exist_ok=True)

# UDP биопара
BIOPAR_UDP_URL = (
    "https://raw.githubusercontent.com/ESA-APEx/apex_algorithms/refs/heads/main/"
    "algorithm_catalog/vito/biopar/openeo_udp/biopar.json"
)

# Лимиты разрешения для openEO (метры на пиксель) - из настроек
BIOPAR_MIN_MPP = settings.BIOPAR_MIN_MPP  # минимальное разрешение
BIOPAR_MAX_MPP = settings.BIOPAR_MAX_MPP  # максимальное разрешение для биопараметров
MIN_PIXELS = settings.MIN_PIXELS          # минимум пикселей
MAX_PIXELS = settings.MAX_PIXELS          # максимум пикселей для оптимизации

# Sentinel Hub API endpoints (для Statistical API)
SH_STATISTICS_URL = settings.SH_STATISTICS_URL
SH_PROCESS_URL = settings.SH_PROCESS_URL

# ---------------------- Вспомогательные ---------------------- #

def _require(pkg_name: str, mod: Any):
    """Проверка наличия обязательного пакета."""
    if mod is None:
        raise RuntimeError(
            f"{pkg_name} не установлен. Установите пакет: pip install {pkg_name}"
        )


def _normalize_geojson_polygon(aoi_geojson: Dict[str, Any]) -> Dict[str, Any]:
    """
    Проверяем GeoJSON-полигон и нормализуем структуру.
    CRS ожидается EPSG:4326 (lon/lat).
    """
    if not aoi_geojson or aoi_geojson.get("type") != "Polygon":
        raise ValueError("spatial_extent должен быть GeoJSON Polygon (EPSG:4326).")
    coords = aoi_geojson.get("coordinates", [])
    if not coords or not isinstance(coords, list):
        raise ValueError("Некорректная геометрия Polygon.")
    if len(coords[0]) < 4:
        raise ValueError("Polygon должен содержать минимум 4 координаты (включая замыкающую)")
    return aoi_geojson


def _bbox_from_polygon(aoi: Dict[str, Any]) -> List[float]:
    """Возвращает bbox [minx, miny, maxx, maxy] из GeoJSON Polygon."""
    ring = aoi["coordinates"][0]
    xs = [p[0] for p in ring]
    ys = [p[1] for p in ring]
    return [min(xs), min(ys), max(xs), max(ys)]


def _approx_bbox_size_meters(bbox: List[float]) -> Tuple[float, float]:
    """
    Грубая оценка размеров bbox в метрах по широте середины окна.
    
    Args:
        bbox: [minx, miny, maxx, maxy] в градусах
        
    Returns:
        Tuple[float, float]: (ширина_м, высота_м)
    """
    from math import cos, radians
    
    minx, miny, maxx, maxy = bbox
    lat_mid = (miny + maxy) / 2.0
    m_per_deg_lat = 111_320.0
    m_per_deg_lon = 111_320.0 * cos(radians(lat_mid))
    width_m = max(1.0, (maxx - minx) * m_per_deg_lon)
    height_m = max(1.0, (maxy - miny) * m_per_deg_lat)
    return width_m, height_m


def _choose_resolution_for_biopar(bbox: List[float], target_mpp: int = 60) -> Tuple[int, int]:
    """
    Выбирает оптимальное разрешение (width/height в пикселях) для обработки BIOPAR,
    чтобы не превышать лимиты и получить адекватное разрешение.
    
    Args:
        bbox: [minx, miny, maxx, maxy]
        target_mpp: Желаемое разрешение в метрах на пиксель
        
    Returns:
        Tuple[int, int]: (width_px, height_px)
    """
    from math import ceil
    
    w_m, h_m = _approx_bbox_size_meters(bbox)
    mpp = max(BIOPAR_MIN_MPP, min(int(target_mpp), BIOPAR_MAX_MPP))
    
    w_px = max(MIN_PIXELS, min(MAX_PIXELS, ceil(w_m / mpp)))
    h_px = max(MIN_PIXELS, min(MAX_PIXELS, ceil(h_m / mpp)))
    
    # Контрольная проверка эффективного разрешения
    eff_mpp = max(w_m / w_px, h_m / h_px)
    if eff_mpp > BIOPAR_MAX_MPP:
        w_px = max(w_px, min(MAX_PIXELS, ceil(w_m / BIOPAR_MAX_MPP)))
        h_px = max(h_px, min(MAX_PIXELS, ceil(h_m / BIOPAR_MAX_MPP)))
    
    logger.debug(
        f"BIOPAR resolution: bbox≈({w_m:.0f}x{h_m:.0f} m), "
        f"target {mpp} m/px → {w_px}x{h_px} px (eff≈{eff_mpp:.1f} m/px)"
    )
    return int(w_px), int(h_px)


def _digest_for(aoi: Dict[str, Any], start: str, end: str, btype: str) -> str:
    """Генерирует SHA256 хэш для кэширования (более безопасен чем MD5)."""
    payload = {
        "aoi": aoi,
        "start": start,
        "end": end,
        "biopar_type": btype.upper(),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def _tiff_path_for(aoi: Dict[str, Any], start: str, end: str, btype: str) -> Path:
    """Генерирует путь к кэшированному GeoTIFF."""
    return TIFF_CACHE_DIR / f"biopar_{btype.lower()}_{_digest_for(aoi, start, end, btype)}.tif"


def _stats_cache_path_for(aoi: Dict[str, Any], start: str, end: str, btype: str, tag: str) -> Path:
    """Генерирует путь к кэшированной статистике."""
    return STATS_CACHE_DIR / f"stats_{btype.lower()}_{tag}_{_digest_for(aoi, start, end, btype)}.json"


def _get_biopar_evalscript(biopar_type: str) -> str:
    """
    Возвращает evalscript V3 для Statistical API по типу BIOPAR.
    Использует SNAP NN алгоритмы из Sentinel Hub Custom Scripts.

    Args:
        biopar_type: Тип параметра (FAPAR, LAI, FCOVER)

    Returns:
        str: Evalscript V3 с облачной маской

    Note:
        CCC и CWC не поддерживаются через Statistical API - используйте openEO
    """
    bt = biopar_type.upper()

    if bt == "FAPAR":
        return """//VERSION=3
function setup() {
  return {
    input: [{
      bands: ["B03","B04","B05","B06","B07","B8A","B11","B12",
              "viewZenithMean","viewAzimuthMean","sunZenithAngles","sunAzimuthAngles",
              "SCL","dataMask"]
    }],
    output: [
      {id:"fapar", bands:1, sampleType:"FLOAT32"},
      {id:"dataMask", bands:1}
    ],
    mosaicking: "ORBIT"
  };
}

var degToRad = Math.PI / 180;

function evaluatePixel(samples) {
  for (let i = 0; i < samples.length; i++) {
    let sample = samples[i];
    if (sample.dataMask === 0) continue;
    if (sample.SCL === 3 || sample.SCL === 8 || sample.SCL === 9 ||
        sample.SCL === 10 || sample.SCL === 11) continue;

    var b03_norm = normalize(sample.B03, 0, 0.253061520471542);
    var b04_norm = normalize(sample.B04, 0, 0.290393577911328);
    var b05_norm = normalize(sample.B05, 0, 0.305398915248555);
    var b06_norm = normalize(sample.B06, 0.006637972542253, 0.608900395797889);
    var b07_norm = normalize(sample.B07, 0.013972727018939, 0.753827384322927);
    var b8a_norm = normalize(sample.B8A, 0.026690138082061, 0.782011770669178);
    var b11_norm = normalize(sample.B11, 0.016388074192258, 0.493761397883092);
    var b12_norm = normalize(sample.B12, 0, 0.493025984460231);

    var viewZen_norm = normalize(Math.cos(sample.viewZenithMean * degToRad), 0.918595400582046, 1);
    var sunZen_norm  = normalize(Math.cos(sample.sunZenithAngles * degToRad), 0.342022871159208, 0.936206429175402);
    var relAzim_norm = Math.cos((sample.sunAzimuthAngles - sample.viewAzimuthMean) * degToRad);

    var n1 = neuron1(b03_norm,b04_norm,b05_norm,b06_norm,b07_norm,b8a_norm,b11_norm,b12_norm,viewZen_norm,sunZen_norm,relAzim_norm);
    var n2 = neuron2(b03_norm,b04_norm,b05_norm,b06_norm,b07_norm,b8a_norm,b11_norm,b12_norm,viewZen_norm,sunZen_norm,relAzim_norm);
    var n3 = neuron3(b03_norm,b04_norm,b05_norm,b06_norm,b07_norm,b8a_norm,b11_norm,b12_norm,viewZen_norm,sunZen_norm,relAzim_norm);
    var n4 = neuron4(b03_norm,b04_norm,b05_norm,b06_norm,b07_norm,b8a_norm,b11_norm,b12_norm,viewZen_norm,sunZen_norm,relAzim_norm);
    var n5 = neuron5(b03_norm,b04_norm,b05_norm,b06_norm,b07_norm,b8a_norm,b11_norm,b12_norm,viewZen_norm,sunZen_norm,relAzim_norm);

    var l2 = layer2(n1, n2, n3, n4, n5);
    var fapar = denormalize(l2, 0.000153013463222, 0.977135096979553);
    fapar = Math.max(0, Math.min(1, fapar));

    return {fapar: [fapar], dataMask: [1]};
  }
  return {fapar: [NaN], dataMask: [0]};
}

function neuron1(a,b,c,d,e,f,g,h,i,j,k){var s=-0.887068364040280+0.268714454733421*a-0.205473108029835*b+0.281765694196018*c+1.337443412255980*d+0.390319212938497*e-3.612714342203350*f+0.222530960987244*g+0.821790549667255*h-0.093664567310731*i+0.019290146147447*j+0.037364446377188*k;return tansig(s);}
function neuron2(a,b,c,d,e,f,g,h,i,j,k){var s=+0.320126471197199-0.248998054599707*a-0.571461305473124*b-0.369957603466673*c+0.246031694650909*d+0.332536215252841*e+0.438269896208887*f+0.819000551890450*g-0.934931499059310*h+0.082716247651866*i-0.286978634108328*j-0.035890968351662*k;return tansig(s);}
function neuron3(a,b,c,d,e,f,g,h,i,j,k){var s=+0.610523702500117-0.164063575315880*a-0.126303285737763*b-0.253670784366822*c-0.321162835049381*d+0.067082287973580*e+2.029832288655260*f-0.023141228827722*g-0.553176625657559*h+0.059285451897783*i-0.034334454541432*j-0.031776704097009*k;return tansig(s);}
function neuron4(a,b,c,d,e,f,g,h,i,j,k){var s=-0.379156190833946+0.130240753003835*a+0.236781035723321*b+0.131811664093253*c-0.250181799267664*d-0.011364149953286*e-1.857573214633520*f-0.146860751013916*g+0.528008831372352*h-0.046230769098303*i-0.034509608392235*j+0.031884395036004*k;return tansig(s);}
function neuron5(a,b,c,d,e,f,g,h,i,j,k){var s=+1.353023396690570-0.029929946166941*a+0.795804414040809*b+0.348025317624568*c+0.943567007518504*d-0.276341670431501*e-2.946594180142590*f+0.289483073507500*g+1.044006950440180*h-0.000413031960419*i+0.403331114840215*j+0.068427130526696*k;return tansig(s);}
function layer2(n1,n2,n3,n4,n5){return -0.336431283973339+2.126038811064490*n1-0.632044932794919*n2+5.598995787206250*n3+1.770444140578970*n4-0.267879583604849*n5;}
function normalize(u,min,max){return 2*(u-min)/(max-min)-1;}
function denormalize(n,min,max){return 0.5*(n+1)*(max-min)+min;}
function tansig(x){return 2/(1+Math.exp(-2*x))-1;}
"""
    elif bt == "LAI":
        return """//VERSION=3
function setup() {
  return {
    input: [{
      bands: ["B03","B04","B05","B06","B07","B8A","B11","B12",
              "viewZenithMean","viewAzimuthMean","sunZenithAngles","sunAzimuthAngles",
              "SCL","dataMask"]
    }],
    output: [
      {id:"lai", bands:1, sampleType:"FLOAT32"},
      {id:"dataMask", bands:1}
    ],
    mosaicking: "ORBIT"
  };
}

var degToRad = Math.PI / 180;

function evaluatePixel(samples) {
  for (let i = 0; i < samples.length; i++) {
    let sample = samples[i];
    if (sample.dataMask === 0) continue;
    if (sample.SCL === 3 || sample.SCL === 8 || sample.SCL === 9 ||
        sample.SCL === 10 || sample.SCL === 11) continue;

    var b03_norm = normalize(sample.B03, 0, 0.255607);
    var b04_norm = normalize(sample.B04, 0, 0.291938);
    var b05_norm = normalize(sample.B05, 0, 0.307567);
    var b06_norm = normalize(sample.B06, 0.007004, 0.613413);
    var b07_norm = normalize(sample.B07, 0.014526, 0.760554);
    var b8a_norm = normalize(sample.B8A, 0.027440, 0.793957);
    var b11_norm = normalize(sample.B11, 0.016904, 0.497987);
    var b12_norm = normalize(sample.B12, 0, 0.494352);

    var viewZen_norm = normalize(Math.cos(sample.viewZenithMean * degToRad), 0.918595400582046, 1);
    var sunZen_norm  = normalize(Math.cos(sample.sunZenithAngles * degToRad), 0.342022871159208, 0.936206429175402);
    var relAzim_norm = Math.cos((sample.sunAzimuthAngles - sample.viewAzimuthMean) * degToRad);

    var n1 = neuron1(b03_norm,b04_norm,b05_norm,b06_norm,b07_norm,b8a_norm,b11_norm,b12_norm,viewZen_norm,sunZen_norm,relAzim_norm);
    var n2 = neuron2(b03_norm,b04_norm,b05_norm,b06_norm,b07_norm,b8a_norm,b11_norm,b12_norm,viewZen_norm,sunZen_norm,relAzim_norm);
    var n3 = neuron3(b03_norm,b04_norm,b05_norm,b06_norm,b07_norm,b8a_norm,b11_norm,b12_norm,viewZen_norm,sunZen_norm,relAzim_norm);
    var n4 = neuron4(b03_norm,b04_norm,b05_norm,b06_norm,b07_norm,b8a_norm,b11_norm,b12_norm,viewZen_norm,sunZen_norm,relAzim_norm);
    var n5 = neuron5(b03_norm,b04_norm,b05_norm,b06_norm,b07_norm,b8a_norm,b11_norm,b12_norm,viewZen_norm,sunZen_norm,relAzim_norm);

    var l2 = layer2(n1, n2, n3, n4, n5);
    var lai = denormalize(l2, 0.002, 6.0);
    lai = Math.max(0, Math.min(8, lai));

    return {lai: [lai], dataMask: [1]};
  }
  return {lai: [NaN], dataMask: [0]};
}

function neuron1(a,b,c,d,e,f,g,h,i,j,k){var s=+0.784808-0.137023*a+0.046769*b-0.507095*c+0.059367*d+0.479746*e-1.357460*f+0.083341*g+0.253529*h+0.037930*i-0.268747*j+0.301715*k;return tansig(s);}
function neuron2(a,b,c,d,e,f,g,h,i,j,k){var s=-0.372636-0.207983*a-0.100905*b+0.018108*c-0.280948*d+0.308629*e+0.782934*f-0.109214*g-0.652244*h-0.126916*i-0.283522*j-0.057708*k;return tansig(s);}
function neuron3(a,b,c,d,e,f,g,h,i,j,k){var s=-0.395026-0.133541*a-0.122994*b+0.010796*c-0.419717*d+0.356877*e+1.998431*f-0.207434*g-0.518681*h+0.072074*i-0.156707*j-0.008894*k;return tansig(s);}
function neuron4(a,b,c,d,e,f,g,h,i,j,k){var s=+0.128022+0.212186*a-0.052945*b-0.024536*c-0.041589*d-0.020826*e-1.796692*f-0.181030*g+0.625598*h-0.074544*i-0.013845*j-0.020874*k;return tansig(s);}
function neuron5(a,b,c,d,e,f,g,h,i,j,k){var s=-0.208894+0.179996*a+0.262594*b+0.122393*c+0.135604*d-0.147989*e-0.912822*f+0.058144*g+0.188219*h+0.174050*i-0.292004*j+0.009611*k;return tansig(s);}
function layer2(n1,n2,n3,n4,n5){return +1.096963107077220-1.500135489728730*n1-0.096283269121503*n2-0.194935930577094*n3-0.352305895755591*n4+0.075107415847473*n5;}
function normalize(u,min,max){return 2*(u-min)/(max-min)-1;}
function denormalize(n,min,max){return 0.5*(n+1)*(max-min)+min;}
function tansig(x){return 2/(1+Math.exp(-2*x))-1;}
"""
    elif bt == "FCOVER":
        return """//VERSION=3
function setup() {
  return {
    input: [{
      bands: ["B03","B04","B05","B06","B07","B8A","B11","B12",
              "viewZenithMean","viewAzimuthMean","sunZenithAngles","sunAzimuthAngles",
              "SCL","dataMask"]
    }],
    output: [
      {id:"fcover", bands:1, sampleType:"FLOAT32"},
      {id:"dataMask", bands:1}
    ],
    mosaicking: "ORBIT"
  };
}

var degToRad = Math.PI / 180;

function evaluatePixel(samples) {
  for (let i = 0; i < samples.length; i++) {
    let sample = samples[i];
    if (sample.dataMask === 0) continue;
    if (sample.SCL === 3 || sample.SCL === 8 || sample.SCL === 9 ||
        sample.SCL === 10 || sample.SCL === 11) continue;

    var b03_norm = normalize(sample.B03, 0, 0.253061520472);
    var b04_norm = normalize(sample.B04, 0, 0.290393577911);
    var b05_norm = normalize(sample.B05, 0, 0.305398915249);
    var b06_norm = normalize(sample.B06, 0.00663797254225, 0.608900395798);
    var b07_norm = normalize(sample.B07, 0.0139727270189, 0.753827384323);
    var b8a_norm = normalize(sample.B8A, 0.0266901380821, 0.782011770669);
    var b11_norm = normalize(sample.B11, 0.0163880741923, 0.493761397883);
    var b12_norm = normalize(sample.B12, 0, 0.49302598446);

    var viewZen_norm = normalize(Math.cos(sample.viewZenithMean * degToRad), 0.918595400582, 0.999999999991);
    var sunZen_norm  = normalize(Math.cos(sample.sunZenithAngles * degToRad), 0.342022871159, 0.936206429175);
    var relAzim_norm = Math.cos((sample.sunAzimuthAngles - sample.viewAzimuthMean) * degToRad);

    var n1 = neuron1(b03_norm,b04_norm,b05_norm,b06_norm,b07_norm,b8a_norm,b11_norm,b12_norm,viewZen_norm,sunZen_norm,relAzim_norm);
    var n2 = neuron2(b03_norm,b04_norm,b05_norm,b06_norm,b07_norm,b8a_norm,b11_norm,b12_norm,viewZen_norm,sunZen_norm,relAzim_norm);
    var n3 = neuron3(b03_norm,b04_norm,b05_norm,b06_norm,b07_norm,b8a_norm,b11_norm,b12_norm,viewZen_norm,sunZen_norm,relAzim_norm);
    var n4 = neuron4(b03_norm,b04_norm,b05_norm,b06_norm,b07_norm,b8a_norm,b11_norm,b12_norm,viewZen_norm,sunZen_norm,relAzim_norm);
    var n5 = neuron5(b03_norm,b04_norm,b05_norm,b06_norm,b07_norm,b8a_norm,b11_norm,b12_norm,viewZen_norm,sunZen_norm,relAzim_norm);

    var l2 = layer2(n1, n2, n3, n4, n5);
    var fcover = denormalize(l2, 0.0, 1.0);
    fcover = Math.max(0, Math.min(1, fcover));

    return {fcover: [fcover], dataMask: [1]};
  }
  return {fcover: [NaN], dataMask: [0]};
}

function neuron1(a,b,c,d,e,f,g,h,i,j,k){var s=+0.0137252282366+0.0620475742195*a-0.210637958422*b+0.00910504629206*c+1.30972609475*d+0.62612181421*e-2.55574799014*f+0.157617890355*g+0.0367979958686*h+0.09346914378*i-0.479103746331*j+0.344160187043*k;return tansig(s);}
function neuron2(a,b,c,d,e,f,g,h,i,j,k){var s=-0.633893997132+0.177727232172*a-0.0890540117122*b-0.306518961301*c+0.134721838239*d+0.0831366551838*e+0.448401871028*f+0.393642915*g-0.679321241292*h+0.478879910242*i-0.265800913171*j-0.188123881816*k;return tansig(s);}
function neuron3(a,b,c,d,e,f,g,h,i,j,k){var s=+1.02168965849-0.409688743281*a+1.08858884766*b+0.36284522554*c+0.0369390509705*d-0.348012590003*e-2.0035261881*f+0.0410357601757*g+1.22373853174*h-0.0124082778287*i-0.282223364524*j+1.028e-4*k;return tansig(s);}
function neuron4(a,b,c,d,e,f,g,h,i,j,k){var s=-0.498002810205-0.188970957866*a-0.0358621840833*b+0.00551248528107*c+1.35391570802*d-0.739689896116*e-2.21719530107*f+0.313216124198*g+1.5020168915*h+1.21530490195*i-0.421938358618*j+1.48852484547*k;return tansig(s);}
function neuron5(a,b,c,d,e,f,g,h,i,j,k){var s=-3.88922154789+2.49293993709*a-4.40511331388*b-1.91062012624*c-0.703174115575*d-0.215104721138*e-0.972151494818*f-0.930752241278*g+1.2143441876*h-0.521665460192*i-0.445755955598*j+0.344111873777*k;return tansig(s);}
function layer2(n1,n2,n3,n4,n5){return -0.0967998147811+0.23080586765*n1-0.333655484884*n2-0.499418292325*n3+0.0472484396749*n4-0.0798516540739*n5;}
function normalize(u,min,max){return 2*(u-min)/(max-min)-1;}
function denormalize(n,min,max){return 0.5*(n+1)*(max-min)+min;}
function tansig(x){return 2/(1+Math.exp(-2*x))-1;}
"""
    else:
        raise NotImplementedError(
            f"{bt} не поддерживается через Statistical API. "
            f"Для CCC и CWC используйте openEO."
        )


def _as_float_or_none(x: Any) -> Optional[float]:
    """Пытается привести к float, возвращает None для None/NaN/нечисел."""
    try:
        v = float(x)
        return v if np.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def _validate_date_range(start_date: str, end_date: str) -> None:
    """
    Валидирует диапазон дат.
    
    Args:
        start_date: YYYY-MM-DD
        end_date: YYYY-MM-DD
        
    Raises:
        ValueError: Если даты невалидны
    """
    try:
        start = datetime.strptime(start_date, "%Y-%m-%d")
        end = datetime.strptime(end_date, "%Y-%m-%d")
    except ValueError as e:
        raise ValueError(f"Неверный формат даты. Используйте YYYY-MM-DD: {e}")
    
    if start > end:
        raise ValueError(f"start_date ({start_date}) должна быть раньше end_date ({end_date})")

    if end > datetime.utcnow():
        logger.warning(f"end_date ({end_date}) в будущем, данные могут быть неполными")
    
    # Проверка на слишком большой период
    days_diff = (end - start).days
    if days_diff > 365:
        logger.warning(f"Период {days_diff} дней превышает год, обработка может занять много времени")


# ---------------------- Загрузка BIOPAR GeoTIFF ---------------------- #



# Замените функцию fetch_biopar_geotiff на обёртку:
def fetch_biopar_geotiff(
    aoi_geojson: Dict[str, Any],
    start_date: str,
    end_date: str,
    biopar_type: str = "FAPAR",
    force: bool = False,
    timeout_sec: int = 120
) -> Path:
    """
    Загружает BIOPAR GeoTIFF.
    - FAPAR, LAI, FCOVER: через Sentinel Hub (быстрее)
    - CCC, CWC: через openEO (единственный вариант)
    """
    _require("rasterio", rasterio)
    
    biopar_type = biopar_type.upper()
    if biopar_type not in BIOPAR_TYPES:
        raise ValueError(f"biopar_type должен быть одним из {sorted(BIOPAR_TYPES)}")

    aoi_geojson = _normalize_geojson_polygon(aoi_geojson)
    _validate_date_range(start_date, end_date)
    
    # Проверяем кэш
    tif_path = _tiff_path_for(aoi_geojson, start_date, end_date, biopar_type)
    if tif_path.exists() and not force:
        logger.info(f"[BIOPAR] cache hit: {tif_path.name}")
        return tif_path

    logger.info(f"[BIOPAR] запрос: {biopar_type} {start_date}..{end_date}")

    # Для CCC и CWC используем openEO
    if biopar_type in ("CCC", "CWC"):
        logger.info(f"[BIOPAR] {biopar_type} доступен только через openEO")
        
        from backend.biopar_openeo import fetch_biopar_openeo
        
        try:
            openeo_path = fetch_biopar_openeo(
                aoi_geojson=aoi_geojson,
                start_date=start_date,
                end_date=end_date,
                biopar_type=biopar_type,
                force=force
            )
            
            # Копируем в единый кэш
            import shutil
            shutil.copy(openeo_path, tif_path)
            logger.info(f"[BIOPAR] сохранено: {tif_path.name}")
            
            return tif_path
            
        except Exception as e:
            logger.error(f"[BIOPAR] openEO error: {e}", exc_info=True)
            raise

    # Для FAPAR, LAI, FCOVER используем Sentinel Hub (быстрее)
    try:
        bbox = _bbox_from_polygon(aoi_geojson)
        width_px, height_px = _choose_resolution_for_biopar(bbox, target_mpp=settings.BIOPAR_TARGET_MPP)

        sh_path = _fetch_sh(
            bbox=bbox,
            start_date=start_date,
            end_date=end_date,
            biopar_type=biopar_type,
            width=width_px,
            height=height_px,
            max_cloud_coverage=settings.BIOPAR_MAX_CLOUD,
            mosaicking_order=MosaickingOrder.LEAST_CC
        )
        
        import shutil
        shutil.copy(sh_path, tif_path)
        logger.info(f"[BIOPAR] сохранено: {tif_path.name}")
        
        return tif_path
        
    except Exception as e:
        logger.error(f"[BIOPAR] Sentinel Hub error: {e}", exc_info=True)
        raise
# ---------------------- Статистика по GeoTIFF ---------------------- #

def _masked_mean(arr: np.ndarray) -> float:
    """Вычисляет среднее с учётом маски."""
    m = np.isfinite(arr)
    return float(np.nan) if not m.any() else float(np.nanmean(arr[m]))


def _compute_percentiles(arr: np.ndarray, ks=(10, 25, 50, 75, 90)) -> Dict[str, Optional[float]]:
    """Вычисляет перцентили массива."""
    vals = arr[np.isfinite(arr)]
    if vals.size == 0:
        # Очистка памяти перед возвратом
        del vals
        return {f"p{k}": None for k in ks}
    res = np.percentile(vals, ks)
    result = {f"p{int(k)}": float(np.round(v, 4)) for k, v in zip(ks, res)}

    # Явно удаляем временные массивы для освобождения памяти
    del vals
    del res

    return result


def compute_tiff_stats(
    tif_path: Path,
    aoi_geojson: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Считает mean/median/std/min/max и перцентили для GeoTIFF BIOPAR.
    Если передать aoi_geojson — перед вычислением обрежет по маске полигона.
    
    Args:
        tif_path: Путь к GeoTIFF файлу
        aoi_geojson: Опциональный GeoJSON полигон для маскирования
        
    Returns:
        Dict: Статистические показатели
    """
    _require("rasterio", rasterio)

    try:
        with rasterio.open(tif_path) as src:
            if aoi_geojson:
                geom = transform_geom(
                    "EPSG:4326",
                    src.crs.to_string(),
                    aoi_geojson,
                    precision=6
                )
                data, _ = rio_mask(src, [geom], crop=True, filled=True, nodata=np.nan)
                band = data[0].astype(np.float32)
                # Явно удаляем временный массив data для освобождения памяти
                del data
            else:
                band = src.read(1, masked=True).filled(np.nan).astype(np.float32)

        # Use masked arrays for more efficient operations
        masked = np.ma.masked_invalid(band)
        if masked.count() == 0:
            logger.warning("No valid data in GeoTIFF")
            # Очистка памяти перед возвратом
            del band
            del masked
            return {
                "mean": None, "median": None, "std": None,
                "min": None, "max": None,
                "percentiles": {k: None for k in ["p10", "p25", "p50", "p75", "p90"]},
                "pixels": 0
            }

        mean = float(masked.mean())
        median = float(np.ma.median(masked))
        std = float(masked.std())
        vmin = float(masked.min())
        vmax = float(masked.max())
        pcts = _compute_percentiles(band)

        result = {
            "mean": round(mean, 4),
            "median": round(median, 4),
            "std": round(std, 4),
            "min": round(vmin, 4),
            "max": round(vmax, 4),
            "percentiles": pcts,
            "pixels": int(masked.count())
        }

        # Явно удаляем большие массивы для освобождения памяти
        del band
        del masked

        return result

    except Exception as e:
        logger.error(f"Ошибка вычисления статистики: {e}", exc_info=True)
        raise


def get_biopar_statistics(
    aoi_geojson: Dict[str, Any],
    start_date: str,
    end_date: str,
    biopar_type: str = "FAPAR",
    use_cache: bool = True,
    aggregation_days: int = 5
) -> Dict[str, Any]:
    """
    Возвращает статистику BIOPAR через Statistical API (для FAPAR/LAI/FCOVER)
    или через GeoTIFF (для CCC/CWC).

    Args:
        aoi_geojson: GeoJSON Polygon (EPSG:4326)
        start_date: YYYY-MM-DD
        end_date: YYYY-MM-DD
        biopar_type: 'FAPAR'|'LAI'|'FCOVER'|'CCC'|'CWC'
        use_cache: Использовать кэш
        aggregation_days: Период агрегации в днях (для Statistical API)

    Returns:
        {
          "status": "success",
          "biopar_type": "...",
          "statistics": {...},
          "timeline": [...]
        }
    """
    try:
        biopar_type = biopar_type.upper()
        aoi_geojson = _normalize_geojson_polygon(aoi_geojson)
        _validate_date_range(start_date, end_date)

        # Для FAPAR, LAI, FCOVER используем Statistical API
        if biopar_type in ("FAPAR", "LAI", "FCOVER"):
            return _get_biopar_stats_statistical_api(
                aoi_geojson, start_date, end_date, biopar_type,
                use_cache, aggregation_days
            )

        # Для CCC и CWC используем старый метод через GeoTIFF
        cache_path = _stats_cache_path_for(
            aoi_geojson, start_date, end_date, biopar_type, tag="full"
        )

        if use_cache and cache_path.exists():
            try:
                cached = json.loads(cache_path.read_text(encoding="utf-8"))
                logger.info(f"[BIOPAR] statistics cache hit: {cache_path.name}")
                return cached
            except Exception as e:
                logger.warning(f"Не удалось загрузить кэш: {e}")

        tif = fetch_biopar_geotiff(aoi_geojson, start_date, end_date, biopar_type)
        stats = compute_tiff_stats(tif, aoi_geojson=aoi_geojson)

        result = {
            "status": "success",
            "biopar_type": biopar_type,
            "period": f"{start_date} – {end_date}",
            "statistics": stats,
            "timeline": []
        }

        if use_cache:
            try:
                cache_path.write_text(
                    json.dumps(result, ensure_ascii=False, indent=2),
                    encoding="utf-8"
                )
                logger.info(f"[BIOPAR] statistics cached: {cache_path.name}")
            except Exception as e:
                logger.warning(f"Не удалось сохранить кэш статистики: {e}")

        return result

    except Exception as e:
        logger.error(f"[BIOPAR] ошибка получения статистики: {e}", exc_info=True)
        return {
            "status": "error",
            "message": str(e),
            "biopar_type": biopar_type,
            "statistics": {},
            "timeline": []
        }


def _get_biopar_stats_statistical_api(
    aoi_geojson: Dict[str, Any],
    start_date: str,
    end_date: str,
    biopar_type: str,
    use_cache: bool,
    aggregation_days: int
) -> Dict[str, Any]:
    """
    Получает статистику BIOPAR через Statistical API (эффективнее чем загрузка GeoTIFF).

    Args:
        aoi_geojson: GeoJSON Polygon
        start_date: YYYY-MM-DD
        end_date: YYYY-MM-DD
        biopar_type: FAPAR|LAI|FCOVER
        use_cache: Использовать кэш
        aggregation_days: Размер окна агрегации

    Returns:
        Dict: Статистика с временным рядом
    """
    from backend.biopar_sentinelhub import (
        get_cdse_token,
        NoDataAvailableError,
        SentinelHubError
    )

    logger.info(
        f"[BIOPAR] Statistical API: {biopar_type} {start_date}..{end_date}, "
        f"agg={aggregation_days}d"
    )

    # Проверка кэша
    cache_path = _stats_cache_path_for(
        aoi_geojson, start_date, end_date, biopar_type,
        tag=f"statapi_{aggregation_days}d"
    )

    if use_cache and cache_path.exists():
        try:
            with open(cache_path, 'r') as f:
                cached = json.load(f)
            logger.info(f"[BIOPAR] stats cache hit: {cache_path.name}")
            return cached
        except Exception as e:
            logger.warning(f"Failed to load cache: {e}")

    # Получаем токен и evalscript
    token = get_cdse_token()
    evalscript = _get_biopar_evalscript(biopar_type)

    # Определяем bbox
    bbox = _bbox_from_polygon(aoi_geojson)

    # Безопасное разрешение
    width_px, height_px = _choose_resolution_for_biopar(bbox, target_mpp=60)

    # ID output-а в evalscript
    output_id = biopar_type.lower()

    # Формируем запрос к Statistical API
    payload = {
        "input": {
            "bounds": {
                "bbox": bbox,
                "properties": {
                    "crs": "http://www.opengis.net/def/crs/EPSG/0/4326"
                }
            },
            "data": [{
                "type": "sentinel-2-l2a",
                "dataFilter": {
                    "maxCloudCoverage": 50
                },
                "processing": {
                    "harmonizeValues": True
                }
            }]
        },
        "aggregation": {
            "timeRange": {
                "from": f"{start_date}T00:00:00Z",
                "to": f"{end_date}T23:59:59Z"
            },
            "aggregationInterval": {
                "of": f"P{aggregation_days}D"
            },
            "evalscript": evalscript,
            "width": width_px,
            "height": height_px
        },
        "calculations": {
            "default": {
                "statistics": {
                    "default": {
                        "percentiles": {
                            "k": [10, 25, 50, 75, 90]
                        }
                    }
                }
            }
        }
    }

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

    # Отправляем запрос
    logger.info(f"[BIOPAR] Requesting stats from Statistical API...")
    resp = requests.post(
        SH_STATISTICS_URL,
        headers=headers,
        json=payload,
        timeout=180
    )

    if resp.status_code == 400:
        error_text = resp.text
        if "no data" in error_text.lower():
            raise NoDataAvailableError(
                f"No data for {biopar_type} {start_date} to {end_date}"
            )
        raise SentinelHubError(f"Invalid request: {error_text}")

    if resp.status_code != 200:
        logger.error(f"Statistical API error ({resp.status_code}): {resp.text}")
        resp.raise_for_status()

    result = resp.json()

    if result.get("status") != "OK":
        raise SentinelHubError(f"API returned non-OK status: {result}")

    data = result.get("data", [])

    if not data:
        raise NoDataAvailableError(
            f"No valid observations for {biopar_type} {start_date} to {end_date}"
        )

    # Парсим ответ
    timeline = []
    all_means = []

    for item in data:
        interval = item.get("interval", {})
        outputs = item.get("outputs", {})
        biopar_output = outputs.get(output_id, {})
        bands = biopar_output.get("bands", {})
        band_stats = bands.get("B0", {}).get("stats", {})

        if not band_stats:
            continue

        mean_val = _as_float_or_none(band_stats.get("mean"))
        if mean_val is None:
            continue

        pcts = band_stats.get("percentiles", {}) or {}

        def _r(x):
            v = _as_float_or_none(x)
            return round(v, 4) if v is not None else None

        timeline.append({
            "date": interval.get("from", "")[:10],
            "mean_value": round(mean_val, 4),
            "min_value": _r(band_stats.get("min")),
            "max_value": _r(band_stats.get("max")),
            "std_value": _r(band_stats.get("stDev")),
            # Add frontend-compatible field names
            "mean": round(mean_val, 4),
            "min": _r(band_stats.get("min")),
            "max": _r(band_stats.get("max")),
            "std": _r(band_stats.get("stDev")),
            "p50": _r(pcts.get("50.0")),
            "median": _r(pcts.get("50.0"))
        })
        all_means.append(float(mean_val))

    if not all_means:
        raise NoDataAvailableError(
            f"All observations masked for {biopar_type} {start_date} to {end_date}"
        )

    # Агрегированная статистика
    arr = np.asarray(all_means, dtype=np.float64)
    mean_val = float(np.nanmean(arr))
    median_val = float(np.nanmedian(arr))
    std_val = float(np.nanstd(arr))
    min_val = float(np.nanmin(arr))
    max_val = float(np.nanmax(arr))

    # Тренд
    if len(all_means) >= 3:
        x = np.arange(len(all_means))
        slope, _, r_value, p_value, _ = scipy_stats.linregress(x, all_means)

        if abs(slope) < 0.001:
            direction = "stable"
        else:
            direction = "increasing" if slope > 0 else "decreasing"

        trend = {
            "direction": direction,
            "slope": round(float(slope), 6),
            "r_squared": round(float(r_value ** 2), 3),
            "p_value": round(float(p_value), 4),
            "description": f"{biopar_type} {direction} (R²={round(r_value**2, 3)})"
        }
    else:
        trend = {
            "direction": "insufficient_data",
            "slope": 0.0,
            "r_squared": 0.0,
            "p_value": 1.0,
            "description": "Insufficient data for trend"
        }

    # Get bbox from aoi_geojson
    bbox = _bbox_from_polygon(aoi_geojson)

    response = {
        "status": STATUS_SUCCESS,
        "biopar_type": biopar_type,
        "bbox": bbox,
        "period": {"start": start_date, "end": end_date},
        "statistics": {
            "mean": round(mean_val, 4),
            "median": round(median_val, 4),
            "std": round(std_val, 4),
            "min": round(min_val, 4),
            "max": round(max_val, 4)
        },
        "timeline": timeline,
        "trend": trend,  # Add trend for frontend compatibility
        "products_available": len(all_means)
    }

    # Сохраняем в кэш
    if use_cache:
        try:
            with open(cache_path, 'w') as f:
                json.dump(response, f, indent=2)
            logger.info(f"[BIOPAR] stats cached: {cache_path.name}")
        except Exception as e:
            logger.warning(f"Failed to cache stats: {e}")

    return response


# ---------------------- Временной ряд (оконная агрегация) ---------------------- #

def _iter_date_windows(start_date: str, end_date: str, window_days: int) -> List[Tuple[str, str]]:
    """
    Разбивает период на окна фиксированного размера.
    
    Args:
        start_date: YYYY-MM-DD
        end_date: YYYY-MM-DD
        window_days: Размер окна в днях
        
    Returns:
        List[Tuple[str, str]]: Список пар (start, end) для каждого окна
    """
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    cur = start
    windows = []
    
    while cur <= end:
        w_end = min(end, cur + timedelta(days=window_days - 1))
        windows.append((cur.strftime("%Y-%m-%d"), w_end.strftime("%Y-%m-%d")))
        cur = w_end + timedelta(days=1)
    
    return windows


def get_biopar_timeseries(
    aoi_geojson: Dict[str, Any],
    start_date: str,
    end_date: str,
    biopar_type: str = "FAPAR",
    aggregation_days: int = 10,
    use_cache: bool = True
) -> Dict[str, Any]:
    """
    Временной ряд средних значений BIOPAR.
    Для FAPAR/LAI/FCOVER использует Statistical API (эффективно).
    Для CCC/CWC использует GeoTIFF метод (медленно, но единственный вариант).

    Args:
        aoi_geojson: GeoJSON Polygon
        start_date: YYYY-MM-DD
        end_date: YYYY-MM-DD
        biopar_type: Тип биопараметра
        aggregation_days: Размер окна в днях
        use_cache: Использовать кэш

    Returns:
    {
      "status": "success",
      "biopar_type": "FAPAR",
      "timeline": [{"date":"YYYY-MM-DD","mean":0.42,...}, ...],
      "trend": {...}
    }
    """
    try:
        biopar_type = biopar_type.upper()
        aoi_geojson = _normalize_geojson_polygon(aoi_geojson)
        _validate_date_range(start_date, end_date)

        # Для FAPAR, LAI, FCOVER используем Statistical API
        if biopar_type in ("FAPAR", "LAI", "FCOVER"):
            # Get stats from Statistical API
            stats_result = _get_biopar_stats_statistical_api(
                aoi_geojson, start_date, end_date, biopar_type,
                use_cache, aggregation_days
            )

            # Transform timeline to series format for timeseries endpoint
            series = []
            for item in stats_result.get("timeline", []):
                series.append({
                    "date": item["date"],
                    "value": item["mean_value"],
                    "aggregation_window": aggregation_days
                })

            # Return in timeseries format (bbox and period will be added by router)
            # Include both 'series' (for schema) and 'timeline' (for frontend)
            return {
                "status": STATUS_SUCCESS,
                "biopar_type": biopar_type,
                "series": series,
                "timeline": stats_result.get("timeline", []),  # Frontend expects this
                "trend": stats_result.get("trend"),             # Frontend expects this
                "aggregation_days": aggregation_days
            }

        # Для CCC и CWC используем старый метод через GeoTIFF
        cache_path = _stats_cache_path_for(
            aoi_geojson, start_date, end_date, biopar_type, tag=f"ts_{aggregation_days}d"
        )

        if use_cache and cache_path.exists():
            try:
                cached = json.loads(cache_path.read_text(encoding="utf-8"))
                logger.info(f"[BIOPAR] timeseries cache hit: {cache_path.name}")
                return cached
            except Exception as e:
                logger.warning(f"Не удалось загрузить кэш серии: {e}")

        windows = _iter_date_windows(start_date, end_date, aggregation_days)
        timeline = []
        means = []

        logger.info(f"[BIOPAR] обработка {len(windows)} временных окон...")

        for i, (w_start, w_end) in enumerate(windows):
            try:
                logger.debug(f"[BIOPAR] окно {i+1}/{len(windows)}: {w_start}..{w_end}")
                tif = fetch_biopar_geotiff(aoi_geojson, w_start, w_end, biopar_type)
                st = compute_tiff_stats(tif, aoi_geojson=aoi_geojson)

                if st["mean"] is not None:
                    p50_val = st["percentiles"].get("p50")
                    timeline.append({
                        "date": w_end,
                        "mean": round(float(st["mean"]), 4),
                        "p50": p50_val,
                        "median": p50_val,  # Frontend expects median
                        "min": st.get("min"),
                        "max": st.get("max"),
                        "std": st.get("std")
                    })
                    means.append(float(st["mean"]))
                else:
                    timeline.append({"date": w_end, "mean": None})

            except Exception as e:
                logger.warning(f"[BIOPAR] окно {w_start}..{w_end} пропущено: {e}")
                timeline.append({"date": w_end, "mean": None, "error": str(e)})

        # Тренд по имеющимся значениям
        xs = [i for i, t in enumerate(timeline) if t.get("mean") is not None]
        ys = [t["mean"] for t in timeline if t.get("mean") is not None]

        if len(ys) >= 3:
            x_arr = np.asarray(xs, dtype=float)
            y_arr = np.asarray(ys, dtype=float)
            slope, _, r_value, p_value, _ = scipy_stats.linregress(x_arr, y_arr)

            if abs(slope) < 1e-4:
                direction = "stable"
            else:
                direction = "increasing" if slope > 0 else "decreasing"

            trend = {
                "direction": direction,
                "slope": round(float(slope), 6),
                "r_squared": round(float(r_value ** 2), 3),
                "p_value": round(float(p_value), 4),
                "description": f"{biopar_type} {direction} (R²={round(r_value**2, 3)})"
            }
        else:
            trend = {
                "direction": "insufficient_data",
                "slope": 0.0,
                "r_squared": 0.0,
                "p_value": 1.0,
                "description": "Недостаточно данных для анализа тренда"
            }

        # Transform to series format for timeseries endpoint
        series = []
        for item in timeline:
            if item.get("mean") is not None:
                series.append({
                    "date": item["date"],
                    "value": item["mean"],
                    "aggregation_window": aggregation_days
                })

        result = {
            "status": "success",
            "biopar_type": biopar_type,
            "series": series,
            "timeline": timeline,  # Frontend expects this
            "trend": trend,        # Frontend expects this
            "aggregation_days": aggregation_days
        }

        if use_cache:
            try:
                cache_path.write_text(
                    json.dumps(result, ensure_ascii=False, indent=2),
                    encoding="utf-8"
                )
                logger.info(f"[BIOPAR] timeseries cached: {cache_path.name}")
            except Exception as e:
                logger.warning(f"Не удалось сохранить кэш серии: {e}")

        return result

    except Exception as e:
        logger.error(f"[BIOPAR] ошибка временного ряда: {e}", exc_info=True)
        return {
            "status": "error",
            "message": str(e),
            "biopar_type": biopar_type,
            "series": [],
            "aggregation_days": aggregation_days
        }


# ---------------------- Классификация статусов ---------------------- #

def classify_biopar_status(biopar_type: str, mean_value: Optional[float]) -> Dict[str, str]:
    """
    Классификация состояния растительности по биопараметрам.
    Пороговые значения откалиброваны для сельскохозяйственных культур.
    
    Args:
        biopar_type: Тип параметра (FAPAR, LAI, FCOVER, CCC, CWC)
        mean_value: Среднее значение параметра
        
    Returns:
        Dict: Статус, уровень и описание
    """
    if mean_value is None:
        return {
            "status": "no_data",
            "level": "Нет данных",
            "description": "Не удалось оценить параметры"
        }

    t = biopar_type.upper()

    if t == "FAPAR":  # Fraction of Absorbed PAR: 0..1
        v = mean_value
        if v < 0.1:
            s, l, d = (
                "very_low",
                "Очень низкий",
                "Слабое поглощение PAR, возможен стресс или редкая растительность"
            )
        elif v < 0.25:
            s, l, d = (
                "low",
                "Низкий",
                "Ниже нормы, ранняя фаза развития или стресс"
            )
        elif v < 0.5:
            s, l, d = (
                "moderate",
                "Средний",
                "Умеренное поглощение, развивающаяся листовая масса"
            )
        elif v < 0.7:
            s, l, d = (
                "optimal",
                "Оптимальный",
                "Здоровая листовая масса, активный фотосинтез"
            )
        else:
            s, l, d = (
                "high",
                "Высокий",
                "Очень плотный покров, насыщенная листовая масса"
            )
            
    elif t == "LAI":  # Leaf Area Index: 0..6+
        v = mean_value
        if v < 0.5:
            s, l, d = (
                "very_low",
                "Очень низкий",
                "Малая площадь зелёной поверхности, начало вегетации"
            )
        elif v < 1.5:
            s, l, d = (
                "low",
                "Низкий",
                "Разреженный покров, ранняя стадия развития"
            )
        elif v < 3.0:
            s, l, d = (
                "moderate",
                "Средний",
                "Умеренная листовая масса, активный рост"
            )
        elif v < 5.0:
            s, l, d = (
                "optimal",
                "Оптимальный",
                "Хорошо развитая листовая масса"
            )
        else:
            s, l, d = (
                "high",
                "Высокий",
                "Очень густой покров, возможно лесные насаждения"
            )
            
    elif t == "FCOVER":  # Fraction of vegetation cover: 0..1
        v = mean_value
        if v < 0.2:
            s, l, d = (
                "very_low",
                "Очень низкий",
                "Небольшая доля покрытия растительностью"
            )
        elif v < 0.4:
            s, l, d = (
                "low",
                "Низкий",
                "Фрагментарное покрытие, заметна почва"
            )
        elif v < 0.6:
            s, l, d = (
                "moderate",
                "Средний",
                "Умеренная доля покрытия"
            )
        elif v < 0.8:
            s, l, d = (
                "optimal",
                "Оптимальный",
                "Преимущественно покрытая поверхность"
            )
        else:
            s, l, d = (
                "high",
                "Высокий",
                "Практически сплошное покрытие"
            )
            
    elif t == "CCC":  # Canopy Chlorophyll Content: g/m²
        v = mean_value
        if v < 50:
            s, l, d = (
                "very_low",
                "Очень низкий",
                "Критически низкое содержание хлорофилла"
            )
        elif v < 100:
            s, l, d = (
                "low",
                "Низкий",
                "Пониженное содержание, возможен хлороз"
            )
        elif v < 200:
            s, l, d = (
                "moderate",
                "Средний",
                "Нормальное содержание для большинства культур"
            )
        elif v < 300:
            s, l, d = (
                "optimal",
                "Оптимальный",
                "Высокое содержание, активный фотосинтез"
            )
        else:
            s, l, d = (
                "high",
                "Высокий",
                "Очень высокое содержание хлорофилла"
            )
            
    elif t == "CWC":  # Canopy Water Content: g/m²
        v = mean_value
        if v < 100:
            s, l, d = (
                "very_low",
                "Очень низкий",
                "Критически низкое содержание воды, стресс"
            )
        elif v < 200:
            s, l, d = (
                "low",
                "Низкий",
                "Пониженное содержание, возможен водный стресс"
            )
        elif v < 400:
            s, l, d = (
                "moderate",
                "Средний",
                "Нормальное содержание воды"
            )
        elif v < 600:
            s, l, d = (
                "optimal",
                "Оптимальный",
                "Хорошая оводнённость"
            )
        else:
            s, l, d = (
                "high",
                "Высокий",
                "Высокое содержание воды"
            )
    else:
        s, l, d = (
            "neutral",
            "Неизвестный тип",
            "Статус не определён для данного параметра"
        )

    return {"status": s, "level": l, "description": d}


# ---------------------- Рекомендации ---------------------- #

def generate_recommendations_biopar(
    biopar_type: str,
    statistics: Dict[str, Any],
    trend: Dict[str, Any]
) -> List[str]:
    """
    Генерирует агрономические рекомендации на основе биопараметров и трендов.
    
    Args:
        biopar_type: Тип параметра
        statistics: Статистика параметра
        trend: Информация о тренде
        
    Returns:
        List[str]: Список рекомендаций
    """
    rec = []
    mean_val = statistics.get("mean")

    status = classify_biopar_status(biopar_type, mean_val)
    status_level = status["status"]
    
    # Общие рекомендации по уровню
    if status_level in ("very_low", "low"):
        rec.append(
            "⚠️ Параметр ниже нормы: требуется детальное обследование посевов"
        )
        rec.append(
            "🔍 Проверьте водный режим, питание и наличие вредителей/болезней"
        )
        rec.append(
            "💧 Рассмотрите корректировку системы орошения или внесения удобрений"
        )
    elif status_level == "moderate":
        rec.append(
            "ℹ️ Умеренные значения: усильте мониторинг каждые 5–7 дней"
        )
        rec.append(
            "📊 Сравните с данными прошлых лет для выявления отклонений"
        )
    elif status_level in ("optimal", "high"):
        rec.append(
            "✅ Параметры в норме или выше: продолжайте текущий режим агротехники"
        )
        rec.append(
            "📅 Поддерживайте регулярный мониторинг каждые 10–14 дней"
        )
    else:
        rec.append(
            "ℹ️ Интерпретация зависит от культуры и фазы развития"
        )

    # Специфичные рекомендации по типу
    if biopar_type == "FAPAR" and status_level in ("very_low", "low"):
        rec.append(
            "🌱 Низкий FAPAR: проверьте густоту посевов и равномерность всходов"
        )
    elif biopar_type == "LAI" and status_level in ("very_low", "low"):
        rec.append(
            "🌾 Низкий LAI: оцените развитие листового аппарата и фазу развития"
        )
    elif biopar_type == "CCC" and status_level in ("very_low", "low"):
        rec.append(
            "🍃 Низкий хлорофилл: возможен дефицит азота или хлороз"
        )
        rec.append(
            "🧪 Рекомендуется листовая диагностика и почвенный анализ"
        )
    elif biopar_type == "CWC" and status_level in ("very_low", "low"):
        rec.append(
            "💧 Низкое содержание воды: вероятен водный стресс"
        )
        rec.append(
            "🌡️ Проверьте режим орошения и метеоусловия"
        )

    # Рекомендации по тренду
    trend_dir = trend.get("direction", "stable")
    r_squared = trend.get("r_squared", 0)
    
    if trend_dir == "decreasing" and r_squared > 0.5:
        rec.append(
            "📉 Выраженный нисходящий тренд: необходима срочная диагностика"
        )
        rec.append(
            "🔧 Проверьте историю обработок и погодные условия за период"
        )
    elif trend_dir == "increasing" and r_squared > 0.5:
        rec.append(
            "📈 Положительный тренд: состояние посевов улучшается"
        )
    elif trend_dir == "stable":
        rec.append(
            "➡️ Стабильная динамика: мониторьте дальнейшее развитие"
        )

    # Общие рекомендации
    rec.append(
        "🛰️ Комбинируйте с данными NDVI, EVI и метеорологией для комплексной оценки"
    )
    rec.append(
        "📈 Ведите историю наблюдений для выявления многолетних трендов"
    )

    return rec


# ---------------------- Итоговый отчёт ---------------------- #

def generate_biopar_report(
    aoi_geojson: Dict[str, Any],
    date: str,
    period_days: int = 30,
    biopar_type: str = "FAPAR",
    aggregation_days: int = 10
) -> Dict[str, Any]:
    """
    Сводный отчёт по BIOPAR за период [date - period_days + 1 .. date].
    Возвращает агрегированную статистику, временной ряд и рекомендации.
    
    Args:
        aoi_geojson: GeoJSON Polygon
        date: Конечная дата отчёта (YYYY-MM-DD)
        period_days: Длина периода в днях
        biopar_type: Тип биопараметра
        aggregation_days: Размер окна для временного ряда
        
    Returns:
        Dict: Детальный отчёт с рекомендациями
    """
    try:
        biopar_type = biopar_type.upper()
        end = datetime.strptime(date, "%Y-%m-%d")
        start = end - timedelta(days=period_days - 1)
        start_str = start.strftime("%Y-%m-%d")
        end_str = end.strftime("%Y-%m-%d")

        logger.info(
            f"[BIOPAR] генерация отчёта: {biopar_type} {start_str}..{end_str}"
        )

        # Временной ряд
        ts = get_biopar_timeseries(
            aoi_geojson=aoi_geojson,
            start_date=start_str,
            end_date=end_str,
            biopar_type=biopar_type,
            aggregation_days=aggregation_days,
            use_cache=True
        )
        
        timeline = ts.get("timeline", [])
        trend = ts.get("trend", {
            "direction": "insufficient_data",
            "slope": 0.0,
            "r_squared": 0.0,
            "p_value": 1.0
        })

        # Полная статистика
        stats_full = get_biopar_statistics(
            aoi_geojson=aoi_geojson,
            start_date=start_str,
            end_date=end_str,
            biopar_type=biopar_type,
            use_cache=True
        )["statistics"]

        status_info = classify_biopar_status(biopar_type, stats_full.get("mean"))
        recs = generate_recommendations_biopar(biopar_type, stats_full, trend)

        return {
            "status": "success",
            "biopar_type": biopar_type,
            "report_date": date,
            "period_analyzed": f"{start_str} – {end_str}",
            "summary": {
                "overall": status_info["level"],
                "description": status_info["description"],
                "trend": trend.get("description", ""),
                "status": status_info
            },
            "statistics": stats_full,
            "timeline": timeline,
            "recommendations": recs,
            "total_observations": ts.get("total_observations", 0)
        }
        
    except Exception as e:
        logger.error(f"[BIOPAR] ошибка генерации отчёта: {e}", exc_info=True)
        return {
            "status": "error",
            "message": str(e),
            "biopar_type": biopar_type,
            "report_date": date
        }


# ---------------------- Мульти-точки ---------------------- #

def get_multiple_points_timeseries_biopar(
    points: List[Tuple[float, float]],
    aoi_geojson: Dict[str, Any],
    start_date: str,
    end_date: str,
    biopar_type: str = "FAPAR",
    aggregation_days: int = 10,
) -> Dict[str, Any]:
    """
    Временные ряды для нескольких точек.
    Упрощённая версия: возвращает одну серию (mean по AOI) для всех точек.
    Для настоящего point-sampling нужно создавать микро-bbox вокруг каждой точки.
    
    Args:
        points: Список координат (lon, lat)
        aoi_geojson: GeoJSON Polygon
        start_date: YYYY-MM-DD
        end_date: YYYY-MM-DD
        biopar_type: Тип параметра
        aggregation_days: Размер окна
        
    Returns:
        Dict: Временные ряды для всех точек
    """
    try:
        series = get_biopar_timeseries(
            aoi_geojson=aoi_geojson,
            start_date=start_date,
            end_date=end_date,
            biopar_type=biopar_type,
            aggregation_days=aggregation_days,
            use_cache=True
        )
        
        return {
            "status": "success" if series.get("timeline") is not None else "error",
            "biopar_type": biopar_type,
            "points": [
                {
                    "point_id": i,
                    "lon": lon,
                    "lat": lat,
                    "series": series.get("timeline", [])
                }
                for i, (lon, lat) in enumerate(points)
            ],
            "total_points": len(points)
        }
        
    except Exception as e:
        logger.error(f"[BIOPAR] ошибка мульти-точек: {e}", exc_info=True)
        return {
            "status": "error",
            "message": str(e),
            "biopar_type": biopar_type,
            "points": []
        }