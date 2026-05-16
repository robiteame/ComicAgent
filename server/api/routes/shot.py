import json
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from db import get_db
from models import Shot, Character

router = APIRouter(prefix="/api/shot", tags=["shot"])


class ShotUpdate(BaseModel):
    shot_type: str | None = None
    scene_description: str | None = None
    character_action: str | None = None
    dialogue: str | None = None
    camera_angle: str | None = None
    duration: float | None = None
    emotion: str | None = None
    transition: str | None = None


class RegenerateRequest(BaseModel):
    reason: str = ""
    new_emotion: str | None = None
    new_scene: str | None = None
    new_camera_angle: str | None = None


@router.get("/{project_id}/shots")
async def get_project_shots(project_id: str, db: Session = Depends(get_db)):
    shots = (
        db.query(Shot)
        .filter(Shot.project_id == project_id)
        .order_by(Shot.sequence)
        .all()
    )
    return [
        {
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
            "audio_path": s.audio_path,
            "status": s.status,
            "version": s.version,
            "characters_in_scene": json.loads(s.characters_in_scene)
            if s.characters_in_scene
            else [],
        }
        for s in shots
    ]


@router.put("/{shot_id}")
async def update_shot(shot_id: str, data: ShotUpdate, db: Session = Depends(get_db)):
    shot = db.query(Shot).filter(Shot.id == shot_id).first()
    if not shot:
        raise HTTPException(status_code=404, detail="镜头不存在")
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(shot, key, value)
    db.commit()
    return {"id": shot.id, "status": "updated"}


@router.post("/{shot_id}/regenerate")
async def regenerate_shot(
    shot_id: str, data: RegenerateRequest, db: Session = Depends(get_db)
):
    shot = db.query(Shot).filter(Shot.id == shot_id).first()
    if not shot:
        raise HTTPException(status_code=404, detail="镜头不存在")

    # 标记为待重新生成
    shot.status = "pending"
    shot.version = shot.version + 1 if shot.version else 2
    if data.new_emotion:
        shot.emotion = data.new_emotion
    if data.new_scene:
        shot.scene_description = data.new_scene
    if data.new_camera_angle:
        shot.camera_angle = data.new_camera_angle
    db.commit()

    # TODO: 触发异步重生成任务
    return {"id": shot.id, "status": "regenerating", "version": shot.version}


@router.post("/batch-regenerate")
async def batch_regenerate(
    shot_ids: list[str],
    reason: str = "",
    db: Session = Depends(get_db),
):
    shots = db.query(Shot).filter(Shot.id.in_(shot_ids)).all()
    for shot in shots:
        shot.status = "pending"
        shot.version = shot.version + 1 if shot.version else 2
    db.commit()
    return {"updated": len(shots)}
