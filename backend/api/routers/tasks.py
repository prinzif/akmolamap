# backend/api/routers/tasks.py
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.tasks import celery_app, download_and_cog

router = APIRouter(prefix="/tasks", tags=["Tasks"])


class EnqueueResponse(BaseModel):
    status: str
    task_id: str
    product_id: str


@router.get("/health")
def tasks_health():
    """
    Простой health Celery: проверяем, что объект celery_app создан.
    (Глубокую проверку брокера/бэкенда можно добавить через inspect/ping.)
    """
    return {"ok": bool(celery_app)}


@router.get("/status/{task_id}")
def task_status(task_id: str):
    """
    Статус любой Celery-задачи по task_id.
    """
    try:
        async_result = celery_app.AsyncResult(task_id)
        return {
            "task_id": task_id,
            "state": async_result.state,
            "ready": async_result.ready(),
            "successful": async_result.successful(),
            "result": async_result.result if async_result.successful() else None,
        }
    except Exception as e:
        raise HTTPException(500, f"Failed to get task status: {e}")


@router.post("/sentinel/download/{product_id}", response_model=EnqueueResponse)
def sentinel_download(product_id: str):
    """
    Поставить в очередь задачу скачивания и COG-конвертации (заглушка).
    """
    try:
        task = download_and_cog.delay(product_id)
        return {"status": "queued", "task_id": task.id, "product_id": product_id}
    except Exception as e:
        raise HTTPException(500, f"Failed to enqueue download task: {e}")
