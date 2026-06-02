import uuid
import json
import shutil
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from config import settings
from db import get_db
from models import Character, Project, SceneAsset, Shot

router = APIRouter(prefix="/api/project", tags=["project"])


class ProjectCreate(BaseModel):
    title: str = "未命名项目"
    first_episode_title: str = ""
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
    first_episode_title = payload.pop("first_episode_title", "")
    if payload.get("project_type") == "episode" and not payload.get("episode_number"):
        payload["episode_number"] = _next_episode_number(db, payload.get("parent_project_id", ""))
    project = Project(id=str(uuid.uuid4()), **payload)
    db.add(project)
    first_episode = None
    if project.project_type == "series":
        first_episode = Project(
            id=str(uuid.uuid4()),
            title=first_episode_title.strip() or "第 1 集",
            parent_project_id=project.id,
            project_type="episode",
            episode_number=1,
            genre=project.genre,
            style=project.style,
            input_text="",
            input_type="text",
            output_format=project.output_format,
            resolution=project.resolution,
            platform=project.platform,
            consistency_config=project.consistency_config,
        )
        db.add(first_episode)
    db.commit()
    db.refresh(project)
    if first_episode:
        db.refresh(first_episode)
    result = _serialize_project(project, db)
    if first_episode:
        result["first_episode"] = _serialize_project(first_episode, db)
    return result


@router.get("/{project_id}")
async def get_project(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    _sync_completed_status(db, [project])
    return _serialize_project(project, db)


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


@router.delete("/{project_id}")
async def delete_project(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    delete_ids = [project.id]
    if project.project_type != "episode":
        children = db.query(Project).filter(Project.parent_project_id == project.id).all()
        delete_ids.extend(child.id for child in children)

    for target_id in delete_ids:
        db.query(Shot).filter(Shot.project_id == target_id).delete()
        db.query(Character).filter(Character.project_id == target_id).delete()
        db.query(SceneAsset).filter(SceneAsset.project_id == target_id).delete()

    deleted_files = []
    for target_id in dict.fromkeys(delete_ids):
        if _remove_project_output_dir(target_id):
            deleted_files.append(target_id)

    db.query(Project).filter(Project.id.in_(delete_ids)).delete()
    db.commit()
    return {"status": "deleted", "deleted_project_ids": delete_ids, "cleared_output_project_ids": deleted_files}


@router.post("/{project_id}/import-video")
async def import_final_video(project_id: str, file: UploadFile = File(...), db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    suffix = Path(file.filename or "final.mp4").suffix.lower()
    if suffix not in {".mp4", ".m4v"}:
        raise HTTPException(status_code=400, detail="请上传 mp4 或 m4v 视频文件")

    output_dir = settings.OUTPUT_DIR / "projects" / project_id / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / "final.mp4"
    target.write_bytes(await file.read())
    if target.stat().st_size <= 1024:
        raise HTTPException(status_code=400, detail="上传的视频文件为空或过小")
    project.status = "completed"
    project.updated_at = datetime.utcnow()
    db.commit()
    return {**_serialize_project(project, db), "imported": True}


@router.get("")
async def list_projects(db: Session = Depends(get_db)):
    projects = db.query(Project).order_by(Project.updated_at.desc()).all()
    _sync_completed_status(db, projects)
    return [_serialize_project(project, db) for project in projects]


@router.get("/{project_id}/episodes")
async def list_episodes(project_id: str, db: Session = Depends(get_db)):
    episodes = (
        db.query(Project)
        .filter(Project.parent_project_id == project_id, Project.project_type == "episode")
        .order_by(Project.episode_number.asc(), Project.created_at.asc())
        .all()
    )
    _sync_completed_status(db, episodes)
    return [_serialize_project(project, db) for project in episodes]


def _serialize_project(project: Project, db: Session | None = None) -> dict:
    video_path = _final_video_path(project.id)
    parent_title = ""
    if db and project.parent_project_id:
        parent = db.query(Project).filter(Project.id == project.parent_project_id).first()
        parent_title = parent.title if parent else ""
    return {
        "id": project.id,
        "parent_project_id": project.parent_project_id or "",
        "parent_project_title": parent_title,
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
        "consistency_config": json.loads(project.consistency_config) if project.consistency_config else {},
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


def _remove_project_output_dir(project_id: str) -> bool:
    root = (settings.OUTPUT_DIR / "projects").resolve()
    target = (root / project_id).resolve()
    if root not in target.parents:
        raise HTTPException(status_code=400, detail="项目资产路径异常，已拒绝删除")
    if not target.exists():
        return False
    shutil.rmtree(target)
    return True


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
