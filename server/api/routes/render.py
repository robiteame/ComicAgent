import asyncio
import json
import traceback

from fastapi import APIRouter
from pydantic import BaseModel

from api.websocket import ws_manager
from db import SessionLocal
from models import Shot as ShotModel
from services.ffmpeg_service import FFmpegService

router = APIRouter(prefix="/api/render", tags=["render"])
ffmpeg_service = FFmpegService()

_render_tasks: set[asyncio.Task] = set()
_render_status: dict[str, dict] = {}


class RenderRequest(BaseModel):
    project_id: str
    output_format: str = "9:16"
    resolution: str = "1080p"


@router.post("")
async def render_video(data: RenderRequest):
    task = asyncio.create_task(_render_task(data.project_id, data.output_format, data.resolution))
    _render_tasks.add(task)
    task.add_done_callback(_render_tasks.discard)
    _render_status[data.project_id] = {"status": "rendering", "progress": 0}
    return {"status": "rendering", "project_id": data.project_id}


@router.get("/{project_id}/status")
async def get_render_status(project_id: str):
    return {"project_id": project_id, **_render_status.get(project_id, {"status": "idle", "progress": 0})}


async def _render_task(project_id: str, output_format: str, resolution: str):
    db = SessionLocal()
    try:
        await _progress(project_id, "rendering", 0, "开始导出成片")

        db_shots = db.query(ShotModel).filter(ShotModel.project_id == project_id).order_by(ShotModel.sequence).all()
        if not db_shots:
            raise ValueError("没有可导出的镜头")
        if any(not s.confirmed for s in db_shots):
            raise ValueError("故事板尚未人工审核通过，不能导出成片")
        if any(not (s.storyboard_path or s.image_path) for s in db_shots):
            raise ValueError("故事板尚未全部生成，不能导出成片")

        shots = [
            {
                "shot_id": s.id,
                "shot_type": s.shot_type,
                "scene_description": s.scene_description,
                "characters_in_scene": json.loads(s.characters_in_scene) if s.characters_in_scene else [],
                "character_action": s.character_action,
                "dialogue": s.dialogue,
                "camera_angle": s.camera_angle,
                "camera_movement": s.camera_movement,
                "emotion": s.emotion,
                "duration": s.duration,
                "transition": s.transition,
                "image_path": s.image_path or s.storyboard_path,
                "video_path": s.video_path,
                "audio_path": s.audio_path,
                "status": s.status,
                "version": s.version,
            }
            for s in db_shots
        ]

        video_path = await ffmpeg_service.compose_video(
            shots=shots,
            output_format=output_format,
            resolution=resolution,
            project_id=project_id,
        )

        _render_status[project_id] = {"status": "completed", "progress": 100, "video_path": video_path}
        await ws_manager.send_to_project(
            project_id,
            {
                "type": "render_complete",
                "video_url": f"/output/projects/{project_id}/output/final.mp4",
                "duration": sum(float(s["duration"] or 0) for s in shots),
            },
        )
    except Exception as exc:
        _render_status[project_id] = {"status": "error", "progress": 0, "message": str(exc)}
        await ws_manager.send_to_project(project_id, {"type": "error", "message": f"导出失败: {exc}\n{traceback.format_exc()}"})
    finally:
        db.close()


async def _progress(project_id: str, step: str, progress: int, message: str):
    _render_status[project_id] = {"status": "rendering", "progress": progress, "message": message}
    await ws_manager.send_to_project(project_id, {"type": "progress", "step": step, "progress": progress, "message": message})
