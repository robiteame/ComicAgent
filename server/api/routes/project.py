import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db import get_db
from models import Project

router = APIRouter(prefix="/api/project", tags=["project"])


class ProjectCreate(BaseModel):
    title: str = "未命名项目"
    genre: str = ""
    style: str = "anime"
    input_text: str = ""
    input_type: str = "text"
    output_format: str = "9:16"
    resolution: str = "1080p"
    platform: str = "douyin"


class ProjectUpdate(BaseModel):
    title: str | None = None
    genre: str | None = None
    style: str | None = None
    output_format: str | None = None
    resolution: str | None = None
    platform: str | None = None


@router.post("")
async def create_project(data: ProjectCreate, db: Session = Depends(get_db)):
    project = Project(id=str(uuid.uuid4()), **data.model_dump())
    db.add(project)
    db.commit()
    db.refresh(project)
    return _serialize_project(project)


@router.get("/{project_id}")
async def get_project(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    return _serialize_project(project)


@router.put("/{project_id}")
async def update_project(project_id: str, data: ProjectUpdate, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(project, key, value)
    project.updated_at = datetime.utcnow()
    db.commit()
    return {"id": project.id, "status": "updated"}


@router.get("")
async def list_projects(db: Session = Depends(get_db)):
    projects = db.query(Project).order_by(Project.updated_at.desc()).all()
    return [_serialize_project(project) for project in projects]


def _serialize_project(project: Project) -> dict:
    return {
        "id": project.id,
        "title": project.title,
        "genre": project.genre,
        "style": project.style,
        "status": project.status,
        "input_text": project.input_text,
        "output_format": project.output_format,
        "resolution": project.resolution,
        "platform": project.platform,
        "created_at": project.created_at.isoformat(),
        "updated_at": project.updated_at.isoformat(),
    }
