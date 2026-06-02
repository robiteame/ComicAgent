import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db import get_db
from models import Character, Project, SceneAsset, Shot
from services.image_service import ImageService

router = APIRouter(prefix="/api/asset", tags=["asset"])
image_service = ImageService()


class ShotAssetUpdate(BaseModel):
    scene_asset_id: str = ""
    character_asset_ids: list[str] = []


class CharacterAssetUpdate(BaseModel):
    name: str | None = None
    appearance: dict | str | None = None
    personality: str | None = None
    visual_prompt: str | None = None
    negative_prompt: str | None = None
    voice_id: str | None = None
    emotion_variants: dict | str | None = None
    key_features: list[str] | str | None = None
    default_outfit: str | None = None
    lora_profile: str | None = None
    ip_adapter_profile: str | None = None
    wardrobe_lock: str | None = None
    seed: str | None = None
    regenerate: bool = False


class SceneAssetUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    visual_prompt: str | None = None
    negative_prompt: str | None = None
    key_features: list[str] | str | None = None
    scene_group_key: str | None = None
    time_of_day: str | None = None
    consistency_profile: dict | str | None = None
    prop_lock: str | None = None
    seed: int | None = None
    regenerate: bool = False


@router.get("/{project_id}/board")
async def get_asset_board(project_id: str, db: Session = Depends(get_db)):
    asset_project_id = _asset_project_id(db, project_id)
    return {
        "project_id": project_id,
        "asset_project_id": asset_project_id,
        "characters": [_serialize_character(item) for item in db.query(Character).filter(Character.project_id == asset_project_id).all()],
        "scenes": [_serialize_scene(item) for item in db.query(SceneAsset).filter(SceneAsset.project_id == asset_project_id).all()],
    }


@router.put("/shot/{shot_id}")
async def update_shot_assets(shot_id: str, data: ShotAssetUpdate, db: Session = Depends(get_db)):
    shot = db.query(Shot).filter(Shot.id == shot_id).first()
    if not shot:
        raise HTTPException(status_code=404, detail="镜头不存在")
    shot.scene_asset_id = data.scene_asset_id
    shot.character_asset_ids = json.dumps(data.character_asset_ids, ensure_ascii=False)
    shot.storyboard_status = "pending"
    shot.storyboard_path = ""
    shot.image_path = ""
    shot.status = "pending"
    db.commit()
    return {"id": shot.id, "status": "updated"}


@router.put("/character/{character_id}")
async def update_character_asset(character_id: str, data: CharacterAssetUpdate, db: Session = Depends(get_db)):
    item = db.query(Character).filter(Character.id == character_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="角色资产不存在")

    changed = data.model_dump(exclude_unset=True)
    regenerate = bool(changed.pop("regenerate", False))
    _assign_json_field(item, changed, "appearance")
    _assign_json_field(item, changed, "emotion_variants")
    _assign_json_field(item, changed, "key_features")
    for key, value in changed.items():
        setattr(item, key, value)

    if regenerate:
        ref_path = await image_service.generate_character_reference(
            character=_serialize_character(item),
            style=_project_style(db, item.project_id),
            project_id=item.project_id,
            seed=_int_seed(item.seed, 42),
        )
        item.reference_images = json.dumps([ref_path], ensure_ascii=False)

    item.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(item)
    return _serialize_character(item)


@router.put("/scene/{scene_id}")
async def update_scene_asset(scene_id: str, data: SceneAssetUpdate, db: Session = Depends(get_db)):
    item = db.query(SceneAsset).filter(SceneAsset.id == scene_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="场景资产不存在")

    changed = data.model_dump(exclude_unset=True)
    regenerate = bool(changed.pop("regenerate", False))
    _assign_json_field(item, changed, "key_features")
    _assign_json_field(item, changed, "consistency_profile")
    for key, value in changed.items():
        setattr(item, key, value)

    if regenerate:
        ref_path = await image_service.generate_scene_baseline_reference(
            scene=_serialize_scene(item),
            style=_project_style(db, item.project_id),
            project_id=item.project_id,
            seed=int(item.seed or 1200),
        )
        item.baseline_image_path = ref_path
        item.reference_images = json.dumps([ref_path], ensure_ascii=False)

    item.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(item)
    return _serialize_scene(item)


def _asset_project_id(db: Session, project_id: str) -> str:
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    return project.parent_project_id or project.id


def _assign_json_field(item, data: dict, key: str) -> None:
    if key not in data:
        return
    value = data.pop(key)
    if isinstance(value, str):
        setattr(item, key, value)
    else:
        setattr(item, key, json.dumps(value, ensure_ascii=False))


def _project_style(db: Session, project_id: str) -> str:
    project = db.query(Project).filter(Project.id == project_id).first()
    return (project.style if project else "anime") or "anime"


def _int_seed(value: str | None, fallback: int) -> int:
    try:
        return int(value or fallback)
    except (TypeError, ValueError):
        return fallback


def _serialize_character(item: Character) -> dict:
    return {
        "id": item.id,
        "project_id": item.project_id,
        "type": "character",
        "name": item.name,
        "appearance": json.loads(item.appearance) if item.appearance else {},
        "personality": item.personality,
        "visual_prompt": item.visual_prompt,
        "negative_prompt": item.negative_prompt,
        "voice_id": item.voice_id,
        "key_features": json.loads(item.key_features) if item.key_features else [],
        "reference_images": json.loads(item.reference_images) if item.reference_images else [],
        "default_outfit": item.default_outfit or "",
        "lora_profile": item.lora_profile or "",
        "ip_adapter_profile": item.ip_adapter_profile or "",
        "wardrobe_lock": item.wardrobe_lock or "",
        "seed": item.seed,
    }


def _serialize_scene(item: SceneAsset) -> dict:
    return {
        "id": item.id,
        "project_id": item.project_id,
        "type": "scene",
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
        "seed": item.seed,
    }
