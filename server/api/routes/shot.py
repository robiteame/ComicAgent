import asyncio
import json
import traceback
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from agent.nodes import quality_check, video_compose, voice_gen
from api.websocket import ws_manager
from db import SessionLocal, get_db
from models import Character, Project, SceneAsset, Shot
from services.image_service import ImageService
from services.tts_service import TTSService

router = APIRouter(prefix="/api/shot", tags=["shot"])

image_service = ImageService()
tts_service = TTSService()
_regeneration_tasks: set[asyncio.Task] = set()
_pipeline_phase2_tasks: set[asyncio.Task] = set()


class ShotUpdate(BaseModel):
    shot_type: str | None = None
    scene_description: str | None = None
    character_action: str | None = None
    dialogue: str | None = None
    camera_angle: str | None = None
    duration: float | None = None
    emotion: str | None = None
    transition: str | None = None
    scene_asset_id: str | None = None
    character_asset_ids: list[str] | None = None


class RegenerateRequest(BaseModel):
    reason: str = ""
    new_emotion: str | None = None
    new_scene: str | None = None
    new_camera_angle: str | None = None


class StoryboardGenerateRequest(BaseModel):
    shot_ids: list[str] = []


@router.get("/{project_id}/shots")
async def get_project_shots(project_id: str, db: Session = Depends(get_db)):
    shots = db.query(Shot).filter(Shot.project_id == project_id).order_by(Shot.sequence).all()
    return [_serialize_shot(s) for s in shots]


@router.put("/{shot_id}")
async def update_shot(shot_id: str, data: ShotUpdate, db: Session = Depends(get_db)):
    shot = db.query(Shot).filter(Shot.id == shot_id).first()
    if not shot:
        raise HTTPException(status_code=404, detail="镜头不存在")

    changed = data.model_dump(exclude_unset=True)
    for key, value in changed.items():
        if key == "character_asset_ids":
            setattr(shot, key, json.dumps(value or [], ensure_ascii=False))
        else:
            setattr(shot, key, value)

    if changed:
        shot.status = "pending"
        shot.audio_path = ""
        shot.confirmed = False
        shot.storyboard_status = "pending"
        shot.storyboard_path = ""
        shot.image_path = ""
        shot.version = (shot.version or 1) + 1

    db.commit()
    return {"id": shot.id, "status": "updated", "needs_render": bool(changed)}


@router.post("/{shot_id}/regenerate")
async def regenerate_shot(shot_id: str, data: RegenerateRequest, db: Session = Depends(get_db)):
    shot = db.query(Shot).filter(Shot.id == shot_id).first()
    if not shot:
        raise HTTPException(status_code=404, detail="镜头不存在")

    shot.status = "pending"
    shot.storyboard_status = "queued"
    shot.storyboard_path = ""
    shot.image_path = ""
    shot.version = (shot.version or 1) + 1
    if data.new_emotion:
        shot.emotion = data.new_emotion
    if data.new_scene:
        shot.scene_description = data.new_scene
    if data.new_camera_angle:
        shot.camera_angle = data.new_camera_angle
    db.commit()

    task = asyncio.create_task(_regenerate_single_shot(shot_id, data.reason))
    _regeneration_tasks.add(task)
    task.add_done_callback(_regeneration_tasks.discard)
    return {"id": shot.id, "status": "regenerating", "version": shot.version}


@router.post("/batch-regenerate")
async def batch_regenerate(shot_ids: list[str], reason: str = "", db: Session = Depends(get_db)):
    shots = db.query(Shot).filter(Shot.id.in_(shot_ids)).all()
    for shot in shots:
        shot.status = "pending"
        shot.storyboard_status = "queued"
        shot.storyboard_path = ""
        shot.image_path = ""
        shot.version = (shot.version or 1) + 1
    db.commit()

    for shot in shots:
        task = asyncio.create_task(_regenerate_single_shot(shot.id, reason))
        _regeneration_tasks.add(task)
        task.add_done_callback(_regeneration_tasks.discard)
    return {"updated": len(shots)}


@router.post("/{project_id}/generate-storyboard")
async def generate_storyboard_images(project_id: str, data: StoryboardGenerateRequest, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    query = db.query(Shot).filter(Shot.project_id == project_id)
    if data.shot_ids:
        query = query.filter(Shot.id.in_(data.shot_ids))
    shots = query.order_by(Shot.sequence).all()
    if not shots:
        raise HTTPException(status_code=404, detail="暂无可生成故事板的分镜")

    for shot in shots:
        shot.storyboard_status = "queued"
        shot.status = "pending"
    project.status = "storyboard_generating"
    db.commit()

    task = asyncio.create_task(_run_storyboard_generation(project_id, [shot.id for shot in shots]))
    _regeneration_tasks.add(task)
    task.add_done_callback(_regeneration_tasks.discard)
    return {"status": "storyboard_started", "project_id": project_id, "shots": len(shots)}


@router.post("/{project_id}/confirm-storyboard")
async def confirm_storyboard(project_id: str, db: Session = Depends(get_db)):
    shots = db.query(Shot).filter(Shot.project_id == project_id).order_by(Shot.sequence).all()
    if not shots:
        raise HTTPException(status_code=404, detail="该项目暂无分镜，请先生成分镜")
    unfinished = [shot.id for shot in shots if not shot.storyboard_path and not shot.image_path]
    if unfinished:
        raise HTTPException(status_code=400, detail="故事板尚未全部生成，不能触发视频生成")

    for shot in shots:
        shot.confirmed = True
        shot.status = "storyboard_approved"
    project = db.query(Project).filter(Project.id == project_id).first()
    if project:
        project.status = "rendering"
    db.commit()

    task = asyncio.create_task(_run_phase2_pipeline(project_id))
    _pipeline_phase2_tasks.add(task)
    task.add_done_callback(_pipeline_phase2_tasks.discard)
    return {"status": "video_phase_started", "project_id": project_id, "confirmed_shots": len(shots)}


async def _run_storyboard_generation(project_id: str, shot_ids: list[str]) -> None:
    db = SessionLocal()
    try:
        shots = db.query(Shot).filter(Shot.project_id == project_id, Shot.id.in_(shot_ids)).order_by(Shot.sequence).all()
        characters = _characters(db, project_id)
        scenes = _scenes(db, project_id)
        for index, shot in enumerate(shots):
            await _progress(project_id, "generate_storyboard_images", 48 + min(index * 4, 35), "正在生成线稿故事板")
            shot_data = _shot_dict(shot)
            shot_data["visual_notes"] = _storyboard_notes(shot, scenes)
            image_path = await image_service.generate_shot_image(
                shot=shot_data,
                characters=characters,
                style_params={"prompt_prefix": "monochrome clean storyboard line art, rough pencil layout, no color"},
                project_id=project_id,
                seed=42 + (shot.version or 1) * 100,
            )
            shot.image_path = image_path
            shot.storyboard_path = image_path
            shot.storyboard_status = "done"
            shot.status = "storyboard_done"
            db.commit()
            await ws_manager.send_to_project(
                project_id,
                {
                    "type": "shot_update",
                    "shot_id": shot.id,
                    "status": shot.status,
                    "image_path": shot.image_path,
                    "storyboard_path": shot.storyboard_path,
                },
            )

        project = db.query(Project).filter(Project.id == project_id).first()
        if project:
            project.status = "storyboard_ready"
            db.commit()
        await _progress(project_id, "wait_storyboard_approval", 72, "故事板已生成，等待人工审核")
        await ws_manager.send_to_project(project_id, {"type": "storyboard_ready", "project_id": project_id})
    except Exception as exc:
        db.rollback()
        project = db.query(Project).filter(Project.id == project_id).first()
        if project:
            project.status = "error"
            db.commit()
        await ws_manager.send_to_project(project_id, {"type": "error", "message": f"故事板生成失败: {exc}\n{traceback.format_exc()}"})
    finally:
        db.close()


async def _run_phase2_pipeline(project_id: str):
    db = SessionLocal()
    try:
        state = _load_state(db, project_id)
        await _progress(project_id, "phase2_start", 76, "故事板已审批，开始生成配音与成片")

        for step, progress, node, message in [
            ("generate_voice", 84, voice_gen.run, "正在合成角色对白音频"),
            ("compose_video", 94, video_compose.run, "正在拼接完整漫剧视频"),
            ("quality_check", 100, quality_check.run, "正在校验最终结果"),
        ]:
            await _progress(project_id, step, progress, message)
            state.update(await node(state))
            if step == "compose_video":
                video_path = state.get("video_path", "")
                if not video_path or not Path(video_path).exists():
                    raise RuntimeError("视频合成未生成最终文件")

        _persist_phase2(db, project_id, state)
        await ws_manager.send_to_project(
            project_id,
            {
                "type": "complete",
                "project_id": project_id,
                "shots": state.get("shots", []),
                "video_path": state.get("video_path", ""),
            },
        )
    except Exception as exc:
        print(f"成片生成失败: {exc}")
        print(traceback.format_exc())
        db.rollback()
        project = db.query(Project).filter(Project.id == project_id).first()
        if project:
            project.status = "error"
            db.commit()
        await ws_manager.send_to_project(project_id, {"type": "error", "message": f"成片生成失败: {exc}\n{traceback.format_exc()}"})
    finally:
        db.close()


async def _regenerate_single_shot(shot_id: str, reason: str = ""):
    db = SessionLocal()
    shot = None
    try:
        shot = db.query(Shot).filter(Shot.id == shot_id).first()
        if not shot:
            return
        characters = _characters(db, shot.project_id)
        scenes = _scenes(db, shot.project_id)
        shot_data = _shot_dict(shot)
        shot_data["visual_notes"] = reason or _storyboard_notes(shot, scenes)
        image_path = await image_service.generate_shot_image(
            shot=shot_data,
            characters=characters,
            style_params={"prompt_prefix": "monochrome clean storyboard line art, rough pencil layout, no color"},
            project_id=shot.project_id,
            seed=42 + (shot.version or 1) * 100,
        )
        shot.image_path = image_path
        shot.storyboard_path = image_path
        shot.storyboard_status = "done"
        shot.status = "storyboard_done"
        db.commit()
        await ws_manager.send_to_project(
            shot.project_id,
            {"type": "shot_update", "shot_id": shot.id, "status": shot.status, "image_path": shot.image_path, "storyboard_path": shot.storyboard_path},
        )
    except Exception as exc:
        db.rollback()
        if shot:
            shot.status = "failed"
            shot.storyboard_status = "failed"
            shot.visual_notes = f"重新生成故事板失败: {exc}"
            db.commit()
            await ws_manager.send_to_project(shot.project_id, {"type": "error", "message": shot.visual_notes})
    finally:
        db.close()


def _load_state(db, project_id: str) -> dict:
    project = db.query(Project).filter(Project.id == project_id).first()
    return {
        "project_id": project_id,
        "user_input": project.input_text if project else "",
        "input_type": "text",
        "uploaded_file_path": "",
        "file_type": "",
        "script_title": project.title if project else "",
        "genre": project.genre if project else "",
        "style_suggestion": project.style if project else "anime",
        "characters": _characters(db, project_id),
        "raw_script": "",
        "script_scenes": [],
        "logic_issues": [],
        "shots": [_shot_dict(s) for s in db.query(Shot).filter(Shot.project_id == project_id).order_by(Shot.sequence).all()],
        "style": project.style if project else "anime",
        "style_params": {},
        "output_format": project.output_format if project else "9:16",
        "resolution": project.resolution if project else "1080p",
        "platform": project.platform if project else "douyin",
        "target_duration": 60,
        "video_path": "",
        "current_step": "",
        "errors": [],
        "human_feedback": "",
        "needs_human_review": False,
        "storyboard_confirmed": True,
        "rag_context": [],
        "narrative_context": {},
        "generation_preferences": {},
    }


def _persist_phase2(db, project_id: str, state: dict) -> None:
    for shot in state.get("shots", []):
        db_shot = db.query(Shot).filter(Shot.id == shot.get("shot_id")).first()
        if not db_shot:
            continue
        db_shot.image_path = shot.get("image_path", db_shot.image_path)
        db_shot.storyboard_path = shot.get("storyboard_path", db_shot.storyboard_path)
        db_shot.audio_path = shot.get("audio_path", db_shot.audio_path)
        db_shot.status = shot.get("status", db_shot.status)
        db_shot.version = shot.get("version", db_shot.version)
        db_shot.visual_notes = shot.get("visual_notes", db_shot.visual_notes)
        db_shot.confirmed = True

    project = db.query(Project).filter(Project.id == project_id).first()
    if project:
        project.status = "completed"
    db.commit()


def _serialize_shot(s: Shot) -> dict:
    return {
        "id": s.id,
        "project_id": s.project_id,
        "sequence": s.sequence,
        "shot_type": s.shot_type,
        "scene_description": s.scene_description,
        "character_action": s.character_action,
        "dialogue": s.dialogue,
        "camera_angle": s.camera_angle,
        "duration": s.duration,
        "emotion": s.emotion,
        "transition": s.transition,
        "image_path": s.image_path,
        "storyboard_path": s.storyboard_path,
        "audio_path": s.audio_path,
        "status": s.status,
        "storyboard_status": s.storyboard_status,
        "version": s.version,
        "confirmed": s.confirmed,
        "characters_in_scene": json.loads(s.characters_in_scene) if s.characters_in_scene else [],
        "scene_asset_id": s.scene_asset_id or "",
        "character_asset_ids": json.loads(s.character_asset_ids) if s.character_asset_ids else [],
    }


def _shot_dict(s: Shot) -> dict:
    data = _serialize_shot(s)
    data["shot_id"] = data.pop("id")
    data["camera_movement"] = s.camera_movement or "静止"
    data["seed"] = 42
    data["visual_notes"] = s.visual_notes or ""
    if not data["image_path"] and data.get("storyboard_path"):
        data["image_path"] = data["storyboard_path"]
    return data


def _asset_project_id(db, project_id: str) -> str:
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        return project_id
    return project.parent_project_id or project.id


def _characters(db, project_id: str) -> list[dict]:
    asset_project_id = _asset_project_id(db, project_id)
    chars = db.query(Character).filter(Character.project_id == asset_project_id).all()
    return [
        {
            "id": c.id,
            "name": c.name,
            "appearance": json.loads(c.appearance) if c.appearance else {},
            "personality": c.personality or "",
            "visual_prompt": c.visual_prompt or "",
            "negative_prompt": c.negative_prompt or "",
            "voice_id": c.voice_id or "",
            "key_features": json.loads(c.key_features) if c.key_features else [],
            "emotion_variants": json.loads(c.emotion_variants) if c.emotion_variants else {},
            "reference_images": json.loads(c.reference_images) if c.reference_images else [],
            "seed": int(c.seed) if c.seed and c.seed.isdigit() else 42,
        }
        for c in chars
    ]


def _scenes(db, project_id: str) -> dict[str, dict]:
    asset_project_id = _asset_project_id(db, project_id)
    scenes = db.query(SceneAsset).filter(SceneAsset.project_id == asset_project_id).all()
    return {
        item.id: {
            "id": item.id,
            "name": item.name,
            "description": item.description,
            "visual_prompt": item.visual_prompt,
            "negative_prompt": item.negative_prompt,
            "key_features": json.loads(item.key_features) if item.key_features else [],
        }
        for item in scenes
    }


def _storyboard_notes(shot: Shot, scenes: dict[str, dict]) -> str:
    scene = scenes.get(shot.scene_asset_id or "")
    parts = ["line art storyboard panel, grayscale, clean readable staging"]
    if scene:
        parts.extend([scene.get("visual_prompt", ""), scene.get("description", "")])
    if shot.visual_notes:
        parts.append(shot.visual_notes)
    return ", ".join(part for part in parts if part)


async def _progress(project_id: str, step: str, progress: int, message: str):
    await ws_manager.send_to_project(project_id, {"type": "progress", "step": step, "progress": progress, "message": message})
