import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

sys.path.insert(0, str(Path(__file__).parent))

from api.routes import asset, character, chat, graph, project, render, script, shot  # noqa: E402
from api.websocket import ws_manager  # noqa: E402
from db import init_db  # noqa: E402


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    print("数据库初始化完成")
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
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(project.router)
app.include_router(asset.router)
app.include_router(script.router)
app.include_router(shot.router)
app.include_router(render.router)
app.include_router(chat.router)
app.include_router(graph.router)
app.include_router(character.router)

output_dir = Path(__file__).parent.parent / "output"
output_dir.mkdir(parents=True, exist_ok=True)
app.mount("/output", StaticFiles(directory=str(output_dir)), name="output")


@app.websocket("/ws/{project_id}")
async def websocket_endpoint(websocket: WebSocket, project_id: str):
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
    return {"status": "ok"}


if __name__ == "__main__":
    import os

    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", "8011")), reload=False)
