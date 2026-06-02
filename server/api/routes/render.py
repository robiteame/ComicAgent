import asyncio
import json
import traceback

from fastapi import APIRouter
from pydantic import BaseModel

from api.websocket import ws_manager
from db import SessionLocal
from models import Project, Shot as ShotModel
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
        project = db.query(Project).filter(Project.id == project_id).first()
        if project:
            project.status = "rendering"
            db.commit()

        db_shots = db.query(ShotModel).filter(ShotModel.project_id == project_id).order_by(ShotModel.sequence).all()
        if not db_shots:
            raise ValueError("没有可导出的镜头")
        if any(not s.confirmed for s in db_shots):
            raise ValueError("仍有镜头故事板未人工审核通过，不能导出成片")
        if any(not (s.storyboard_path or s.image_path) for s in db_shots):
            raise ValueError("仍有镜头未生成定稿故事板参考图，不能导出成片")
        if any(not s.video_path for s in db_shots):
            raise ValueError("仍有镜头未逐一生成视频，请先完成每个镜头的视频生成")

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
                "scene_group_id": s.scene_group_id or s.scene_asset_id or "",
                "continuity_profile": _json_dict(s.continuity_profile),
            }
            for s in db_shots
        ]
        _apply_post_profiles(shots)

        video_path = await ffmpeg_service.compose_video(
            shots=shots,
            output_format=output_format,
            resolution=resolution,
            project_id=project_id,
        )

        _render_status[project_id] = {"status": "completed", "progress": 100, "video_path": video_path}
        project = db.query(Project).filter(Project.id == project_id).first()
        if project:
            project.status = "completed"
            db.commit()
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
        project = db.query(Project).filter(Project.id == project_id).first()
        if project:
            project.status = "error"
            db.commit()
        await ws_manager.send_to_project(project_id, {"type": "error", "message": f"导出失败: {exc}\n{traceback.format_exc()}"})
    finally:
        db.close()


async def _progress(project_id: str, step: str, progress: int, message: str):
    _render_status[project_id] = {"status": "rendering", "progress": progress, "message": message}
    await ws_manager.send_to_project(project_id, {"type": "progress", "step": step, "progress": progress, "message": message})


def _json_dict(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _apply_post_profiles(shots: list[dict]) -> None:
    for index, shot in enumerate(shots):
        previous_shot = shots[index - 1] if index > 0 else None
        next_shot = shots[index + 1] if index + 1 < len(shots) else None
        profile = shot.get("continuity_profile") or {}
        scene_group = shot.get("scene_group_id") or ""
        previous_group = previous_shot.get("scene_group_id") if previous_shot else ""
        next_group = next_shot.get("scene_group_id") if next_shot else ""
        cross_in = bool(previous_shot and previous_group != scene_group)
        cross_out = bool(next_shot and next_group != scene_group)
        shot["post_profile"] = {
            "scene_group_id": scene_group,
            "transition_in": profile.get("cross_scene_transition") if cross_in else "hard cut",
            "transition_out": profile.get("cross_scene_transition") if cross_out else profile.get("same_scene_transition", "hard cut or 0.2s fade only"),
            "same_scene_fade_seconds": 0.2,
            "cross_scene_flash_seconds": 0.35,
            "cross_scene_in": cross_in,
            "cross_scene_out": cross_out,
            "lut": profile.get("lut", "project_scene_lut_locked"),
            "saturation": profile.get("saturation", "locked per scene group"),
            "sharpness": profile.get("sharpness", "locked per scene group"),
            "ambient_audio_policy": profile.get("ambient_audio_policy", "continuous room tone"),
        }
