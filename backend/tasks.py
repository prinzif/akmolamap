# backend/tasks.py
from __future__ import annotations

import logging
from pathlib import Path
from time import sleep

from celery import Celery



from backend.settings import settings

logger = logging.getLogger(__name__)

# Celery app
celery_app = Celery(
    "akmola",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_BACKEND_URL,
)

@celery_app.task(name="download_and_cog")
def download_and_cog(product_id: str) -> dict:
    """
    Заглушка: “скачать и конвертировать в COG”.
    Для демо просто создаёт файл-плейсхолдер в COG_DIR.
    """
    logger.info("Task download_and_cog: %s", product_id)
    out_path = settings.COG_DIR / f"{product_id}.tif"
    try:
        # эмуляция работы
        sleep(2)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        # создаём плейсхолдер (в реальности — конвертация в COG)
        if not out_path.exists():
            out_path.write_bytes(b"COG_PLACEHOLDER")
        logger.info("COG готов: %s", out_path)
        return {"status": "ready", "product_id": product_id, "cog": str(out_path)}
    except Exception as e:
        logger.exception("Ошибка в download_and_cog(%s)", product_id)
        return {"status": "error", "product_id": product_id, "message": str(e)}
