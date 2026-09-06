import uuid
import json
import os
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from config import settings
from db import get_db
from models import Character, Project, SceneAsset, Shot
from services.security import UploadLimitExceeded, safe_path, save_upload_stream, validate_identifier, validate_video_upload
from services.storage_service import StorageQuotaExceeded, StorageService
from services.task_registry import ScopeCancellation, cancel_scopes, release_scope_block

router = APIRouter(prefix="/api/project", tags=["project"])
storage_service = StorageService()


@dataclass(frozen=True)
class _StagedProjectPath:
    source: Path
    trash: Path


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
    parent_id = payload.get("parent_project_id") or ""
    if parent_id:
        try:
            validate_identifier(parent_id, "父项目 ID")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        parent = db.query(Project).filter(Project.id == parent_id).first()
        if not parent:
            raise HTTPException(status_code=404, detail="父项目不存在")
        if parent.status == "deleting":
            raise HTTPException(status_code=409, detail="父项目正在删除")
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
    parent_titles = {project.id: project.title}
    result = _serialize_project(project, parent_titles)
    if first_episode:
        result["first_episode"] = _serialize_project(first_episode, parent_titles)
    return result


@router.get("/{project_id}")
async def get_project(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    if project.status == "deleting":
        raise HTTPException(status_code=409, detail="项目正在删除")
    _sync_completed_status(db, [project])
    return _serialize_project(project, _parent_titles(db, [project]))


@router.put("/{project_id}")
async def update_project(project_id: str, data: ProjectUpdate, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    changed = data.model_dump(exclude_unset=True)
    generation_fields = {"style", "output_format", "resolution"}
    generation_changed = any(
        key in generation_fields and getattr(project, key) != value
        for key, value in changed.items()
    )
    if "parent_project_id" in changed and changed["parent_project_id"]:
        parent_id = str(changed["parent_project_id"])
        try:
            validate_identifier(parent_id, "父项目 ID")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if parent_id == project.id:
            raise HTTPException(status_code=400, detail="项目不能成为自己的父项目")
        parent = db.query(Project).filter(Project.id == parent_id).first()
        if not parent:
            raise HTTPException(status_code=404, detail="父项目不存在")
        if parent.status == "deleting":
            raise HTTPException(status_code=409, detail="父项目正在删除")
        if _is_descendant(db, project.id, parent_id):
            raise HTTPException(status_code=400, detail="不能将项目移动到自己的子项目下")
    for key, value in changed.items():
        setattr(project, key, value)
    if generation_changed:
        _invalidate_project_generation(db, project)
    project.updated_at = datetime.utcnow()
    db.commit()
    if generation_changed:
        await cancel_scopes({f"project:{project_id}"}, "project generation settings changed")
    return {"id": project_id, "status": "updated"}


@router.delete("/{project_id}")
async def delete_project(project_id: str, db: Session = Depends(get_db)):
    try:
        validate_identifier(project_id, "项目 ID")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    delete_ids = _descendant_ids(db, project.id)
    previous_statuses = {
        target_id: status
        for target_id, status in db.query(Project.id, Project.status).filter(Project.id.in_(delete_ids)).all()
    }
    shot_ids = [shot_id for (shot_id,) in db.query(Shot.id).filter(Shot.project_id.in_(delete_ids)).all()]
    db.query(Project).filter(Project.id.in_(delete_ids)).update(
        {Project.status: "deleting", Project.updated_at: datetime.utcnow()},
        synchronize_session=False,
    )
    # End the read transaction before the registry takes its SQLite write lock.
    # Keep already-loaded identity values usable for callers after the bulk
    # deletion, matching SQLAlchemy's normal synchronized-delete behavior.
    expire_on_commit = db.expire_on_commit
    db.expire_on_commit = False
    db.commit()
    scopes = {f"project:{target_id}" for target_id in delete_ids}
    scopes.update(f"shot:{shot_id}" for shot_id in shot_ids)
    cancellation: ScopeCancellation | None = None
    staged_paths: list[_StagedProjectPath] = []
    trash_token = uuid.uuid4().hex
    try:
        cancellation = await cancel_scopes(scopes, "project was deleted", keep_blocked=True)
        if not isinstance(cancellation, ScopeCancellation):
            raise RuntimeError("项目任务作用域锁定失败")

        project = db.query(Project).filter(Project.id == project_id).first()
        if not project:
            return {"status": "deleted", "deleted_project_ids": delete_ids, "cleared_output_project_ids": []}

        staged_paths = _stage_project_paths(delete_ids, trash_token, previous_statuses)

        for target_id in delete_ids:
            db.query(Shot).filter(Shot.project_id == target_id).delete()
            db.query(Character).filter(Character.project_id == target_id).delete()
            db.query(SceneAsset).filter(SceneAsset.project_id == target_id).delete()

        deleted_files = [
            path.source.relative_to((settings.OUTPUT_DIR / "projects").resolve()).parts[0]
            for path in staged_paths
            if path.source.parent == (settings.OUTPUT_DIR / "projects").resolve()
        ]

        db.query(Project).filter(Project.id.in_(delete_ids)).delete()
        db.commit()
        _cleanup_staged_project_paths(staged_paths, trash_token)
        return {"status": "deleted", "deleted_project_ids": delete_ids, "cleared_output_project_ids": deleted_files}
    except BaseException:
        db.rollback()
        _restore_staged_project_paths(staged_paths)
        _remove_delete_manifest(trash_token)
        _prune_trash_parents(staged_paths)
        _prune_empty_trash_roots()
        _restore_project_statuses(previous_statuses)
        raise
    finally:
        if cancellation is not None:
            release_scope_block(cancellation)
        db.expire_on_commit = expire_on_commit


@router.post("/{project_id}/import-video")
async def import_final_video(project_id: str, file: UploadFile = File(...), db: Session = Depends(get_db)):
    try:
        validate_identifier(project_id, "项目 ID")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    suffix = Path(file.filename or "final.mp4").suffix.lower()
    if suffix not in {".mp4", ".m4v"}:
        raise HTTPException(status_code=400, detail="请上传 mp4 或 m4v 视频文件")
    mime = getattr(file, "content_type", None)

    candidate: Path | None = None
    cancellation: ScopeCancellation | None = None
    try:
        output_root = (settings.OUTPUT_DIR / "projects").resolve()
        output_dir = safe_path(output_root, project_id, "output", create_parent=True)
        target = output_dir / "final.mp4"
        candidate = output_dir / f".final-{uuid.uuid4().hex}.candidate"
        # Keep an existing final video intact until the replacement passes
        # signature checks, so the temporary candidate must fit alongside it.
        available = storage_service.ensure_project_capacity(project_id, replacing=target)
        size = await save_upload_stream(file, candidate, min(settings.MAX_VIDEO_UPLOAD_BYTES, available))
    except UploadLimitExceeded as exc:
        raise HTTPException(status_code=413, detail="上传视频超过大小或项目存储配额") from exc
    except StorageQuotaExceeded as exc:
        raise HTTPException(status_code=413, detail="项目媒体存储空间不足") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OSError as exc:
        if candidate is not None:
            candidate.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail="保存视频失败") from exc
    if size <= 1024:
        candidate.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="上传的视频文件为空或过小")
    try:
        validate_video_upload(candidate, mime)
    except (OSError, ValueError):
        candidate.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="上传文件不是有效的 MP4 视频")

    # Hold the project scope while promoting the candidate. This cancels and
    # waits for an in-flight render before it can publish over the import.
    db.rollback()
    try:
        cancellation = await cancel_scopes(
            {f"project:{project_id}"},
            "final video was imported",
            keep_blocked=True,
        )
        if not isinstance(cancellation, ScopeCancellation):
            raise RuntimeError("项目渲染作用域锁定失败")
        project = db.query(Project).filter(Project.id == project_id).first()
        if not project or project.status == "deleting":
            raise HTTPException(status_code=409, detail="项目正在删除或已不存在")
        output_dir = safe_path((settings.OUTPUT_DIR / "projects").resolve(), project_id, "output", create_parent=True)
        target = output_dir / "final.mp4"
        # Recheck against the post-upload tree while the project blocker is
        # held. The first quota check ran before the candidate was written and
        # could race with a render or another media writer.
        usage = storage_service.project_usage_bytes(project_id)
        replaced_bytes = target.stat().st_size if target.is_file() else 0
        if usage - replaced_bytes > int(settings.PROJECT_STORAGE_QUOTA_BYTES):
            raise HTTPException(status_code=413, detail="项目媒体存储空间不足")
    except BaseException:
        candidate.unlink(missing_ok=True)
        if cancellation is not None:
            release_scope_block(cancellation)
            cancellation = None
        raise

    backup = target.with_name(f".final-{uuid.uuid4().hex}.previous")
    had_previous = target.exists()
    try:
        if had_previous:
            os.replace(target, backup)
        os.replace(candidate, target)
        project.status = "completed"
        project.updated_at = datetime.utcnow()
        db.commit()
    except BaseException as exc:
        db.rollback()
        target.unlink(missing_ok=True)
        if had_previous and backup.exists():
            os.replace(backup, target)
        elif backup.exists():
            backup.unlink(missing_ok=True)
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(status_code=500, detail="发布视频失败") from exc
    finally:
        if cancellation is not None:
            release_scope_block(cancellation)
    try:
        backup.unlink(missing_ok=True)
    except OSError:
        pass
    return {**_serialize_project(project, _parent_titles(db, [project])), "imported": True}


@router.get("")
async def list_projects(db: Session = Depends(get_db)):
    projects = db.query(Project).order_by(Project.updated_at.desc()).all()
    _sync_completed_status(db, projects)
    parent_titles = _parent_titles(db, projects)
    return [_serialize_project(project, parent_titles) for project in projects]


@router.get("/{project_id}/episodes")
async def list_episodes(project_id: str, db: Session = Depends(get_db)):
    episodes = (
        db.query(Project)
        .filter(Project.parent_project_id == project_id, Project.project_type == "episode")
        .order_by(Project.episode_number.asc(), Project.created_at.asc())
        .all()
    )
    _sync_completed_status(db, episodes)
    parent_titles = _parent_titles(db, episodes)
    return [_serialize_project(project, parent_titles) for project in episodes]


def _serialize_project(project: Project, parent_titles: dict[str, str] | None = None) -> dict:
    video_path = _final_video_path(project.id)
    parent_title = (parent_titles or {}).get(project.parent_project_id or "", "")
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
        "video_path": (
            f"/output/projects/{project.id}/output/final.mp4"
            if project.status == "completed" and _has_file(video_path)
            else ""
        ),
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


def _stage_project_paths(project_ids: list[str], token: str, previous_statuses: dict[str, str]) -> list[_StagedProjectPath]:
    """Move project trees into same-filesystem trash before deleting rows."""

    staged: list[_StagedProjectPath] = []
    roots = ((settings.OUTPUT_DIR / "projects").resolve(), (settings.DATA_DIR / "uploads").resolve())
    try:
        _write_delete_manifest(token, project_ids, previous_statuses)
        for root in roots:
            for project_id in dict.fromkeys(project_ids):
                try:
                    validate_identifier(project_id, "项目 ID")
                except ValueError as exc:
                    raise HTTPException(status_code=400, detail=str(exc)) from exc
                source = (root / project_id).resolve()
                if root not in source.parents:
                    raise HTTPException(status_code=400, detail="项目资产路径异常，已拒绝删除")
                if not source.exists():
                    continue
                trash = (root / ".trash" / token / project_id).resolve()
                trash.parent.mkdir(parents=True, exist_ok=True)
                os.replace(source, trash)
                staged.append(_StagedProjectPath(source=source, trash=trash))
    except BaseException:
        _restore_staged_project_paths(staged)
        _remove_delete_manifest(token)
        _prune_trash_parents(staged)
        raise
    return staged


def _restore_staged_project_paths(staged: list[_StagedProjectPath]) -> None:
    for item in reversed(staged):
        if not item.trash.exists():
            continue
        item.source.parent.mkdir(parents=True, exist_ok=True)
        if item.source.exists():
            raise RuntimeError(f"无法恢复项目目录，目标已存在: {item.source}")
        os.replace(item.trash, item.source)
    _prune_trash_parents(staged)


def _cleanup_staged_project_paths(staged: list[_StagedProjectPath], token: str) -> None:
    for item in staged:
        shutil.rmtree(item.trash, ignore_errors=True)
    roots = {
        (settings.OUTPUT_DIR / "projects").resolve(),
        (settings.DATA_DIR / "uploads").resolve(),
    }
    for root in roots:
        trash_dir = root / ".trash" / token
        shutil.rmtree(trash_dir, ignore_errors=True)
    _remove_delete_manifest(token)
    _prune_trash_parents(staged)


def _prune_trash_parents(staged: list[_StagedProjectPath]) -> None:
    for item in staged:
        for directory in (item.trash.parent, item.trash.parent.parent):
            try:
                directory.rmdir()
            except OSError:
                pass


def _delete_manifest_path(token: str) -> Path:
    return (settings.OUTPUT_DIR / "projects" / ".trash" / token / "manifest.json").resolve()


def _write_delete_manifest(token: str, project_ids: list[str], previous_statuses: dict[str, str]) -> None:
    manifest = _delete_manifest_path(token)
    manifest.parent.mkdir(parents=True, exist_ok=True)
    temporary = manifest.with_name(f".{manifest.name}.{uuid.uuid4().hex}.tmp")
    payload = {
        "version": 1,
        "project_ids": list(dict.fromkeys(project_ids)),
        "previous_statuses": previous_statuses,
    }
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        with temporary.open("rb") as stream:
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, manifest)
    finally:
        temporary.unlink(missing_ok=True)


def _remove_delete_manifest(token: str) -> None:
    manifest = _delete_manifest_path(token)
    manifest.unlink(missing_ok=True)
    try:
        manifest.parent.rmdir()
    except OSError:
        pass


def recover_staged_project_deletions() -> int:
    """Recover or finish project deletions interrupted by process death."""

    trash_root = (settings.OUTPUT_DIR / "projects" / ".trash").resolve()
    if not trash_root.exists():
        return 0
    from db import SessionLocal

    recovered = 0
    db = SessionLocal()
    try:
        for manifest in sorted(trash_root.glob("*/manifest.json")):
            token = manifest.parent.name
            try:
                payload = json.loads(manifest.read_text(encoding="utf-8"))
                project_ids = [validate_identifier(item, "项目 ID") for item in payload.get("project_ids", [])]
                previous_statuses = {
                    validate_identifier(key, "项目 ID"): str(value)
                    for key, value in (payload.get("previous_statuses") or {}).items()
                }
            except (OSError, TypeError, ValueError, json.JSONDecodeError):
                continue
            existing = {
                project_id: status
                for project_id, status in db.query(Project.id, Project.status).filter(Project.id.in_(project_ids)).all()
            }
            if existing:
                staged: list[_StagedProjectPath] = []
                for root in ((settings.OUTPUT_DIR / "projects").resolve(), (settings.DATA_DIR / "uploads").resolve()):
                    for project_id in project_ids:
                        source = root / project_id
                        trash = root / ".trash" / token / project_id
                        if trash.exists() and not source.exists():
                            source.parent.mkdir(parents=True, exist_ok=True)
                            os.replace(trash, source)
                            staged.append(_StagedProjectPath(source=source, trash=trash))
                for project_id, status in previous_statuses.items():
                    project = db.query(Project).filter(Project.id == project_id).first()
                    if project and project.status == "deleting":
                        project.status = status
                db.commit()
                _remove_delete_manifest(token)
                shutil.rmtree(manifest.parent, ignore_errors=True)
                _prune_empty_trash_roots()
                recovered += 1
            else:
                # The row deletion committed before the process died; the
                # database is authoritative, so only discard staged files.
                for root in ((settings.OUTPUT_DIR / "projects").resolve(), (settings.DATA_DIR / "uploads").resolve()):
                    shutil.rmtree(root / ".trash" / token, ignore_errors=True)
                _prune_empty_trash_roots()
                recovered += 1
        db.commit()
    finally:
        db.close()
    return recovered


def _prune_empty_trash_roots() -> None:
    for root in (
        (settings.OUTPUT_DIR / "projects" / ".trash").resolve(),
        (settings.DATA_DIR / "uploads" / ".trash").resolve(),
    ):
        if root.exists():
            # Remove only empty token/parent directories. Any unknown file or
            # manifest remains for a later explicit recovery decision.
            for child in sorted(root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
                if child.is_dir():
                    try:
                        child.rmdir()
                    except OSError:
                        pass
        try:
            root.rmdir()
        except OSError:
            pass


def _restore_project_statuses(previous_statuses: dict[str, str]) -> None:
    if not previous_statuses:
        return
    restore_db = None
    try:
        from db import SessionLocal

        restore_db = SessionLocal()
        for project_id, status in previous_statuses.items():
            project = restore_db.query(Project).filter(Project.id == project_id).first()
            if project:
                project.status = status
        restore_db.commit()
    except Exception:
        if restore_db is not None:
            restore_db.rollback()
    finally:
        if restore_db is not None:
            restore_db.close()


def _descendant_ids(db: Session, root_id: str) -> list[str]:
    """Return a project and nested descendants using one indexed query."""

    children_by_parent: dict[str, list[str]] = {}
    for child_id, parent_id in db.query(Project.id, Project.parent_project_id).all():
        children_by_parent.setdefault(parent_id or "", []).append(child_id)
    result: list[str] = []
    seen: set[str] = set()
    pending = [root_id]
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        result.append(current)
        pending.extend(children_by_parent.get(current, ()))
    return result


def _is_descendant(db: Session, root_id: str, candidate_id: str) -> bool:
    return candidate_id in set(_descendant_ids(db, root_id)[1:])


def _parent_titles(db: Session, projects: list[Project]) -> dict[str, str]:
    parent_ids = {project.parent_project_id for project in projects if project.parent_project_id}
    if not parent_ids:
        return {}
    return dict(db.query(Project.id, Project.title).filter(Project.id.in_(parent_ids)).all())


def _has_file(path: Path) -> bool:
    return path.exists() and path.is_file() and path.stat().st_size > 0


def _sync_completed_status(db: Session, projects: list[Project]) -> None:
    changed = False
    nonfinal_statuses = {
        "draft",
        "pending",
        "assets_ready",
        "storyboard_generating",
        "storyboard_ready",
        "storyboard_approved",
        "rendering",
        "error",
        "failed",
        "cancelled",
        "interrupted",
        "deleting",
    }
    for project in projects:
        if project.status not in nonfinal_statuses and project.status != "completed" and _has_file(_final_video_path(project.id)):
            project.status = "completed"
            project.updated_at = datetime.utcnow()
            changed = True
    if changed:
        db.commit()


def _invalidate_project_generation(db: Session, project: Project) -> None:
    project.status = "assets_ready"
    for shot in db.query(Shot).filter(Shot.project_id == project.id).all():
        shot.confirmed = False
        shot.storyboard_status = "pending"
        shot.storyboard_path = ""
        shot.image_path = ""
        shot.audio_path = ""
        shot.video_path = ""
        shot.last_frame_path = ""
        shot.status = "pending"
        shot.version = (shot.version or 1) + 1
