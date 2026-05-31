import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db import get_db
from models import Character, Project, SceneAsset, Shot

router = APIRouter(prefix="/api/asset", tags=["asset"])


class ShotAssetUpdate(BaseModel):
    scene_asset_id: str = ""
    character_asset_ids: list[str] = []


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


def _asset_project_id(db: Session, project_id: str) -> str:
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    return project.parent_project_id or project.id


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
        "seed": item.seed,
    }
