"""核心路由：前端入口页与模型列表代理。"""
import asyncio

import openai
from fastapi import APIRouter, Form, HTTPException
from fastapi.responses import FileResponse

from task_store import PROJECT_ROOT

router = APIRouter()


@router.get("/")
async def read_root():
    """返回前端页面"""
    return FileResponse(str(PROJECT_ROOT / "static" / "index.html"))


@router.post("/api/models")
async def list_models(
    base_url: str = Form(default=""),
    api_key: str = Form(default=""),
):
    """Proxy: fetch model list from any OpenAI-compatible API."""
    effective_key = api_key
    effective_url = base_url.rstrip("/") or None

    if not effective_key:
        raise HTTPException(status_code=400, detail="API key is required")

    try:
        client = openai.OpenAI(api_key=effective_key, base_url=effective_url)
        resp = await asyncio.to_thread(client.models.list)
        models = [{"id": m.id, "name": getattr(m, "name", m.id)} for m in resp.data]
        # Sort by id for readability
        models.sort(key=lambda x: x["id"])
        return {"data": models}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


