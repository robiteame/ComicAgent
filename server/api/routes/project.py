import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from config import settings
from db import get_db
from models import Project

router = APIRouter(prefix="/api/project", tags=["project"])


class ProjectCreate(BaseModel):
    title: str = "未命名项目"
    parent_project_id: str = ""
    project_type: str = "series"
    episode_number: int = 0
    genre: str = ""
    style: str = "anime"
    input_text: str = ""
    input_type: str = "text"
    output_format: str = "9:16"
    resolution: str = "1080p"
    platform: str = "douyin"


class ProjectUpdate(BaseModel):
    title: str | None = None
    parent_project_id: str | None = None
    project_type: str | None = None
    episode_number: int | None = None
    genre: str | None = None
    style: str | None = None
    output_format: str | None = None
    resolution: str | None = None
    platform: str | None = None


@router.post("")
async def create_project(data: ProjectCreate, db: Session = Depends(get_db)):
    payload = data.model_dump()
    if payload.get("project_type") == "episode" and not payload.get("episode_number"):
        payload["episode_number"] = _next_episode_number(db, payload.get("parent_project_id", ""))
    project = Project(id=str(uuid.uuid4()), **payload)
    db.add(project)
    db.commit()
    db.refresh(project)
    return _serialize_project(project)


@router.get("/{project_id}")
async def get_project(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    _sync_completed_status(db, [project])
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
    _sync_completed_status(db, projects)
    return [_serialize_project(project) for project in projects]


@router.get("/{project_id}/episodes")
async def list_episodes(project_id: str, db: Session = Depends(get_db)):
    episodes = (
        db.query(Project)
        .filter(Project.parent_project_id == project_id, Project.project_type == "episode")
        .order_by(Project.episode_number.asc(), Project.created_at.asc())
        .all()
    )
    _sync_completed_status(db, episodes)
    return [_serialize_project(project) for project in episodes]


def _serialize_project(project: Project) -> dict:
    video_path = _final_video_path(project.id)
    return {
        "id": project.id,
        "parent_project_id": project.parent_project_id or "",
        "project_type": project.project_type or "series",
        "episode_number": project.episode_number or 0,
        "title": project.title,
        "genre": project.genre,
        "style": project.style,
        "status": project.status,
        "video_path": f"/output/projects/{project.id}/output/final.mp4" if _has_file(video_path) else "",
        "input_text": project.input_text,
        "output_format": project.output_format,
        "resolution": project.resolution,
        "platform": project.platform,
        "created_at": project.created_at.isoformat(),
        "updated_at": project.updated_at.isoformat(),
    }


def _next_episode_number(db: Session, parent_project_id: str) -> int:
    if not parent_project_id:
        return 1
    existing = (
        db.query(Project)
        .filter(Project.parent_project_id == parent_project_id, Project.project_type == "episode")
        .order_by(Project.episode_number.desc())
        .first()
    )
    return int(existing.episode_number or 0) + 1 if existing else 1


def _final_video_path(project_id: str) -> Path:
    return settings.OUTPUT_DIR / "projects" / project_id / "output" / "final.mp4"


def _has_file(path: Path) -> bool:
    return path.exists() and path.is_file() and path.stat().st_size > 0


def _sync_completed_status(db: Session, projects: list[Project]) -> None:
    changed = False
    active_statuses = {"assets_ready", "storyboard_generating", "storyboard_ready", "rendering"}
    for project in projects:
        if project.status not in active_statuses and project.status != "completed" and _has_file(_final_video_path(project.id)):
            project.status = "completed"
            project.updated_at = datetime.utcnow()
            changed = True
    if changed:
        db.commit()
