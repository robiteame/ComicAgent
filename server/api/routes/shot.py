import asyncio
import json
import traceback

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.websocket import ws_manager
from db import SessionLocal, get_db
from models import Character, Project, SceneAsset, Shot
from services.consistency_service import ConsistencyService
from services.image_service import ImageService
from services.reference_asset_service import ReferenceAssetService
from services.style_templates import style_prompt_params
from services.tts_service import TTSService
from services.video_service import SeedanceVideoService

router = APIRouter(prefix="/api/shot", tags=["shot"])

image_service = ImageService()
tts_service = TTSService()
seedance_service = SeedanceVideoService()
consistency_service = ConsistencyService()
reference_asset_service = ReferenceAssetService()
_regeneration_tasks: set[asyncio.Task] = set()
_shot_video_tasks: set[asyncio.Task] = set()


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
    prompt: str | None = None
    visual_notes: str | None = None
    new_emotion: str | None = None
    new_scene: str | None = None
    new_camera_angle: str | None = None
    shot_type: str | None = None
    character_action: str | None = None
    dialogue: str | None = None
    duration: float | None = None


class StoryboardGenerateRequest(BaseModel):
    shot_ids: list[str] = []


class StoryboardApprovalRequest(BaseModel):
    approved: bool = True


class ShotVideoGenerateRequest(BaseModel):
    force: bool = False


@router.get("/{project_id}/shots")
async def get_project_shots(project_id: str, db: Session = Depends(get_db)):
    shots = db.query(Shot).filter(Shot.project_id == project_id).order_by(Shot.sequence).all()
    return [_serialize_shot(s) for s in shots]


@router.put("/{shot_id}")
async def update_shot(shot_id: str, data: ShotUpdate, db: Session = Depends(get_db)):
    shot = db.query(Shot).filter(Shot.id == shot_id).first()
    if not shot:
        raise HTTPException(status_code=404, detail="镜头不存在")

    _ensure_shot_unlocked(shot)
    previous_scene_key = _shot_scene_key(shot)
    changed = data.model_dump(exclude_unset=True)
    for key, value in changed.items():
        if key == "character_asset_ids":
            setattr(shot, key, json.dumps(value or [], ensure_ascii=False))
        else:
            setattr(shot, key, value)

    if changed:
        _invalidate_storyboard_outputs(shot)
        _invalidate_downstream_media(db, shot, {previous_scene_key, _shot_scene_key(shot)})
        shot.version = (shot.version or 1) + 1

    db.commit()
    return {"id": shot.id, "status": "updated", "needs_render": bool(changed)}


@router.post("/{shot_id}/regenerate")
async def regenerate_shot(shot_id: str, data: RegenerateRequest, db: Session = Depends(get_db)):
    shot = db.query(Shot).filter(Shot.id == shot_id).first()
    if not shot:
        raise HTTPException(status_code=404, detail="镜头不存在")

    _ensure_shot_unlocked(shot)
    previous_scene_key = _shot_scene_key(shot)
    _invalidate_storyboard_outputs(shot)
    _invalidate_downstream_media(db, shot, {previous_scene_key, _shot_scene_key(shot)})
    shot.status = "pending"
    shot.storyboard_status = "queued"
    shot.version = (shot.version or 1) + 1
    if data.new_emotion:
        shot.emotion = data.new_emotion
    if data.new_scene:
        shot.scene_description = data.new_scene
    if data.new_camera_angle:
        shot.camera_angle = data.new_camera_angle
    if data.shot_type:
        shot.shot_type = data.shot_type
    if data.character_action is not None:
        shot.character_action = data.character_action
    if data.dialogue is not None:
        shot.dialogue = data.dialogue
    if data.duration is not None:
        shot.duration = data.duration
    prompt = data.prompt if data.prompt is not None else data.visual_notes
    if prompt is not None:
        shot.visual_notes = prompt
    db.commit()

    task = asyncio.create_task(_regenerate_single_shot(shot_id, data.reason or prompt or ""))
    _regeneration_tasks.add(task)
    task.add_done_callback(_regeneration_tasks.discard)
    return {"id": shot.id, "status": "regenerating", "version": shot.version}


@router.post("/batch-regenerate")
async def batch_regenerate(shot_ids: list[str], reason: str = "", db: Session = Depends(get_db)):
    shots = db.query(Shot).filter(Shot.id.in_(shot_ids)).all()
    locked = [shot.id for shot in shots if shot.confirmed]
    if locked:
        raise HTTPException(status_code=423, detail=f"已审批镜头禁止重生成: {', '.join(locked)}")
    for shot in shots:
        previous_scene_key = _shot_scene_key(shot)
        _invalidate_storyboard_outputs(shot)
        _invalidate_downstream_media(db, shot, {previous_scene_key, _shot_scene_key(shot)})
        shot.status = "pending"
        shot.storyboard_status = "queued"
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
    locked = [shot.id for shot in shots if shot.confirmed]
    if locked:
        if data.shot_ids:
            raise HTTPException(status_code=423, detail=f"已审批镜头禁止重生成: {', '.join(locked)}")
        shots = [shot for shot in shots if not shot.confirmed]
    if not shots:
        raise HTTPException(status_code=404, detail="暂无可生成故事板的分镜")

    for shot in shots:
        previous_scene_key = _shot_scene_key(shot)
        _invalidate_storyboard_outputs(shot)
        _invalidate_downstream_media(db, shot, {previous_scene_key, _shot_scene_key(shot)})
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
        raise HTTPException(status_code=404, detail="暂无可确认的故事板分镜")
    unfinished = [shot.id for shot in shots if not shot.storyboard_path and not shot.image_path]
    if unfinished:
        raise HTTPException(status_code=400, detail="仍有镜头未生成定稿故事板")
    unapproved = [shot.id for shot in shots if not shot.confirmed]
    if unapproved:
        raise HTTPException(status_code=400, detail="仍有镜头未人工审核通过")

    project = db.query(Project).filter(Project.id == project_id).first()
    if project:
        project.status = "storyboard_approved"
    db.commit()

    return {"status": "storyboard_approved", "project_id": project_id, "confirmed_shots": len(shots)}


@router.post("/{shot_id}/approve-storyboard")
async def approve_storyboard(shot_id: str, data: StoryboardApprovalRequest, db: Session = Depends(get_db)):
    shot = db.query(Shot).filter(Shot.id == shot_id).first()
    if not shot:
        raise HTTPException(status_code=404, detail="镜头不存在")
    if data.approved and not (shot.storyboard_path or shot.image_path):
        raise HTTPException(status_code=400, detail="该镜头故事板尚未生成")
    shot.confirmed = bool(data.approved)
    shot.status = "storyboard_approved" if data.approved else "needs_review"
    if not data.approved:
        _invalidate_video_outputs(shot)
        _invalidate_downstream_media(db, shot)
    db.commit()
    return {"id": shot.id, "approved": shot.confirmed, "status": shot.status}


@router.post("/{shot_id}/generate-video")
async def generate_shot_video(shot_id: str, data: ShotVideoGenerateRequest, db: Session = Depends(get_db)):
    shot = db.query(Shot).filter(Shot.id == shot_id).first()
    if not shot:
        raise HTTPException(status_code=404, detail="镜头不存在")
    if not shot.confirmed:
        raise HTTPException(status_code=400, detail="请先审核通过该镜头故事板")
    if not (shot.storyboard_path or shot.image_path):
        raise HTTPException(status_code=400, detail="该镜头尚未生成定稿故事板")
    if _can_reuse_existing_video(shot, data.force):
        return {"id": shot.id, "status": shot.status, "video_path": shot.video_path, "audio_path": shot.audio_path}

    shot.status = "video_generating"
    db.commit()
    task = asyncio.create_task(_run_single_shot_video(shot_id, data.force))
    _shot_video_tasks.add(task)
    task.add_done_callback(_shot_video_tasks.discard)
    return {"id": shot.id, "status": "video_generating"}


async def _run_storyboard_generation(project_id: str, shot_ids: list[str]) -> None:
    db = SessionLocal()
    try:
        shots = db.query(Shot).filter(Shot.project_id == project_id, Shot.id.in_(shot_ids)).order_by(Shot.sequence).all()
        project = db.query(Project).filter(Project.id == project_id).first()
        characters = _characters(db, project_id)
        scenes = _scenes(db, project_id)
        await _ensure_scene_baselines(db, project, scenes)
        scenes = _scenes(db, project_id)
        for index, shot in enumerate(shots):
            await _progress(project_id, "generate_storyboard_images", 48 + min(index * 4, 35), "正在生成定稿故事板参考图")
            shot_data = _shot_dict(shot)
            shot_data["visual_notes"] = _storyboard_notes(shot, scenes)
            previous_reference = _previous_reference_for_shot(db, shot)
            shot_data.update(
                consistency_service.build_generation_context(
                    shot_data,
                    characters,
                    scenes,
                    previous_reference_path=previous_reference,
                    for_video=False,
                )
            )
            _materialize_control_references(project_id, shot_data)
            image_path = await image_service.generate_shot_image(
                shot=shot_data,
                characters=characters,
                style_params=_storyboard_style_params(project),
                project_id=project_id,
                seed=42 + (shot.version or 1) * 100,
            )
            shot.scene_group_id = shot_data.get("scene_group_id", shot.scene_group_id)
            shot.consistency_context = shot_data.get("consistency_context", shot.consistency_context)
            shot.reference_weights = json.dumps(shot_data.get("reference_weights", {}), ensure_ascii=False)
            shot.continuity_profile = json.dumps(shot_data.get("continuity_profile", {}), ensure_ascii=False)
            shot.continuity_reference_path = previous_reference
            shot.pose_reference_path = shot_data.get("pose_reference_path", "")
            shot.depth_reference_path = shot_data.get("depth_reference_path", "")
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
                    "audio_path": shot.audio_path,
                    "video_path": shot.video_path,
                    "last_frame_path": shot.last_frame_path,
                    "scene_group_id": shot.scene_group_id,
                    "reference_weights": _json_dict(shot.reference_weights),
                    "continuity_profile": _json_dict(shot.continuity_profile),
                    "continuity_reference_path": shot.continuity_reference_path,
                    "pose_reference_path": shot.pose_reference_path,
                    "depth_reference_path": shot.depth_reference_path,
                },
            )

        project = db.query(Project).filter(Project.id == project_id).first()
        if project:
            project.status = "storyboard_ready"
            db.commit()
        await _progress(project_id, "wait_storyboard_approval", 72, "定稿故事板参考图已生成，等待人工审核")
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


async def _regenerate_single_shot(shot_id: str, reason: str = ""):
    db = SessionLocal()
    shot = None
    try:
        shot = db.query(Shot).filter(Shot.id == shot_id).first()
        if not shot:
            return
        project = db.query(Project).filter(Project.id == shot.project_id).first()
        characters = _characters(db, shot.project_id)
        scenes = _scenes(db, shot.project_id)
        await _ensure_scene_baselines(db, project, scenes)
        scenes = _scenes(db, shot.project_id)
        shot_data = _shot_dict(shot)
        shot_data["visual_notes"] = reason or _storyboard_notes(shot, scenes)
        previous_reference = _previous_reference_for_shot(db, shot)
        shot_data.update(
            consistency_service.build_generation_context(
                shot_data,
                characters,
                scenes,
                previous_reference_path=previous_reference,
                for_video=False,
            )
        )
        _materialize_control_references(shot.project_id, shot_data)
        image_path = await image_service.generate_shot_image(
            shot=shot_data,
            characters=characters,
            style_params=_storyboard_style_params(project),
            project_id=shot.project_id,
            seed=42 + (shot.version or 1) * 100,
        )
        shot.scene_group_id = shot_data.get("scene_group_id", shot.scene_group_id)
        shot.consistency_context = shot_data.get("consistency_context", shot.consistency_context)
        shot.reference_weights = json.dumps(shot_data.get("reference_weights", {}), ensure_ascii=False)
        shot.continuity_profile = json.dumps(shot_data.get("continuity_profile", {}), ensure_ascii=False)
        shot.continuity_reference_path = previous_reference
        shot.pose_reference_path = shot_data.get("pose_reference_path", "")
        shot.depth_reference_path = shot_data.get("depth_reference_path", "")
        shot.image_path = image_path
        shot.storyboard_path = image_path
        shot.storyboard_status = "done"
        shot.status = "storyboard_done"
        db.commit()
        await ws_manager.send_to_project(
            shot.project_id,
            {
                "type": "shot_update",
                "shot_id": shot.id,
                "status": shot.status,
                "image_path": shot.image_path,
                "storyboard_path": shot.storyboard_path,
                "audio_path": shot.audio_path,
                "video_path": shot.video_path,
                "last_frame_path": shot.last_frame_path,
                "scene_group_id": shot.scene_group_id,
                "reference_weights": _json_dict(shot.reference_weights),
                "continuity_profile": _json_dict(shot.continuity_profile),
                "continuity_reference_path": shot.continuity_reference_path,
                "pose_reference_path": shot.pose_reference_path,
                "depth_reference_path": shot.depth_reference_path,
            },
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


async def _run_single_shot_video(shot_id: str, force: bool = False) -> None:
    db = SessionLocal()
    shot = None
    try:
        shot = db.query(Shot).filter(Shot.id == shot_id).first()
        if not shot:
            return
        if _can_reuse_existing_video(shot, force):
            return

        project_id = shot.project_id
        project = db.query(Project).filter(Project.id == project_id).first()
        characters = _characters(db, project_id)
        scenes = _scenes(db, project_id)
        await _ensure_scene_baselines(db, project, scenes)
        scenes = _scenes(db, project_id)
        shot_data = _shot_dict(shot)
        shot_data["storyboard_prompt"] = _storyboard_notes(shot, scenes)
        if project:
            shot_data["output_format"] = project.output_format or "9:16"
            shot_data["style"] = project.style or "anime"
        previous_reference = _previous_reference_for_shot(db, shot, prefer_last_frame=True)
        shot_data.update(
            consistency_service.build_generation_context(
                shot_data,
                characters,
                scenes,
                previous_reference_path=previous_reference,
                for_video=True,
            )
        )
        _materialize_control_references(project_id, shot_data)

        await _progress(project_id, "generate_voice", 82, f"正在生成镜头 {shot.sequence} 的角色配音")
        if shot.dialogue:
            speaker = (json.loads(shot.characters_in_scene) if shot.characters_in_scene else [""])[0]
            voice_id = next((item.get("voice_id", "") for item in characters if item.get("name") == speaker), "")
            shot.audio_path = await tts_service.generate_dialogue(
                text=shot.dialogue,
                voice_id=voice_id,
                emotion=shot.emotion or "neutral",
                project_id=project_id,
                shot_id=shot.id,
            )
            shot_data["audio_path"] = shot.audio_path

        await _progress(project_id, "generate_seedance_video", 90, f"正在生成镜头 {shot.sequence} 的 Seedance 视频")
        result = await seedance_service.generate_shot_video(shot_data, characters, scenes, project_id)
        continuity_profile = shot_data.get("continuity_profile", {}) or {}
        if result.get("reference_payload_mode"):
            continuity_profile["seedance_reference_payload_mode"] = result["reference_payload_mode"]
            shot_data["continuity_profile"] = continuity_profile
        shot.scene_group_id = shot_data.get("scene_group_id", shot.scene_group_id)
        shot.consistency_context = shot_data.get("consistency_context", shot.consistency_context)
        shot.reference_weights = json.dumps(shot_data.get("reference_weights", {}), ensure_ascii=False)
        shot.continuity_profile = json.dumps(shot_data.get("continuity_profile", {}), ensure_ascii=False)
        shot.continuity_reference_path = previous_reference
        shot.pose_reference_path = shot_data.get("pose_reference_path", "")
        shot.depth_reference_path = shot_data.get("depth_reference_path", "")
        shot.video_path = result["video_path"]
        shot.last_frame_path = result.get("frame_path", "")
        if not shot.image_path:
            shot.image_path = result.get("frame_path", "")
        shot.status = "video_done"
        db.commit()

        await ws_manager.send_to_project(
            project_id,
            {
                "type": "shot_update",
                "shot_id": shot.id,
                "status": shot.status,
                "image_path": shot.image_path,
                "storyboard_path": shot.storyboard_path,
                "audio_path": shot.audio_path,
                "video_path": shot.video_path,
                "last_frame_path": shot.last_frame_path,
                "scene_group_id": shot.scene_group_id,
                "reference_weights": _json_dict(shot.reference_weights),
                "continuity_profile": _json_dict(shot.continuity_profile),
                "continuity_reference_path": shot.continuity_reference_path,
                "pose_reference_path": shot.pose_reference_path,
                "depth_reference_path": shot.depth_reference_path,
            },
        )
    except Exception as exc:
        db.rollback()
        if shot:
            shot.status = "failed"
            shot.visual_notes = f"单镜头视频生成失败: {exc}"
            db.commit()
            await ws_manager.send_to_project(
                shot.project_id,
                {"type": "error", "message": f"镜头 {shot.sequence} 视频生成失败: {exc}\n{traceback.format_exc()}"},
            )
    finally:
        db.close()


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
        "video_path": s.video_path,
        "audio_path": s.audio_path,
        "status": s.status,
        "storyboard_status": s.storyboard_status,
        "version": s.version,
        "confirmed": s.confirmed,
        "characters_in_scene": json.loads(s.characters_in_scene) if s.characters_in_scene else [],
        "scene_asset_id": s.scene_asset_id or "",
        "character_asset_ids": json.loads(s.character_asset_ids) if s.character_asset_ids else [],
        "scene_group_id": s.scene_group_id or "",
        "consistency_context": s.consistency_context or "",
        "reference_weights": _json_dict(s.reference_weights),
        "continuity_profile": _json_dict(s.continuity_profile),
        "continuity_reference_path": s.continuity_reference_path or "",
        "pose_reference_path": s.pose_reference_path or "",
        "depth_reference_path": s.depth_reference_path or "",
        "last_frame_path": s.last_frame_path or "",
    }


def _shot_dict(s: Shot) -> dict:
    data = _serialize_shot(s)
    data["shot_id"] = data.pop("id")
    data["camera_movement"] = s.camera_movement or "静止"
    data["seed"] = 42
    data["visual_notes"] = s.visual_notes or ""
    data["consistency_context"] = s.consistency_context or ""
    data["scene_group_id"] = s.scene_group_id or ""
    data["reference_weights"] = _json_dict(s.reference_weights)
    data["continuity_profile"] = _json_dict(s.continuity_profile)
    data["continuity_reference_path"] = s.continuity_reference_path or ""
    data["pose_reference_path"] = s.pose_reference_path or ""
    data["depth_reference_path"] = s.depth_reference_path or ""
    data["last_frame_path"] = s.last_frame_path or ""
    if not data["image_path"] and data.get("storyboard_path"):
        data["image_path"] = data["storyboard_path"]
    data["video_path"] = s.video_path or ""
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
            "default_outfit": c.default_outfit or "",
            "lora_profile": c.lora_profile or "",
            "ip_adapter_profile": c.ip_adapter_profile or "",
            "wardrobe_lock": c.wardrobe_lock or "",
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
            "reference_images": json.loads(item.reference_images) if item.reference_images else [],
            "scene_group_key": item.scene_group_key or item.id,
            "time_of_day": item.time_of_day or "",
            "baseline_image_path": item.baseline_image_path or "",
            "consistency_profile": json.loads(item.consistency_profile) if item.consistency_profile else {},
            "prop_lock": item.prop_lock or "",
        }
        for item in scenes
    }


def _json_dict(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _ensure_shot_unlocked(shot: Shot) -> None:
    if shot.confirmed:
        raise HTTPException(status_code=423, detail="已审批锁定的镜头禁止改动或重生成")


def _invalidate_storyboard_outputs(shot: Shot) -> None:
    shot.confirmed = False
    shot.status = "pending"
    shot.storyboard_status = "pending"
    shot.storyboard_path = ""
    shot.image_path = ""
    shot.scene_group_id = ""
    shot.reference_weights = "{}"
    shot.consistency_context = ""
    _invalidate_video_outputs(shot, reset_status=False)


def _can_reuse_existing_video(shot: Shot, force: bool = False) -> bool:
    return bool(shot.video_path and shot.status == "video_done" and not force)


def _invalidate_video_outputs(shot: Shot, reset_status: bool = True) -> None:
    shot.audio_path = ""
    shot.video_path = ""
    shot.last_frame_path = ""
    shot.continuity_reference_path = ""
    shot.pose_reference_path = ""
    shot.depth_reference_path = ""
    shot.continuity_profile = "{}"
    if not reset_status:
        return
    if shot.storyboard_path or shot.image_path:
        shot.status = "storyboard_approved" if shot.confirmed else "storyboard_done"
    else:
        shot.status = "pending"


def _invalidate_downstream_media(db: Session, shot: Shot, scene_keys: set[str] | None = None) -> None:
    keys = {key for key in (scene_keys or {_shot_scene_key(shot)}) if key}
    if not keys:
        return
    downstream = (
        db.query(Shot)
        .filter(Shot.project_id == shot.project_id, Shot.sequence > shot.sequence)
        .order_by(Shot.sequence)
        .all()
    )
    for item in downstream:
        if _shot_scene_key(item) in keys:
            _invalidate_video_outputs(item)


def _shot_scene_key(shot: Shot) -> str:
    return shot.scene_group_id or shot.scene_asset_id or ""


def _shot_scene_keys(shot: Shot, db: Session | None = None) -> set[str]:
    keys = {str(value) for value in (shot.scene_group_id, shot.scene_asset_id) if value}
    if db is not None and shot.scene_asset_id:
        try:
            scene = db.query(SceneAsset).filter(SceneAsset.id == shot.scene_asset_id).first()
            if scene and scene.scene_group_key:
                keys.add(scene.scene_group_key)
        except Exception:
            pass
    return keys


def _materialize_control_references(project_id: str, shot_data: dict) -> None:
    profile = shot_data.get("continuity_profile") or {}
    source_path = profile.get("previous_reference_path") or shot_data.get("continuity_reference_path", "")
    controls = reference_asset_service.materialize_continuity_controls(
        project_id=project_id,
        shot_id=shot_data.get("shot_id", "shot"),
        source_path=source_path,
        enabled=bool(profile.get("complex_motion")),
    )
    if not controls:
        return

    profile.update(controls)
    profile["openpose_lock"] = "enabled"
    profile["depth_lock"] = "enabled"
    shot_data["continuity_profile"] = profile
    shot_data["pose_reference_path"] = controls.get("pose_reference_path", "")
    shot_data["depth_reference_path"] = controls.get("depth_reference_path", "")

    weights = shot_data.get("reference_weights") or {}
    assets = [asset for asset in (shot_data.get("reference_assets") or []) if isinstance(asset, dict)]
    if controls.get("pose_reference_path"):
        assets.append(
            {
                "type": "openpose_source_frame",
                "path": controls["pose_reference_path"],
                "role": "complex_motion_body_joint_lock",
                "weight": weights.get("action", 0.30),
                "required": True,
            }
        )
    if controls.get("depth_reference_path"):
        assets.append(
            {
                "type": "depth_source_frame",
                "path": controls["depth_reference_path"],
                "role": "perspective_depth_lock",
                "weight": weights.get("environment", 0.45),
                "required": True,
            }
        )
    shot_data["reference_assets"] = assets


def _storyboard_notes(shot: Shot, scenes: dict[str, dict]) -> str:
    scene = scenes.get(shot.scene_asset_id or "")
    parts = [
        "finished approved storyboard keyframe",
        "full color final-look reference image",
        "lock character identity, costume, face, hairstyle and scene palette",
    ]
    if scene:
        parts.extend([scene.get("visual_prompt", ""), scene.get("description", "")])
        parts.extend([scene.get("prop_lock", ""), scene.get("baseline_image_path", "") and "preserve scene baseline reference"])
        if scene.get("reference_images"):
            parts.append("strictly preserve the approved scene asset reference")
    if shot.visual_notes:
        parts.append(shot.visual_notes)
    return ", ".join(part for part in parts if part)


def _storyboard_style_params(project: Project | None) -> dict:
    style = (project.style if project else "anime") or "anime"
    params = style_prompt_params(style)
    params["prompt_prefix"] = (
        f"{params.get('prompt_prefix', '')}, production-ready storyboard reference, "
        "not sketch, not rough line art, no monochrome, no grayscale"
    )
    return params


async def _ensure_scene_baselines(db: Session, project: Project | None, scenes: dict[str, dict]) -> None:
    if not project:
        return
    style = project.style or "anime"
    changed = False
    for scene_id, scene in scenes.items():
        if scene.get("baseline_image_path") or scene.get("reference_images"):
            continue
        model = db.query(SceneAsset).filter(SceneAsset.id == scene_id).first()
        if not model:
            continue
        try:
            ref_path = await image_service.generate_scene_baseline_reference(
                scene=scene,
                style=style,
                project_id=_asset_project_id(db, project.id),
                seed=int(model.seed or 1200),
            )
            model.baseline_image_path = ref_path
            model.reference_images = json.dumps([ref_path], ensure_ascii=False)
            changed = True
        except Exception:
            continue
    if changed:
        db.commit()


def _previous_reference_for_shot(db: Session, shot: Shot, prefer_last_frame: bool = False) -> str:
    current_keys = _shot_scene_keys(shot, db)
    if not current_keys:
        return ""
    previous_shots = (
        db.query(Shot)
        .filter(Shot.project_id == shot.project_id, Shot.sequence < shot.sequence)
        .order_by(Shot.sequence.desc())
        .all()
    )
    for previous in previous_shots:
        if not (current_keys & _shot_scene_keys(previous, db)):
            continue
        if prefer_last_frame and previous.last_frame_path:
            return previous.last_frame_path
        return previous.storyboard_path or previous.image_path or previous.last_frame_path or ""
    return ""


async def _progress(project_id: str, step: str, progress: int, message: str):
    await ws_manager.send_to_project(project_id, {"type": "progress", "step": step, "progress": progress, "message": message})
