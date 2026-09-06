import asyncio
import hashlib
import json
import traceback
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from api.websocket import ws_manager
from config import settings
from db import SessionLocal, get_db
from models import Character, Project, SceneAsset, Shot
from services.consistency_service import ConsistencyService
from services.image_service import ImageService
from services.reference_asset_service import ReferenceAssetService
from services.skill_config_service import (
    agent_style_id,
    apply_agent_config_to_shot,
    clean_tts_text,
    resolve_skill_config,
    should_materialize_openpose,
)
from services.style_templates import style_prompt_params
from services.tts_service import TTSService
from services.video_service import SeedanceVideoService
from services.security import existing_file, validate_identifier
from services.task_registry import cancel as cancel_task, cancel_scopes, claim as claim_task, finish as finish_task, start as start_task

router = APIRouter(prefix="/api/shot", tags=["shot"])

image_service = ImageService()
tts_service = TTSService()
seedance_service = SeedanceVideoService()
consistency_service = ConsistencyService()
reference_asset_service = ReferenceAssetService()
_regeneration_tasks: set[asyncio.Task] = set()
_shot_video_tasks: set[asyncio.Task] = set()
_project_generation_locks: dict[str, asyncio.Lock] = {}
_shot_generation_locks: dict[str, asyncio.Lock] = {}


class ShotUpdate(BaseModel):
    shot_type: str | None = None
    scene_description: str | None = None
    character_action: str | None = None
    dialogue: str | None = None
    camera_angle: str | None = None
    camera_movement: str | None = None
    duration: float | None = None
    emotion: str | None = None
    transition: str | None = None
    visual_notes: str | None = None
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
    shot_ids: list[str] = Field(default_factory=list)


class StoryboardApprovalRequest(BaseModel):
    approved: bool = True


class ShotVideoGenerateRequest(BaseModel):
    force: bool = False


@router.get("/{shot_id}/generation-prompt")
async def get_shot_generation_prompt(shot_id: str, db: Session = Depends(get_db)):
    shot = db.query(Shot).filter(Shot.id == shot_id).first()
    if not shot:
        raise HTTPException(status_code=404, detail="Shot not found")

    project = db.query(Project).filter(Project.id == shot.project_id).first()
    skill_config = resolve_skill_config(shot.project_id, db)
    characters = _characters(db, shot.project_id)
    scenes = _scenes(db, shot.project_id)
    previous_reference = _previous_reference_for_shot(db, shot)
    shot_data = _shot_dict(shot)
    shot_data["storyboard_prompt"] = _storyboard_notes(shot, scenes)
    shot_data.update(
        consistency_service.build_generation_context(
            shot_data,
            characters,
            scenes,
            previous_reference_path=previous_reference,
            for_video=False,
        )
    )
    apply_agent_config_to_shot(shot_data, skill_config)
    prompt, negative_prompt = image_service.build_shot_prompt(
        shot=shot_data,
        characters=characters,
        style_params=_storyboard_style_params(project, skill_config),
    )
    return {
        "shot_id": shot.id,
        "prompt": prompt,
        "negative_prompt": negative_prompt,
        "scene_reference_images": shot_data.get("scene_reference_images", []),
        "character_reference_images": shot_data.get("character_reference_images", []),
    }


@router.get("/{project_id}/shots")
async def get_project_shots(project_id: str, db: Session = Depends(get_db)):
    _validate_id_or_400(project_id, "项目 ID")
    if not db.query(Project).filter(Project.id == project_id).first():
        raise HTTPException(status_code=404, detail="Project not found")
    shots = db.query(Shot).filter(Shot.project_id == project_id).order_by(Shot.sequence).all()
    return [_serialize_shot(s) for s in shots]


@router.put("/{shot_id}")
async def update_shot(shot_id: str, data: ShotUpdate, db: Session = Depends(get_db)):
    shot = db.query(Shot).filter(Shot.id == shot_id).first()
    if not shot:
        raise HTTPException(status_code=404, detail="Shot not found")

    _ensure_shot_unlocked(shot)
    project_id = shot.project_id
    result_id = shot.id
    previous_scene_key = _shot_scene_key(shot)
    changed = data.model_dump(exclude_unset=True)
    if "scene_asset_id" in changed or "character_asset_ids" in changed:
        scene_value = changed.get("scene_asset_id", shot.scene_asset_id) or ""
        character_value = changed.get("character_asset_ids", _json_list(shot.character_asset_ids))
        scene_value, character_value = _validate_asset_bindings(db, shot, scene_value, character_value)
        if "scene_asset_id" in changed:
            changed["scene_asset_id"] = scene_value
        if "character_asset_ids" in changed:
            changed["character_asset_ids"] = character_value
    for key, value in changed.items():
        if key == "character_asset_ids":
            setattr(shot, key, json.dumps(value or [], ensure_ascii=False))
        else:
            setattr(shot, key, value)

    if changed:
        _invalidate_storyboard_outputs(shot)
        _invalidate_downstream_media(db, shot, {previous_scene_key, _shot_scene_key(shot)})
        shot.version = (shot.version or 1) + 1
        _mark_project_output_stale(db, project_id)

    db.commit()
    if changed:
        # The project scope also owns automatic pipelines and renders, while the
        # shot scope owns manual image/video work. Wait for both to unwind so
        # no stale worker can publish after this response.
        await cancel_scopes(
            {f"shot:{shot_id}", f"project:{project_id}"},
            "shot was edited",
        )
    return {"id": result_id, "status": "updated", "needs_render": bool(changed)}


@router.post("/{shot_id}/regenerate")
async def regenerate_shot(shot_id: str, data: RegenerateRequest, db: Session = Depends(get_db)):
    shot = db.query(Shot).filter(Shot.id == shot_id).first()
    if not shot:
        raise HTTPException(status_code=404, detail="Shot not found")

    _ensure_shot_unlocked(shot)
    task_key = _shot_task_key(shot_id, "storyboard")
    expected_version = (shot.version or 1) + 1
    if not claim_task(task_key, f"shot:{shot_id}", version=expected_version):
        return {"id": shot.id, "status": "regenerating", "version": shot.version, "deduplicated": True}

    try:
        previous_scene_key = _shot_scene_key(shot)
        _invalidate_storyboard_outputs(shot)
        _invalidate_downstream_media(db, shot, {previous_scene_key, _shot_scene_key(shot)})
        shot.status = "pending"
        shot.storyboard_status = "queued"
        shot.version = (shot.version or 1) + 1
        expected_version = shot.version
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
        _mark_project_output_stale(db, shot.project_id)
        db.commit()

        task = start_task(task_key, _regenerate_single_shot(shot_id, data.reason or prompt or "", expected_version))
    except BaseException as exc:
        db.rollback()
        finish_task(task_key, "failed", f"storyboard scheduling failed: {exc}")
        raise
    _regeneration_tasks.add(task)
    task.add_done_callback(_regeneration_tasks.discard)
    return {"id": shot.id, "status": "regenerating", "version": shot.version}


@router.post("/batch-regenerate")
async def batch_regenerate(shot_ids: list[str], reason: str = "", db: Session = Depends(get_db)):
    shots = db.query(Shot).filter(Shot.id.in_(shot_ids)).all()
    missing = sorted(set(shot_ids) - {shot.id for shot in shots})
    if missing:
        raise HTTPException(status_code=404, detail=f"镜头不存在: {', '.join(missing)}")
    locked = [shot.id for shot in shots if shot.confirmed]
    if locked:
        raise HTTPException(status_code=423, detail=f"已审核镜头禁止重新生成: {', '.join(locked)}")
    claimed_keys: list[str] = []
    for shot in shots:
        task_key = _shot_task_key(shot.id, "storyboard")
        if not claim_task(task_key, f"shot:{shot.id}", version=(shot.version or 1) + 1):
            for claimed_key in claimed_keys:
                finish_task(claimed_key, "cancelled", "batch claim rolled back")
            raise HTTPException(status_code=409, detail=f"镜头已有生成任务: {shot.id}")
        claimed_keys.append(task_key)
    expected_versions: dict[str, int] = {}
    try:
        for shot in shots:
            previous_scene_key = _shot_scene_key(shot)
            _invalidate_storyboard_outputs(shot)
            _invalidate_downstream_media(db, shot, {previous_scene_key, _shot_scene_key(shot)})
            shot.status = "pending"
            shot.storyboard_status = "queued"
            shot.version = (shot.version or 1) + 1
            expected_versions[shot.id] = shot.version
        for project_id in {shot.project_id for shot in shots}:
            _mark_project_output_stale(db, project_id)
        db.commit()
    except BaseException as exc:
        db.rollback()
        for task_key in claimed_keys:
            finish_task(task_key, "failed", f"batch preparation failed: {exc}")
        raise

    started_keys: set[str] = set()
    try:
        for shot in shots:
            task_key = _shot_task_key(shot.id, "storyboard")
            task = start_task(task_key, _regenerate_single_shot(shot.id, reason, expected_versions[shot.id]))
            started_keys.add(task_key)
            _regeneration_tasks.add(task)
            task.add_done_callback(_regeneration_tasks.discard)
    except BaseException:
        for task_key in started_keys:
            cancel_task(task_key)
        for task_key in set(claimed_keys) - started_keys:
            finish_task(task_key, "failed", "batch scheduling was aborted")
        raise
    return {"updated": len(shots)}


@router.post("/{project_id}/generate-storyboard")
async def generate_storyboard_images(project_id: str, data: StoryboardGenerateRequest, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    query = db.query(Shot).filter(Shot.project_id == project_id)
    if data.shot_ids:
        query = query.filter(Shot.id.in_(data.shot_ids))
    shots = query.order_by(Shot.sequence).all()
    locked = [shot.id for shot in shots if shot.confirmed]
    if locked:
        if data.shot_ids:
            raise HTTPException(status_code=423, detail=f"已审核镜头禁止重新生成: {', '.join(locked)}")
        shots = [shot for shot in shots if not shot.confirmed]
    if not shots:
        raise HTTPException(status_code=404, detail="No shots available for storyboard generation")

    task_key = _project_task_key(project_id, "storyboard")
    if not claim_task(task_key, f"project:{project_id}"):
        return {"status": "storyboard_generating", "project_id": project_id, "deduplicated": True}

    try:
        expected_versions: dict[str, int] = {}
        for shot in shots:
            previous_scene_key = _shot_scene_key(shot)
            _invalidate_storyboard_outputs(shot)
            _invalidate_downstream_media(db, shot, {previous_scene_key, _shot_scene_key(shot)})
            shot.storyboard_status = "queued"
            shot.status = "pending"
            shot.version = (shot.version or 1) + 1
            expected_versions[shot.id] = shot.version
        project.status = "storyboard_generating"
        db.commit()

        task = start_task(task_key, _run_storyboard_generation(project_id, [shot.id for shot in shots], expected_versions))
    except BaseException as exc:
        db.rollback()
        finish_task(task_key, "failed", f"storyboard scheduling failed: {exc}")
        raise
    _regeneration_tasks.add(task)
    task.add_done_callback(_regeneration_tasks.discard)
    return {"status": "storyboard_started", "project_id": project_id, "shots": len(shots)}


@router.post("/{project_id}/confirm-storyboard")
async def confirm_storyboard(project_id: str, db: Session = Depends(get_db)):
    shots = db.query(Shot).filter(Shot.project_id == project_id).order_by(Shot.sequence).all()
    if not shots:
        raise HTTPException(status_code=404, detail="No storyboard shots available for confirmation")
    unfinished = [shot.id for shot in shots if not shot.storyboard_path and not shot.image_path]
    if unfinished:
        raise HTTPException(status_code=400, detail="仍有镜头未生成定稿故事板")
    unapproved = [shot.id for shot in shots if not shot.confirmed]
    if unapproved:
        raise HTTPException(status_code=400, detail="仍有镜头未通过人工审核")

    project = db.query(Project).filter(Project.id == project_id).first()
    if project:
        project.status = "storyboard_approved"
    db.commit()

    return {"status": "storyboard_approved", "project_id": project_id, "confirmed_shots": len(shots)}


@router.post("/{shot_id}/approve-storyboard")
async def approve_storyboard(shot_id: str, data: StoryboardApprovalRequest, db: Session = Depends(get_db)):
    shot = db.query(Shot).filter(Shot.id == shot_id).first()
    if not shot:
        raise HTTPException(status_code=404, detail="Shot not found")
    if data.approved and not (shot.storyboard_path or shot.image_path):
        raise HTTPException(status_code=400, detail="该镜头故事板尚未生成")
    project_id = shot.project_id
    result_id = shot.id
    was_approved = bool(shot.confirmed)
    shot.confirmed = bool(data.approved)
    shot.status = "storyboard_approved" if data.approved else "needs_review"
    revoked = was_approved and not data.approved
    if revoked:
        shot.version = (shot.version or 1) + 1
        _invalidate_video_outputs(shot)
        _invalidate_downstream_media(db, shot)
        shot.status = "needs_review"
        _mark_project_output_stale(db, project_id, status="storyboard_ready")
    db.commit()
    if revoked:
        await cancel_scopes(
            {f"shot:{shot_id}", f"project:{project_id}"},
            "storyboard approval was revoked",
        )
    return {
        "id": result_id,
        "approved": bool(data.approved),
        "status": "storyboard_approved" if data.approved else "needs_review",
    }


@router.post("/{shot_id}/generate-video")
async def generate_shot_video(shot_id: str, data: ShotVideoGenerateRequest, db: Session = Depends(get_db)):
    shot = db.query(Shot).filter(Shot.id == shot_id).first()
    if not shot:
        raise HTTPException(status_code=404, detail="Shot not found")
    task_key = _shot_task_key(shot_id, "video")
    if not shot.confirmed:
        raise HTTPException(status_code=400, detail="请先审核通过该镜头故事板")
    if not (shot.storyboard_path or shot.image_path):
        raise HTTPException(status_code=400, detail="该镜头尚未生成定稿故事板")
    if _can_reuse_existing_video(shot, data.force):
        return {"id": shot.id, "status": shot.status, "video_path": shot.video_path, "audio_path": shot.audio_path}

    expected_version = shot.version or 1
    if not claim_task(task_key, f"shot:{shot_id}", version=expected_version):
        return {"id": shot.id, "status": "video_generating", "deduplicated": True}
    try:
        shot.status = "video_generating"
        _mark_project_output_stale(db, shot.project_id, status="storyboard_approved")
        db.commit()
        task = start_task(task_key, _run_single_shot_video(shot_id, data.force, expected_version))
    except BaseException as exc:
        db.rollback()
        finish_task(task_key, "failed", f"video scheduling failed: {exc}")
        raise
    _shot_video_tasks.add(task)
    task.add_done_callback(_shot_video_tasks.discard)
    return {"id": shot.id, "status": "video_generating"}


async def _run_storyboard_generation(
    project_id: str,
    shot_ids: list[str],
    expected_versions: dict[str, int] | None = None,
) -> None:
    """Run one project storyboard job at a time."""

    lock = _project_generation_locks.setdefault(project_id, asyncio.Lock())
    if lock.locked():
        raise RuntimeError("项目故事板生成任务已在运行")
    if expected_versions is None:
        db = SessionLocal()
        try:
            expected_versions = {
                shot_id: version or 1
                for shot_id, version in db.query(Shot.id, Shot.version)
                .filter(Shot.project_id == project_id, Shot.id.in_(shot_ids))
                .all()
            }
        finally:
            db.close()
    async with lock:
        await _run_storyboard_generation_impl(project_id, shot_ids, expected_versions)


async def _run_storyboard_generation_impl(
    project_id: str,
    shot_ids: list[str],
    expected_versions: dict[str, int],
) -> None:
    try:
        db = SessionLocal()
        try:
            project = db.query(Project).filter(Project.id == project_id).first()
            skill_config = resolve_skill_config(project_id, db)
            scenes = _scenes(db, project_id)
        finally:
            db.close()
        await _ensure_scene_baselines(project_id, project, scenes, skill_config)

        db = SessionLocal()
        try:
            project = db.query(Project).filter(Project.id == project_id).first()
            characters = _characters(db, project_id)
            scenes = _scenes(db, project_id)
        finally:
            db.close()

        for index, shot_id in enumerate(shot_ids):
            db = SessionLocal()
            try:
                shot = db.query(Shot).filter(Shot.id == shot_id, Shot.project_id == project_id).first()
                if not shot:
                    continue
                expected_version = expected_versions.get(shot.id)
                if expected_version is not None and (shot.version or 1) != expected_version:
                    continue
                shot_data = _shot_dict(shot)
                shot_data["visual_notes"] = _storyboard_notes(shot, scenes)
                if project:
                    shot_data["output_format"] = project.output_format or "9:16"
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
                apply_agent_config_to_shot(shot_data, skill_config)
                style_params = _storyboard_style_params(project, skill_config)
                seed = 42 + (shot.version or 1) * 100
            finally:
                db.close()

            await _progress(project_id, "generate_storyboard_images", 48 + min(index * 4, 35), "正在生成定稿故事板参考图")
            _materialize_control_references(project_id, shot_data, skill_config)
            image_path = await image_service.generate_shot_image(
                shot=shot_data,
                characters=characters,
                style_params=style_params,
                project_id=project_id,
                seed=seed,
            )

            db = SessionLocal()
            try:
                shot = db.query(Shot).filter(Shot.id == shot_id, Shot.project_id == project_id).first()
                if not shot or (expected_version is not None and (shot.version or 1) != expected_version):
                    continue
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
                update = _shot_update_payload(shot)
            finally:
                db.close()
            await ws_manager.send_to_project(
                project_id,
                update,
            )

        db = SessionLocal()
        try:
            if expected_versions:
                stale_or_missing = [
                    item.id
                    for item in db.query(Shot)
                    .filter(Shot.project_id == project_id, Shot.id.in_(shot_ids))
                    .all()
                    if (item.version or 1) != expected_versions.get(item.id)
                    or item.storyboard_status != "done"
                ]
                requested_ids = set(expected_versions)
                found_ids = {item.id for item in db.query(Shot.id).filter(Shot.project_id == project_id, Shot.id.in_(shot_ids)).all()}
                stale_or_missing.extend(sorted(requested_ids - found_ids))
                if stale_or_missing:
                    project = db.query(Project).filter(Project.id == project_id).first()
                    if project and project.status == "storyboard_generating":
                        project.status = "assets_ready"
                        db.commit()
                    raise asyncio.CancelledError(f"故事板任务版本已变化: {', '.join(stale_or_missing)}")

            project = db.query(Project).filter(Project.id == project_id).first()
            if project:
                project.status = "storyboard_ready"
                db.commit()
        finally:
            db.close()
        await _progress(project_id, "wait_storyboard_approval", 72, "定稿故事板参考图已生成，等待人工审核")
        await ws_manager.send_to_project(project_id, {"type": "storyboard_ready", "project_id": project_id})
    except Exception as exc:
        db = SessionLocal()
        try:
            project = db.query(Project).filter(Project.id == project_id).first()
            if project:
                project.status = "error"
            queued = db.query(Shot).filter(Shot.project_id == project_id, Shot.storyboard_status == "queued").all()
            for shot in queued:
                shot.storyboard_status = "failed"
                if shot.status == "pending":
                    shot.status = "failed"
            db.commit()
        finally:
            db.close()
        await ws_manager.send_to_project(project_id, {"type": "error", "message": f"故事板生成失败: {exc}\n{traceback.format_exc()}"})
        raise


async def _regenerate_single_shot(shot_id: str, reason: str = "", expected_version: int | None = None):
    lock = _shot_generation_locks.setdefault(shot_id, asyncio.Lock())
    if lock.locked():
        raise RuntimeError("镜头故事板生成任务已在运行")
    await lock.acquire()
    project_id = ""
    try:
        db = SessionLocal()
        try:
            shot = db.query(Shot).filter(Shot.id == shot_id).first()
            if not shot or (expected_version is not None and (shot.version or 1) != expected_version):
                raise asyncio.CancelledError("镜头版本已变化")
            project_id = shot.project_id
            project = db.query(Project).filter(Project.id == project_id).first()
            skill_config = resolve_skill_config(project_id, db)
            scenes = _scenes(db, project_id)
        finally:
            db.close()

        await _ensure_scene_baselines(project_id, project, scenes, skill_config)

        db = SessionLocal()
        try:
            shot = db.query(Shot).filter(Shot.id == shot_id).first()
            if not shot or (expected_version is not None and (shot.version or 1) != expected_version):
                raise asyncio.CancelledError("镜头版本已变化")
            project = db.query(Project).filter(Project.id == project_id).first()
            characters = _characters(db, project_id)
            scenes = _scenes(db, project_id)
            shot_data = _shot_dict(shot)
            shot_data["visual_notes"] = reason or _storyboard_notes(shot, scenes)
            if project:
                shot_data["output_format"] = project.output_format or "9:16"
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
            apply_agent_config_to_shot(shot_data, skill_config)
            style_params = _storyboard_style_params(project, skill_config)
            seed = 42 + (shot.version or 1) * 100
        finally:
            db.close()

        _materialize_control_references(project_id, shot_data, skill_config)
        image_path = await image_service.generate_shot_image(
            shot=shot_data,
            characters=characters,
            style_params=style_params,
            project_id=project_id,
            seed=seed,
        )

        db = SessionLocal()
        try:
            shot = db.query(Shot).filter(Shot.id == shot_id).first()
            if not shot or (expected_version is not None and (shot.version or 1) != expected_version):
                raise asyncio.CancelledError("镜头版本已变化")
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
            update = _shot_update_payload(shot)
        finally:
            db.close()
        await ws_manager.send_to_project(project_id, update)
    except Exception as exc:
        db = SessionLocal()
        try:
            shot = db.query(Shot).filter(Shot.id == shot_id).first()
            if shot and (expected_version is None or (shot.version or 1) == expected_version):
                shot.status = "failed"
                shot.storyboard_status = "failed"
                shot.visual_notes = f"重新生成故事板失败: {exc}"
                project_id = shot.project_id
                error_message = shot.visual_notes
                db.commit()
            else:
                error_message = ""
        finally:
            db.close()
        if error_message:
            await ws_manager.send_to_project(project_id, {"type": "error", "message": error_message})
        raise
    finally:
        lock.release()


async def _run_single_shot_video(
    shot_id: str,
    force: bool = False,
    expected_version: int | None = None,
) -> None:
    lock = _shot_generation_locks.setdefault(shot_id, asyncio.Lock())
    if lock.locked():
        raise RuntimeError("镜头视频生成任务已在运行")
    await lock.acquire()
    project_id = ""
    shot_sequence = 0
    try:
        db = SessionLocal()
        try:
            shot = db.query(Shot).filter(Shot.id == shot_id).first()
            if not shot:
                return
            if expected_version is None:
                expected_version = shot.version or 1
            elif (shot.version or 1) != expected_version:
                raise asyncio.CancelledError("镜头版本已变化")
            if _can_reuse_existing_video(shot, force):
                return
            project_id = shot.project_id
            project = db.query(Project).filter(Project.id == project_id).first()
            skill_config = resolve_skill_config(project_id, db)
            scenes = _scenes(db, project_id)
        finally:
            db.close()

        await _ensure_scene_baselines(project_id, project, scenes, skill_config)

        db = SessionLocal()
        try:
            shot = db.query(Shot).filter(Shot.id == shot_id).first()
            if not shot or (expected_version is not None and (shot.version or 1) != expected_version):
                raise asyncio.CancelledError("镜头版本已变化")
            project = db.query(Project).filter(Project.id == project_id).first()
            characters = _characters(db, project_id)
            scenes = _scenes(db, project_id)
            shot_data = _shot_dict(shot)
            shot_data["storyboard_prompt"] = _storyboard_notes(shot, scenes)
            if project:
                shot_data["output_format"] = project.output_format or "9:16"
                shot_data["resolution"] = project.resolution or "720p"
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
            apply_agent_config_to_shot(shot_data, skill_config)
            shot_sequence = shot.sequence
            dialogue = shot.dialogue
            emotion = shot.emotion or "neutral"
            speakers = _json_list(shot.characters_in_scene)
            speaker = speakers[0] if speakers else ""
        finally:
            db.close()
        _materialize_control_references(project_id, shot_data, skill_config)

        await _progress(project_id, "generate_voice", 82, f"正在生成镜头 {shot_sequence} 的配音")
        media_id = _versioned_media_id(shot_id, expected_version)
        audio_path = shot_data.get("audio_path", "")
        if dialogue:
            voice_id = next((item.get("voice_id", "") for item in characters if item.get("name") == speaker), "")
            audio_path = await tts_service.generate_dialogue(
                text=clean_tts_text(dialogue, skill_config),
                voice_id=voice_id,
                emotion=emotion,
                project_id=project_id,
                shot_id=media_id,
            )
            shot_data["audio_path"] = audio_path

        await _progress(project_id, "generate_seedance_video", 90, f"正在生成镜头 {shot_sequence} 的 Seedance 视频")
        video_shot_data = {**shot_data, "shot_id": media_id}
        result = await seedance_service.generate_shot_video(video_shot_data, characters, scenes, project_id)
        continuity_profile = shot_data.get("continuity_profile", {}) or {}
        if result.get("reference_payload_mode"):
            continuity_profile["seedance_reference_payload_mode"] = result["reference_payload_mode"]
            shot_data["continuity_profile"] = continuity_profile

        db = SessionLocal()
        try:
            shot = db.query(Shot).filter(Shot.id == shot_id).first()
            if not shot or (expected_version is not None and (shot.version or 1) != expected_version):
                raise asyncio.CancelledError("镜头版本已变化")
            shot.scene_group_id = shot_data.get("scene_group_id", shot.scene_group_id)
            shot.consistency_context = shot_data.get("consistency_context", shot.consistency_context)
            shot.reference_weights = json.dumps(shot_data.get("reference_weights", {}), ensure_ascii=False)
            shot.continuity_profile = json.dumps(shot_data.get("continuity_profile", {}), ensure_ascii=False)
            shot.continuity_reference_path = previous_reference
            shot.pose_reference_path = shot_data.get("pose_reference_path", "")
            shot.depth_reference_path = shot_data.get("depth_reference_path", "")
            shot.audio_path = audio_path
            shot.video_path = result["video_path"]
            shot.last_frame_path = result.get("frame_path", "")
            if not shot.image_path:
                shot.image_path = result.get("frame_path", "")
            shot.status = "video_done"
            db.commit()
            update = _shot_update_payload(shot)
        finally:
            db.close()

        await ws_manager.send_to_project(project_id, update)
    except Exception as exc:
        db = SessionLocal()
        try:
            shot = db.query(Shot).filter(Shot.id == shot_id).first()
            if shot and (expected_version is None or (shot.version or 1) == expected_version):
                shot.status = "failed"
                shot.visual_notes = f"单镜头视频生成失败: {exc}"
                project_id = shot.project_id
                shot_sequence = shot.sequence
                db.commit()
                should_notify = True
            else:
                should_notify = False
        finally:
            db.close()
        if should_notify:
            await ws_manager.send_to_project(
                project_id,
                {"type": "error", "message": f"镜头 {shot_sequence} 视频生成失败: {exc}\n{traceback.format_exc()}"},
            )
        raise
    finally:
        lock.release()


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
        "camera_movement": s.camera_movement or "静止",
        "duration": s.duration,
        "emotion": s.emotion,
        "transition": s.transition,
        "visual_notes": s.visual_notes or "",
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


def _shot_update_payload(shot: Shot) -> dict:
    return {
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


def _json_list(raw: str | None) -> list:
    try:
        value = json.loads(raw or "[]")
        return value if isinstance(value, list) else []
    except (TypeError, ValueError):
        return []


def _validate_asset_bindings(db: Session, shot: Shot, scene_asset_id, character_asset_ids) -> tuple[str, list[str]]:
    """Validate all asset references against the shot's owning project."""

    asset_project_id = _asset_project_id(db, shot.project_id)
    scene_id = str(scene_asset_id or "").strip()
    if scene_id:
        scene = db.query(SceneAsset).filter(SceneAsset.id == scene_id, SceneAsset.project_id == asset_project_id).first()
        if not scene:
            raise HTTPException(status_code=400, detail="场景资产不属于该项目")
    ids = list(dict.fromkeys(str(item).strip() for item in (character_asset_ids or []) if str(item).strip()))
    if ids:
        found = {
            item.id
            for item in db.query(Character).filter(Character.id.in_(ids), Character.project_id == asset_project_id).all()
        }
        if found != set(ids):
            raise HTTPException(status_code=400, detail="角色资产不属于该项目")
    return scene_id, ids


def _validate_id_or_400(value: str, field: str) -> str:
    try:
        return validate_identifier(value, field)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _shot_task_key(shot_id: str, kind: str) -> str:
    return f"shot:{shot_id}:{kind}"


def _project_task_key(project_id: str, kind: str) -> str:
    return f"project:{project_id}:{kind}"


def _versioned_media_id(shot_id: str, version: int | None) -> str:
    suffix = f"_v{version or 1}"
    candidate = f"{shot_id}{suffix}"
    if len(candidate) <= 128:
        return candidate
    digest = hashlib.sha256(shot_id.encode("utf-8")).hexdigest()[:20]
    return f"{shot_id[:96]}_{digest}{suffix}"[:128]


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
            "seed": item.seed or 1200,
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
        raise HTTPException(status_code=423, detail="已审核锁定的镜头禁止修改或重新生成")


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
    if force or shot.status != "video_done" or not shot.video_path:
        return False
    return existing_file(
        shot.video_path,
        minimum_size=4096,
        allowed_roots=(settings.OUTPUT_DIR, settings.ASSETS_DIR, settings.DATA_DIR),
    ) is not None


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
            # Fence an in-flight video worker for this downstream shot. The
            # project-scope cancellation performed by callers then waits for it
            # to unwind before returning.
            item.version = (getattr(item, "version", 1) or 1) + 1


def _mark_project_output_stale(db: Session, project_id: str, status: str = "assets_ready") -> None:
    project = db.query(Project).filter(Project.id == project_id).first()
    if project:
        project.status = status


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


def _materialize_control_references(project_id: str, shot_data: dict, skill_config: dict | None = None) -> None:
    profile = shot_data.get("continuity_profile") or {}
    source_path = profile.get("previous_reference_path") or shot_data.get("continuity_reference_path", "")
    controls = reference_asset_service.materialize_continuity_controls(
        project_id=project_id,
        shot_id=shot_data.get("shot_id", "shot"),
        source_path=source_path,
        enabled=bool(profile.get("complex_motion")) and should_materialize_openpose(skill_config),
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


def _storyboard_style_params(project: Project | None, skill_config: dict | None = None) -> dict:
    style = agent_style_id(skill_config, "storyboard_agent", (project.style if project else "anime") or "anime")
    params = style_prompt_params(style)
    params["prompt_prefix"] = (
        f"{params.get('prompt_prefix', '')}, production-ready storyboard reference, "
        "not sketch, not rough line art, no monochrome, no grayscale"
    )
    return params


async def _ensure_scene_baselines(
    project_id: str,
    project: Project | None,
    scenes: dict[str, dict],
    skill_config: dict | None = None,
) -> None:
    if not project:
        return
    style = agent_style_id(skill_config, "storyboard_agent", project.style or "anime")
    asset_project_id = project.parent_project_id or project_id
    skill_append = ""
    if skill_config:
        from services.skill_config_service import agent_prompt_append

        skill_append = agent_prompt_append(skill_config, "storyboard_agent")
    for scene_id, scene in scenes.items():
        if scene.get("baseline_image_path") or scene.get("reference_images"):
            continue
        try:
            scene_payload = dict(scene)
            if skill_append:
                scene_payload["visual_prompt"] = ", ".join(part for part in [scene.get("visual_prompt", ""), skill_append] if part)
            ref_path = await image_service.generate_scene_baseline_reference(
                scene=scene_payload,
                style=style,
                project_id=asset_project_id,
                seed=int(scene.get("seed") or 1200),
            )
            db = SessionLocal()
            try:
                model = (
                    db.query(SceneAsset)
                    .filter(SceneAsset.id == scene_id, SceneAsset.project_id == asset_project_id)
                    .first()
                )
                if model and not model.baseline_image_path:
                    model.baseline_image_path = ref_path
                    model.reference_images = json.dumps([ref_path], ensure_ascii=False)
                    db.commit()
            finally:
                db.close()
        except Exception:
            continue


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
