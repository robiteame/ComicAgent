import asyncio
import json
import os
import traceback
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from api.websocket import ws_manager
from config import settings
from db import SessionLocal, get_db
from models import Project, Shot as ShotModel
from services.ffmpeg_service import FFmpegService
from services.security import existing_file, validate_identifier
from services.task_registry import claim as claim_task, snapshot as task_snapshot, start as start_task, update_progress as update_job_progress

router = APIRouter(prefix="/api/render", tags=["render"])
ffmpeg_service = FFmpegService()

_render_tasks: set[asyncio.Task] = set()
_render_status: dict[str, dict] = {}
_render_locks: dict[str, asyncio.Lock] = {}


class RenderRequest(BaseModel):
    project_id: str
    output_format: str = "9:16"
    resolution: str = "1080p"


@router.post("")
async def render_video(data: RenderRequest, db=Depends(get_db)):
    try:
        validate_identifier(data.project_id, "项目 ID")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not db.query(Project).filter(Project.id == data.project_id).first():
        raise HTTPException(status_code=404, detail="项目不存在")
    task_key = f"project:{data.project_id}:render"
    if not claim_task(task_key, f"project:{data.project_id}"):
        return {"status": "rendering", "project_id": data.project_id, "deduplicated": True}
    task = start_task(task_key, _render_task(data.project_id, data.output_format, data.resolution))
    _render_tasks.add(task)
    task.add_done_callback(_render_tasks.discard)
    _render_status[data.project_id] = {"status": "rendering", "progress": 0}
    return {"status": "rendering", "project_id": data.project_id}


@router.get("/{project_id}/status")
async def get_render_status(project_id: str):
    try:
        validate_identifier(project_id, "项目 ID")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    task_key = f"project:{project_id}:render"
    durable = task_snapshot(task_key)
    memory = _render_status.get(project_id)
    db = SessionLocal()
    try:
        project_status = db.query(Project.status).filter(Project.id == project_id).scalar()
    finally:
        db.close()
    final_path = settings.OUTPUT_DIR / "projects" / project_id / "output" / "final.mp4"
    valid_final = existing_file(final_path, minimum_size=1024, allowed_roots=(settings.OUTPUT_DIR,))
    if durable is None:
        if project_status == "completed" and valid_final:
            return {"project_id": project_id, "status": "completed", "progress": 100, "video_path": str(final_path)}
        if memory and memory.get("status") == "completed":
            memory = None
        return {"project_id": project_id, **(memory or {"status": "idle", "progress": 0})}

    status = durable["status"]
    if status in {"queued", "running"}:
        # The worker records its richer message in memory, while SQLite remains
        # the authority for ownership and survives a process restart.
        if memory and memory.get("status") in {"completed", "error"}:
            payload = memory
        else:
            payload = {**(memory or {}), "status": "rendering", "progress": durable["progress"]}
    elif status == "completed":
        if project_status != "completed":
            return {"project_id": project_id, "status": "idle", "progress": 0}
        payload = {"status": "completed", "progress": 100}
        if valid_final:
            payload["video_path"] = str(final_path)
        if memory and memory.get("status") == "completed":
            if memory.get("video_path"):
                payload["video_path"] = memory["video_path"]
    elif status in {"failed", "interrupted"}:
        payload = {"status": "error", "progress": durable["progress"], "message": durable["error"]}
    else:
        payload = {"status": "cancelled", "progress": durable["progress"], "message": durable["error"]}
    return {"project_id": project_id, **payload}


async def _render_task(project_id: str, output_format: str, resolution: str):
    lock = _render_locks.setdefault(project_id, asyncio.Lock())
    if lock.locked():
        raise RuntimeError("项目渲染任务已在运行")
    await lock.acquire()
    staged_video: Path | None = None
    try:
        await _progress(project_id, "rendering", 0, "开始导出成片")
        db = SessionLocal()
        try:
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
            media_roots = (settings.OUTPUT_DIR, settings.ASSETS_DIR, settings.DATA_DIR)
            missing_media = [
                s.id
                for s in db_shots
                if existing_file(s.video_path, minimum_size=4096, allowed_roots=media_roots) is None
            ]
            if missing_media:
                raise ValueError(f"镜头视频文件不存在或无效: {', '.join(missing_media)}")

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
            manifest = {
                s.id: (s.version or 1, bool(s.confirmed), s.video_path or "", s.audio_path or "")
                for s in db_shots
            }
            project_manifest = (project.style, project.output_format, project.resolution) if project else None
        finally:
            db.close()
        _apply_post_profiles(shots)

        staged_video = Path(
            await ffmpeg_service.compose_video(
            shots=shots,
            output_format=output_format,
            resolution=resolution,
            project_id=project_id,
            publish=False,
            )
        )
        final_file = existing_file(staged_video, minimum_size=1024, allowed_roots=media_roots)
        if final_file is None:
            raise RuntimeError("FFmpeg 未生成有效的成片文件")

        video_path = _publish_render(project_id, staged_video, manifest, project_manifest)
        staged_video = None
        _render_status[project_id] = {"status": "completed", "progress": 100, "video_path": video_path}
        await ws_manager.send_to_project(
            project_id,
            {
                "type": "render_complete",
                "video_url": f"/output/projects/{project_id}/output/final.mp4",
                "duration": sum(float(s["duration"] or 0) for s in shots),
            },
        )
    except asyncio.CancelledError as exc:
        _render_status[project_id] = {"status": "cancelled", "progress": 0, "message": str(exc)}
        db = SessionLocal()
        try:
            project = db.query(Project).filter(Project.id == project_id).first()
            if project and project.status == "rendering":
                project.status = "assets_ready"
                db.commit()
        finally:
            db.close()
        raise
    except Exception as exc:
        _render_status[project_id] = {"status": "error", "progress": 0, "message": str(exc)}
        db = SessionLocal()
        try:
            project = db.query(Project).filter(Project.id == project_id).first()
            if project:
                project.status = "error"
                db.commit()
        finally:
            db.close()
        await ws_manager.send_to_project(project_id, {"type": "error", "message": f"导出失败: {exc}\n{traceback.format_exc()}"})
        # Do not swallow the error: automatic LangGraph callers must be able to
        # short-circuit instead of reaching END with a false success.
        raise
    finally:
        if staged_video is not None:
            staged_video.unlink(missing_ok=True)
        lock.release()


async def _progress(project_id: str, step: str, progress: int, message: str):
    _render_status[project_id] = {"status": "rendering", "progress": progress, "message": message}
    update_job_progress(f"project:{project_id}:render", progress)
    await ws_manager.send_to_project(project_id, {"type": "progress", "step": step, "progress": progress, "message": message})


def _json_dict(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _publish_render(
    project_id: str,
    staged_video: Path,
    manifest: dict[str, tuple],
    project_manifest: tuple | None,
) -> str:
    """Atomically validate the render inputs and promote its staged output."""

    db = SessionLocal()
    try:
        db.execute(text("BEGIN IMMEDIATE"))
        project = db.query(Project).filter(Project.id == project_id).first()
        current = db.query(ShotModel).filter(ShotModel.project_id == project_id).all()
        current_manifest = {
            shot.id: (shot.version or 1, bool(shot.confirmed), shot.video_path or "", shot.audio_path or "")
            for shot in current
        }
        current_project_manifest = (project.style, project.output_format, project.resolution) if project else None
        if not project or current_manifest != manifest or current_project_manifest != project_manifest:
            db.rollback()
            raise asyncio.CancelledError("渲染期间镜头已发生变化")
        final_path = settings.OUTPUT_DIR / "projects" / project_id / "output" / "final.mp4"
        final_path.parent.mkdir(parents=True, exist_ok=True)
        backup_path = final_path.with_name(f".final-{uuid.uuid4().hex}.previous")
        had_previous = final_path.exists()
        if had_previous:
            os.replace(final_path, backup_path)
        try:
            os.replace(staged_video, final_path)
            project.status = "completed"
            db.commit()
        except BaseException:
            db.rollback()
            final_path.unlink(missing_ok=True)
            if had_previous and backup_path.exists():
                os.replace(backup_path, final_path)
            raise
        try:
            backup_path.unlink(missing_ok=True)
        except OSError:
            # A committed render is valid even if best-effort cleanup is
            # delayed; leaving the backup avoids risking the published file.
            pass
        return str(final_path)
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


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
