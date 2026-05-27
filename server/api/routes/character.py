import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db import get_db
from models import Character

router = APIRouter(prefix="/api/character", tags=["character"])


class CharacterUpdate(BaseModel):
    name: str | None = None
    appearance: str | None = None
    personality: str | None = None
    visual_prompt: str | None = None
    negative_prompt: str | None = None
    voice_id: str | None = None
    emotion_variants: str | None = None
    key_features: str | None = None
    default_outfit: str | None = None
    seed: str | None = None


@router.get("/{project_id}/characters")
async def get_project_characters(project_id: str, db: Session = Depends(get_db)):
    chars = db.query(Character).filter(Character.project_id == project_id).all()
    return [
        {
            "id": c.id,
            "project_id": c.project_id,
            "name": c.name,
            "appearance": json.loads(c.appearance) if c.appearance else {},
            "personality": c.personality,
            "visual_prompt": c.visual_prompt,
            "negative_prompt": c.negative_prompt,
            "voice_id": c.voice_id,
            "emotion_variants": json.loads(c.emotion_variants) if c.emotion_variants else {},
            "key_features": json.loads(c.key_features) if c.key_features else [],
            "default_outfit": c.default_outfit,
            "reference_images": json.loads(c.reference_images) if c.reference_images else [],
            "seed": c.seed,
        }
        for c in chars
    ]


@router.put("/{character_id}")
async def update_character(character_id: str, data: CharacterUpdate, db: Session = Depends(get_db)):
    char = db.query(Character).filter(Character.id == character_id).first()
    if not char:
        raise HTTPException(status_code=404, detail="角色不存在")
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(char, key, value)
    db.commit()
    return {"id": char.id, "status": "updated"}
