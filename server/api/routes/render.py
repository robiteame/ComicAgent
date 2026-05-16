from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from services.ffmpeg_service import FFmpegService
from api.websocket import ws_manager
import asyncio

router = APIRouter(prefix="/api/render", tags=["render"])
ffmpeg_service = FFmpegService()


class RenderRequest(BaseModel):
    project_id: str
    output_format: str = "9:16"
    resolution: str = "1080p"


@router.post("")
async def render_video(data: RenderRequest):
    """触发 FFmpeg 渲染成片"""
    # TODO: 从数据库获取镜头数据，调用 ffmpeg_service
    asyncio.create_task(
        _render_task(data.project_id, data.output_format, data.resolution)
    )
    return {"status": "rendering", "project_id": data.project_id}


@router.get("/{project_id}/status")
async def get_render_status(project_id: str):
    """查询渲染进度"""
    # TODO: 实现渲染状态查询
    return {"project_id": project_id, "status": "pending", "progress": 0}


async def _render_task(project_id: str, output_format: str, resolution: str):
    """异步渲染任务"""
    try:
        await ws_manager.send_to_project(
            project_id,
            {"type": "progress", "step": "rendering", "progress": 0, "message": "开始渲染..."},
        )

        # TODO: 从数据库获取 shots 并渲染

        await ws_manager.send_to_project(
            project_id,
            {"type": "render_complete", "video_url": "", "duration": 0},
        )
    except Exception as e:
        await ws_manager.send_to_project(
            project_id, {"type": "error", "message": f"渲染失败: {str(e)}"}
        )
