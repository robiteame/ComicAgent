import sys
import asyncio
import shutil
import subprocess
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse

sys.path.insert(0, str(Path(__file__).parent))

from api.routes import asset, character, chat, graph, project, render, script, settings as settings_routes, shot  # noqa: E402
from api.websocket import ws_manager  # noqa: E402
from config import settings as app_settings  # noqa: E402
from db import engine, init_db  # noqa: E402
from services.task_registry import recover_interrupted  # noqa: E402
from services.local_auth import (  # noqa: E402
    configured_token,
    is_allowed_websocket_origin,
    is_public_path,
    is_token_valid,
    request_token,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    recovered_deletions = project.recover_staged_project_deletions()
    if recovered_deletions:
        print(f"已恢复 {recovered_deletions} 个上次中断的项目删除事务")
    interrupted = recover_interrupted()
    if interrupted:
        print(f"已标记 {interrupted} 个服务重启中断的后台任务")
    print("数据库初始化完成")
    try:
        from services.model_config_service import apply_model_config_to_settings

        apply_model_config_to_settings()
        print("模型与 API 自定义配置已加载")
    except Exception as exc:  # noqa: BLE001
        print(f"模型与 API 自定义配置加载失败（沿用默认配置）: {exc}")
    yield
    print("服务关闭")


app = FastAPI(
    title="AI 漫剧 Agent",
    description="AI 漫剧生产 Agent 后端服务",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    # 桌面客户端的渲染进程来源：开发态为 Vite Dev Server，打包态为 file:// (Origin 为 null)。
    # 不能与 allow_credentials=True 搭配使用通配符 "*"（浏览器会拒绝），因此显式列出来源。
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "null",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def local_auth_middleware(request: Request, call_next):
    expected = configured_token()
    if (
        not expected
        or request.method == "OPTIONS"
        or is_public_path(request.url.path)
        or is_token_valid(expected, request.headers.get("x-comic-agent-token") or request.query_params.get("token"))
    ):
        return await call_next(request)
    return JSONResponse(status_code=401, content={"detail": "invalid local auth token"})

app.include_router(project.router)
app.include_router(asset.router)
app.include_router(script.router)
app.include_router(settings_routes.router)
app.include_router(shot.router)
app.include_router(render.router)
app.include_router(chat.router)
app.include_router(graph.router)
app.include_router(character.router)

output_dir = app_settings.OUTPUT_DIR
output_dir.mkdir(parents=True, exist_ok=True)
app.mount("/output", StaticFiles(directory=str(output_dir)), name="output")


@app.websocket("/ws/{project_id}")
async def websocket_endpoint(websocket: WebSocket, project_id: str):
    expected = configured_token()
    provided = request_token(dict(websocket.headers), websocket.query_params.get("token"))
    if not is_allowed_websocket_origin(websocket.headers.get("origin")):
        await websocket.close(code=1008, reason="websocket origin not allowed")
        return
    if not is_token_valid(expected, provided):
        await websocket.close(code=1008, reason="invalid local auth token")
        return
    await ws_manager.connect(websocket, project_id)
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket, project_id)


@app.get("/")
async def root():
    return {"name": "AI 漫剧 Agent", "version": "0.1.0", "status": "running"}


@app.get("/health")
async def health():
    # The desktop shell uses this marker to distinguish ComicAgent from an
    # unrelated process that happens to occupy the fixed local API port.
    return {"status": "ok", "service": "comic-agent", "version": app.version}


@app.get("/livez")
async def livez():
    return {"status": "ok", "service": "comic-agent", "version": app.version}


@app.get("/readyz")
async def readyz():
    """Verify dependencies needed to accept render work, not just process liveness."""

    try:
        await asyncio.to_thread(_check_database)
        await asyncio.to_thread(_check_ffmpeg)
    except RuntimeError as exc:
        from fastapi import HTTPException

        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"status": "ok", "service": "comic-agent", "version": app.version, "database": "ok", "ffmpeg": "ok"}


def _check_database() -> None:
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("SELECT 1")
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("database unavailable") from exc


def _check_ffmpeg() -> None:
    executable = shutil.which("ffmpeg")
    if not executable:
        raise RuntimeError("ffmpeg unavailable")
    try:
        subprocess.run([executable, "-version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True, timeout=5)
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError("ffmpeg unavailable") from exc


if __name__ == "__main__":
    import os

    import uvicorn

    # The desktop client only needs a local API. Allow an explicit HOST for
    # deployments that intentionally expose the service, but keep the default
    # private to avoid exposing API keys and generated media on the LAN.
    host = os.getenv("HOST", "127.0.0.1")
    if host not in {"127.0.0.1", "localhost", "::1"} and not configured_token():
        raise SystemExit("HOST 绑定到非本机地址时必须设置 COMIC_AGENT_LOCAL_TOKEN")
    uvicorn.run("main:app", host=host, port=int(os.getenv("PORT", "8011")), reload=False)
