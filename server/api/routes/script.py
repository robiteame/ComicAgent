import os
import uuid
import aiofiles
from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from pydantic import BaseModel
from config import settings
from agent.graph import build_graph
from api.websocket import ws_manager
import asyncio

router = APIRouter(prefix="/api/script", tags=["script"])


class ScriptParseRequest(BaseModel):
    project_id: str
    user_input: str
    input_type: str = "text"  # text / file
    style: str = "anime"
    output_format: str = "9:16"
    resolution: str = "1080p"
    platform: str = "douyin"
    target_duration: int = 30


@router.post("/parse")
async def parse_script(data: ScriptParseRequest):
    """提交脚本，触发 Agent 流水线"""

    # 初始化状态
    initial_state = {
        "project_id": data.project_id,
        "user_input": data.user_input,
        "input_type": data.input_type,
        "uploaded_file_path": "",
        "file_type": "",
        "script_title": "",
        "genre": "",
        "style_suggestion": data.style,
        "characters": [],
        "raw_script": "",
        "script_scenes": [],
        "logic_issues": [],
        "shots": [],
        "style": data.style,
        "style_params": {},
        "output_format": data.output_format,
        "resolution": data.resolution,
        "platform": data.platform,
        "target_duration": data.target_duration,
        "video_path": "",
        "current_step": "",
        "errors": [],
        "human_feedback": "",
        "needs_human_review": False,
        "rag_context": [],
        "narrative_context": {},
        "generation_preferences": {},
    }

    # 异步执行 Agent 流水线
    asyncio.create_task(_run_pipeline(data.project_id, initial_state))

    return {"status": "started", "project_id": data.project_id}


@router.post("/upload")
async def upload_script(
    project_id: str = Form(...),
    file: UploadFile = File(...),
    style: str = Form("anime"),
    output_format: str = Form("9:16"),
    resolution: str = Form("1080p"),
    platform: str = Form("douyin"),
):
    """上传脚本文件"""

    # 保存文件
    upload_dir = settings.DATA_DIR / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)

    file_ext = os.path.splitext(file.filename)[1] if file.filename else ".txt"
    file_path = upload_dir / f"{project_id}{file_ext}"

    async with aiofiles.open(file_path, "wb") as f:
        content = await file.read()
        await f.write(content)

    # 读取文件内容
    async with aiofiles.open(file_path, "r", encoding="utf-8") as f:
        user_input = await f.read()

    # 触发解析
    initial_state = {
        "project_id": project_id,
        "user_input": user_input,
        "input_type": "file",
        "uploaded_file_path": str(file_path),
        "file_type": file_ext.lstrip("."),
        "script_title": "",
        "genre": "",
        "style_suggestion": style,
        "characters": [],
        "raw_script": "",
        "script_scenes": [],
        "logic_issues": [],
        "shots": [],
        "style": style,
        "style_params": {},
        "output_format": output_format,
        "resolution": resolution,
        "platform": platform,
        "target_duration": 30,
        "video_path": "",
        "current_step": "",
        "errors": [],
        "human_feedback": "",
        "needs_human_review": False,
        "rag_context": [],
        "narrative_context": {},
        "generation_preferences": {},
    }

    asyncio.create_task(_run_pipeline(project_id, initial_state))

    return {"status": "started", "project_id": project_id, "file": file.filename}


async def _run_pipeline(project_id: str, initial_state: dict):
    """执行 Agent 流水线"""
    try:
        graph = build_graph().compile()

        # 发送进度：开始
        await ws_manager.send_to_project(
            project_id,
            {"type": "progress", "step": "start", "progress": 0, "message": "开始处理..."},
        )

        # 执行流水线
        final_state = None
        async for event in graph.astream(initial_state):
            for node_name, node_output in event.items():
                final_state = node_output
                step = node_output.get("current_step", node_name)
                await ws_manager.send_to_project(
                    project_id,
                    {
                        "type": "progress",
                        "step": step,
                        "progress": _get_step_progress(step),
                        "message": f"完成: {step}",
                    },
                )

        # 发送完成
        await ws_manager.send_to_project(
            project_id,
            {
                "type": "complete",
                "project_id": project_id,
                "shots": final_state.get("shots", []) if final_state else [],
                "video_path": final_state.get("video_path", "") if final_state else "",
            },
        )

    except Exception as e:
        await ws_manager.send_to_project(
            project_id,
            {"type": "error", "message": str(e)},
        )


def _get_step_progress(step: str) -> int:
    """获取步骤进度百分比"""
    progress_map = {
        "parse_script": 20,
        "generate_storyboard": 40,
        "generate_images": 60,
        "generate_voice": 75,
        "compose_video": 90,
        "quality_check": 95,
    }
    return progress_map.get(step, 0)
