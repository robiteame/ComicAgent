import json
import re
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from config import settings
from services.style_templates import create_custom_style_template, style_options

router = APIRouter(prefix="/api/settings", tags=["settings"])


class StyleTemplateCreate(BaseModel):
    label: str
    keywords: str
    negative_prompt: str = ""


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
