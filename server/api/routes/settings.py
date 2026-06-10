import json
import re
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from config import settings
from services.model_config_service import get_model_config, save_model_config
from services.skill_config_service import list_skill_templates, save_skill_template, set_skill_bindings
from services.style_templates import create_custom_style_template, style_options

router = APIRouter(prefix="/api/settings", tags=["settings"])


class StyleTemplateCreate(BaseModel):
    label: str
    keywords: str
    negative_prompt: str = ""


class SkillTemplateSave(BaseModel):
    id: str | None = None
    name: str
    script_agent: dict
    storyboard_agent: dict


class SkillBindingsSave(BaseModel):
    global_default_template_id: str | None = None
    project_bindings: dict[str, str] | None = None
    episode_bindings: dict[str, str] | None = None


class ModelConfigSave(BaseModel):
    categories: dict[str, dict] | None = None
    script: dict | None = None
    image: dict | None = None
    video: dict | None = None
    voice: dict | None = None


@router.get("/style-templates")
async def get_style_templates():
    return {"templates": style_options()}


@router.post("/style-templates")
async def create_style_template(data: StyleTemplateCreate):
    label = data.label.strip()
    keywords = data.keywords.strip()
    if not label or not keywords:
        raise HTTPException(status_code=400, detail="模板名称和画风关键词不能为空")

    key = _template_key(label)
    template = create_custom_style_template(
        key=key,
        label=label,
        keywords=keywords,
        negative_prompt=data.negative_prompt.strip(),
        created_at=datetime.utcnow().isoformat(),
    )
    return template


@router.get("/skill-configs")
async def get_skill_configs():
    return list_skill_templates()


@router.post("/skill-configs")
async def save_skill_config(data: SkillTemplateSave):
    return save_skill_template(data.model_dump(exclude_none=True))


@router.put("/skill-configs/bindings")
async def update_skill_bindings(data: SkillBindingsSave):
    try:
        return set_skill_bindings(data.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/model-configs")
async def get_model_configs():
    return get_model_config()


@router.put("/model-configs")
async def update_model_configs(data: ModelConfigSave):
    return save_model_config(data.model_dump(exclude_none=True))


def _template_key(label: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", label.strip().lower()).strip("_")
    if not slug:
        slug = "custom"
    path = settings.DATA_DIR / "custom_style_templates.json"
    existing = {}
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8") or "{}")
    key = f"custom_{slug}"
    if key not in existing:
        return key
    index = 2
    while f"{key}_{index}" in existing:
        index += 1
    return f"{key}_{index}"
