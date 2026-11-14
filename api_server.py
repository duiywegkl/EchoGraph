"""Backend for the SillyTavern timeline and desktop status controls."""
import argparse
import os
import time
from pathlib import Path
from threading import Lock
from typing import Any, Dict

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from src.core.llm_client import LLMClient
from src.utils.config import config, reload_config

app = FastAPI(title="EchoGraph API", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])
_plugin_heartbeat_at = 0.0
_plugin_chat_uuid = None
_plugin_heartbeat_lock = Lock()

@app.post("/system/reload_config")
async def reload_system_config(request: Request):
    if request.client is None or request.client.host not in ("127.0.0.1", "::1"):
        raise HTTPException(status_code=403, detail="Local requests only")
    reload_config()
    safe_base_url = config.llm.base_url
    if safe_base_url and config.llm.api_key:
        safe_base_url = safe_base_url.replace(config.llm.api_key, "***")
    return {"ok": True, "llm_configured": bool(config.llm.api_key and config.llm.base_url),
            "base_url": safe_base_url, "model": config.llm.model}

@app.get("/system/liveness")
async def liveness():
    return {"ok": True, "version": "1.0.0"}

@app.post("/timeline/heartbeat")
async def timeline_heartbeat(body: dict):
    global _plugin_heartbeat_at, _plugin_chat_uuid
    chat_uuid = body.get("chat_uuid")
    if chat_uuid is not None and not isinstance(chat_uuid, str):
        raise HTTPException(status_code=400, detail="chat_uuid must be a string or null")
    with _plugin_heartbeat_lock:
        _plugin_heartbeat_at = time.monotonic()
        _plugin_chat_uuid = chat_uuid or None
    return {"ok": True}

@app.get("/system/plugin_status")
async def get_plugin_status():
    with _plugin_heartbeat_lock:
        connected = bool(_plugin_heartbeat_at) and time.monotonic() - _plugin_heartbeat_at < 30
        chat_uuid = _plugin_chat_uuid if connected else None
    return {"connected": connected, "chat_uuid": chat_uuid}

def _tavern_timeline_service():
    """Lazy creation keeps imports and TestClient construction away from real data."""
    service = getattr(app.state, 'tavern_timeline', None)
    if service is None:
        from pathlib import Path
        from src.timeline.tavern import TavernTimeline
        default_root = Path(__file__).resolve().parent / 'data' / 'tavern_timeline'
        service = TavernTimeline(
            Path(os.getenv('TIMELINE_TAVERN_DATA_ROOT', str(default_root))),
            LLMClient)
        app.state.tavern_timeline = service
    return service


def _timeline_call(callback):
    from src.timeline.store import StoreError
    from src.timeline.graph import GraphError
    try:
        return callback()
    except (ValueError, StoreError, GraphError, KeyError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post('/timeline/register')
async def timeline_register(body: dict):
    service = _tavern_timeline_service()
    return _timeline_call(lambda: service.register(
        body.get('chat_uuid'), body.get('integrity'), body.get('owner'),
        body.get('file_name'), body.get('previous_file_exists', False)))


@app.get('/timeline/identity/{chat_uuid}')
async def timeline_identity(chat_uuid: str):
    def lookup():
        try:
            chat = _tavern_timeline_service().store.get_chat(chat_uuid)
            return {'previous_file_name': chat['file_name'], 'owner': chat['owner']}
        except Exception:
            return {'previous_file_name': None, 'owner': None}
    return lookup()


@app.post('/timeline/base')
async def timeline_base(body: dict):
    service = _tavern_timeline_service()
    return _timeline_call(lambda: service.base(body.get('owner'),
        {'card': body.get('card', {}), 'books': body.get('books', [])}))


@app.post('/timeline/sync')
async def timeline_sync(body: dict):
    service = _tavern_timeline_service()
    return _timeline_call(lambda: service.sync(body.get('chat_uuid'),
        body.get('messages'), body.get('books')))


@app.get('/timeline/status/{chat_uuid}')
async def timeline_status(chat_uuid: str):
    return _timeline_call(lambda: _tavern_timeline_service().status(chat_uuid))


@app.post('/timeline/retry/{chat_uuid}')
async def timeline_retry(chat_uuid: str):
    return _timeline_call(lambda: _tavern_timeline_service().retry(chat_uuid))


@app.get('/timeline/graph/{chat_uuid}')
async def timeline_graph(chat_uuid: str):
    return _timeline_call(lambda: _tavern_timeline_service().graph(chat_uuid))


@app.post('/timeline/manual/{chat_uuid}')
async def timeline_manual(chat_uuid: str, body: dict):
    return _timeline_call(lambda: _tavern_timeline_service().edit(chat_uuid,
        body.get('op'), body.get('payload', {})))


@app.post('/timeline/undo/{chat_uuid}')
async def timeline_undo(chat_uuid: str):
    return _timeline_call(lambda: _tavern_timeline_service().history(chat_uuid, 'undo'))


@app.post('/timeline/redo/{chat_uuid}')
async def timeline_redo(chat_uuid: str):
    return _timeline_call(lambda: _tavern_timeline_service().history(chat_uuid, 'redo'))


@app.get('/timeline/prompt/{chat_uuid}')
async def timeline_prompt(chat_uuid: str):
    return _timeline_call(lambda: _tavern_timeline_service().prompt(chat_uuid))


@app.get('/timeline/current')
async def timeline_current():
    chat_uuid = _tavern_timeline_service().current_chat_uuid
    return {'has_session': bool(chat_uuid), 'chat_uuid': chat_uuid, 'session_id': chat_uuid}




# --- 服务器启动 ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="EchoGraph API Server")

    # 从环境变量获取默认端口
    from src.utils.config import config
    default_port = int(os.getenv("API_SERVER_PORT", "9543"))

    parser.add_argument("--port", type=int, default=default_port, help="Port to run the API server on")
    args = parser.parse_args()

    logger.info(f"Starting EchoGraph API server on port {args.port}...")
    uvicorn.run(app, host="127.0.0.1", port=args.port)
