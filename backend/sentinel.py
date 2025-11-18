# backend/sentinel.py

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import requests

from backend.settings import settings

logger = logging.getLogger(__name__)

__all__ = [
    "search_products",
    "get_quicklook",
    "get_product_info",
    "check_cdse_health",
]


def _get_token() -> str:
    """
    Получение OAuth2 access_token для CDSE (Copernicus Data Space Ecosystem).
    """
    logger.debug("Requesting access_token from %s", settings.CDSE_TOKEN_URL)
    resp = requests.post(
        settings.CDSE_TOKEN_URL,
        data={
            "client_id": settings.CDSE_CLIENT_ID,
            "client_secret": settings.CDSE_CLIENT_SECRET,
            "grant_type": "client_credentials",
        },
        timeout=10,
    )
    resp.raise_for_status()
    token = resp.json()["access_token"]
    logger.debug("Token successfully obtained, length=%d", len(token))
    return token


def _iso_or_default(date_str: Optional[str], default_delta_days: int) -> str:
    """
    Привести YYYY-MM-DD к ISO8601Z, иначе вернуть now()-delta.
    """
    if date_str:
        try:
            return datetime.strptime(date_str, "%Y-%m-%d").isoformat() + "Z"
        except ValueError:
            pass
    return (datetime.now(timezone.utc) - timedelta(days=default_delta_days)).isoformat() + "Z"


def search_products(
    bbox: List[float],
    start: Optional[str],
    end: Optional[str],
    platform: str = "Sentinel-2",
    cloudmax: int = 40,
    limit: int = 20,
) -> List[Dict[str, Any]]:
    """
    Поиск продуктов Sentinel по CDSE OData API.
    Возвращает список словарей с ключами:
      product_id, title, beginposition, endposition, cloudcover,
      footprint_wkt, quicklook_url, size, platform, s3_path
    """
    logger.info(
        "CDSE search: bbox=%s start=%s end=%s platform=%s cloudmax=%s limit=%s",
        bbox, start, end, platform, cloudmax, limit,
    )
    try:
        token = _get_token()
        headers = {"Authorization": f"Bearer {token}"}

        # Геометрия запроса (BBOX) в WKT
        lonmin, latmin, lonmax, latmax = bbox
        area_wkt = (
            f"POLYGON(({lonmin} {latmin},{lonmax} {latmin},"
            f"{lonmax} {latmax},{lonmin} {latmax},{lonmin} {latmin}))"
        )
        logger.debug("WKT area: %s", area_wkt)

        date_start = _iso_or_default(start, default_delta_days=30)
        date_end   = _iso_or_default(end,   default_delta_days=0)
        logger.debug("Search period: %s - %s", date_start, date_end)

        # Фильтры OData
        filters: List[str] = []

        # Коллекция
        if platform == "Sentinel-2":
            filters.append("Collection/Name eq 'SENTINEL-2'")
        elif platform == "Sentinel-1":
            filters.append("Collection/Name eq 'SENTINEL-1'")

        # Временной интервал
        filters.append(f"ContentDate/Start ge {date_start}")
        filters.append(f"ContentDate/Start le {date_end}")

        # Пересечение с областью (WKT)
        filters.append(f"OData.CSC.Intersects(area=geography'SRID=4326;{area_wkt}')")

        # Облачность (только для S2)
        if platform == "Sentinel-2" and cloudmax < 100:
            filters.append(
                "Attributes/OData.CSC.DoubleAttribute/any(att:"
                "att/Name eq 'cloudCover' and "
                f"att/OData.CSC.DoubleAttribute/Value le {float(cloudmax)})"
            )

        filter_string = " and ".join(filters)

        url = f"{settings.CDSE_API_URL}/Products"
        params = {
            "$filter": filter_string,
            "$orderby": "ContentDate/Start desc",
            "$top": str(int(limit)),
            "$expand": "Attributes",
            "$select": "Id,Name,ContentDate,ContentLength,S3Path,Checksum,GeoFootprint",
        }

        logger.debug("CDSE GET %s params=%s", url, params)
        resp = requests.get(url, params=params, headers=headers, timeout=30)

        if resp.status_code != 200:
            logger.error("CDSE API error: %s - %s", resp.status_code, resp.text)
            resp.raise_for_status()

        data = resp.json()

        # === ДИАГНОСТИКА: проверка структуры ответа ===
        if data.get("value"):
            sample = data["value"][0]
            logger.info("=== CDSE RESPONSE DIAGNOSTIC ===")
            logger.info("Available keys: %s", list(sample.keys()))
            logger.info("GeoFootprint type: %s, value: %s", 
                        type(sample.get("GeoFootprint")), 
                        str(sample.get("GeoFootprint"))[:200])
            logger.info("Footprint: %s", sample.get("Footprint"))
            logger.info("================================")

        items: List[Dict[str, Any]] = []

        items: List[Dict[str, Any]] = []
        for entry in data.get("value", []):
            # Облачность
            cloud_cover: Optional[float] = None
            for attr in entry.get("Attributes", []):
                if attr.get("Name") == "cloudCover":
                    cloud_cover = attr.get("Value")
                    break

            # ---- Геометрия: WKT или GeoJSON -> WKT ----
            footprint_wkt: Optional[str] = None

            # CDSE иногда отдаёт сразу WKT-строку
            geofoot = (
                entry.get("GeoFootprint")
                or entry.get("Footprint")
                or entry.get("footprint")
            )

            if isinstance(geofoot, str):
                # Уже WKT
                footprint_wkt = geofoot.strip()

            elif isinstance(geofoot, dict):
                # GeoJSON -> WKT (Polygon/MultiPolygon)
                gtype = geofoot.get("type")
                coords = geofoot.get("coordinates") or []

                if gtype == "Polygon":
                    # coords: [ [ [lon,lat], ... ] ]
                    ring = coords[0] if coords else []
                    if ring:
                        wkt_coords = " ".join(f"{lon} {lat}" for lon, lat in ring)
                        footprint_wkt = f"POLYGON(({wkt_coords}))"

                elif gtype == "MultiPolygon":
                    # coords: [ [ [ [lon,lat], ... ] ], [ ... ] ]
                    polys: List[str] = []
                    for polygon in coords:
                        if polygon and polygon[0]:
                            wkt_coords = " ".join(f"{lon} {lat}" for lon, lat in polygon[0])
                            polys.append(f"(({wkt_coords}))")
                    if polys:
                        footprint_wkt = f"MULTIPOLYGON({','.join(polys)})"

            product_id = entry.get("Id")
            item = {
                "product_id": product_id,
                "title": entry.get("Name", "Unknown"),
                "beginposition": entry.get("ContentDate", {}).get("Start"),
                "endposition": entry.get("ContentDate", {}).get("End"),
                "cloudcover": cloud_cover,
                "footprint_wkt": footprint_wkt,
                "quicklook_url": f"/api/v1/sentinel/quicklook/{product_id}" if product_id else None,
                "size": entry.get("ContentLength"),
                "platform": platform,
                "s3_path": entry.get("S3Path"),
            }
            items.append(item)

        logger.info(
            "CDSE: найдено %d продуктов (reported count=%s)",
            len(items), data.get("@odata.count", len(items))
        )
        return items

    except requests.exceptions.Timeout:
        logger.error("Timeout while requesting CDSE API")
        raise Exception("CDSE API timeout")
    except requests.exceptions.RequestException as e:
        logger.error("Network error while requesting CDSE: %s", str(e))
        raise Exception(f"Network error: {str(e)}")
    except Exception as e:
        logger.exception("Неожиданная ошибка в search_products")
        raise Exception(f"Search failed: {str(e)}")


def get_quicklook(product_id: str) -> bytes:
    """
    Получить quicklook/thumbnail по product_id из CDSE.
    Возвращает байты изображения (JPEG/PNG).
    """
    logger.info("Quicklook: product_id=%s", product_id)
    if not product_id:
        raise ValueError("product_id is required")

    try:
        token = _get_token()
        headers = {"Authorization": f"Bearer {token}"}

        # CDSE: сначала Thumbnail, затем Quicklook (fallback)
        url_thumb = f"{settings.CDSE_API_URL}/Products({product_id})/Thumbnail"
        resp = requests.get(url_thumb, headers=headers, timeout=20)

        if resp.status_code == 404:
            logger.warning("Thumbnail not found for %s, trying Quicklook", product_id)
            url_quick = f"{settings.CDSE_API_URL}/Products({product_id})/Quicklook"
            resp = requests.get(url_quick, headers=headers, timeout=20)

        if resp.status_code == 404:
            logger.error("Quicklook unavailable for product %s", product_id)
            raise Exception(f"Quicklook not available for product {product_id}")

        resp.raise_for_status()

        ctype = resp.headers.get("Content-Type", "")
        if "image" not in ctype:
            logger.error("Received non-image: Content-Type=%s", ctype)
            raise Exception(f"Invalid content type: {ctype}")

        logger.debug("Quicklook OK: %d байт, %s", len(resp.content), ctype)
        return resp.content

    except requests.exceptions.Timeout:
        logger.error("Таймаут quicklook для %s", product_id)
        raise Exception("Quicklook timeout")
    except requests.exceptions.RequestException as e:
        logger.error("Сетевая ошибка quicklook: %s", str(e))
        raise Exception(f"Network error: {str(e)}")
    except Exception:
        logger.exception("Ошибка получения quicklook для %s", product_id)
        raise


def get_product_info(product_id: str) -> Dict[str, Any]:
    """
    Подтянуть детальную информацию по продукту, включая атрибуты.
    """
    logger.info("Product info: %s", product_id)
    try:
        token = _get_token()
        headers = {"Authorization": f"Bearer {token}"}

        url = f"{settings.CDSE_API_URL}/Products({product_id})"
        params = {"$expand": "Attributes"}  # Коллекцию не расширяем
        resp = requests.get(url, params=params, headers=headers, timeout=15)
        resp.raise_for_status()

        data = resp.json()
        info: Dict[str, Any] = {
            "id": data.get("Id"),
            "name": data.get("Name"),
            "size_mb": round((data.get("ContentLength", 0) or 0) / (1024 * 1024), 2),
            "content_date": data.get("ContentDate"),
            "modification_date": data.get("ModificationDate"),
            "collection": "Unknown",
            "s3_path": data.get("S3Path"),
            "checksum": data.get("Checksum"),
            "attributes": {},
        }

        for attr in data.get("Attributes", []):
            info["attributes"][attr.get("Name")] = attr.get("Value")

        logger.debug("Product info: %s", info)
        return info

    except Exception as e:
        logger.exception("Ошибка получения информации о продукте %s", product_id)
        raise Exception(f"Failed to get product info: {str(e)}")


def check_cdse_health() -> bool:
    """
    Простой healthcheck CDSE API: возвращает True если отвечает /Collections.
    """
    try:
        token = _get_token()
        headers = {"Authorization": f"Bearer {token}"}
        url = f"{settings.CDSE_API_URL}/Collections"
        params = {"$top": "1"}
        resp = requests.get(url, params=params, headers=headers, timeout=5)
        ok = resp.status_code == 200
        if ok:
            logger.info("CDSE API доступен")
        else:
            logger.warning("CDSE API вернул статус %s", resp.status_code)
        return ok
    except Exception as e:
        logger.error("CDSE API недоступен: %s", str(e))
        return False

