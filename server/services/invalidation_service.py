import json

from sqlalchemy.orm import Session

from models import Project, Shot


def invalidate_asset_consumers(
    db: Session,
    asset_project_id: str,
    *,
    character_id: str = "",
    scene_id: str = "",
) -> set[str]:
    """Invalidate shots that consume an edited series or episode asset."""

    children_by_parent: dict[str, list[str]] = {}
    for project_id, parent_id in db.query(Project.id, Project.parent_project_id).all():
        children_by_parent.setdefault(parent_id or "", []).append(project_id)
    project_ids: set[str] = set()
    pending = [asset_project_id]
    while pending:
        current = pending.pop()
        if current in project_ids:
            continue
        project_ids.add(current)
        pending.extend(children_by_parent.get(current, ()))

    candidates = db.query(Shot).filter(Shot.project_id.in_(project_ids)).all()
    affected = [
        shot
        for shot in candidates
        if (scene_id and shot.scene_asset_id == scene_id)
        or (character_id and character_id in _json_list(shot.character_asset_ids))
    ]
    affected_projects = {shot.project_id for shot in affected}
    for shot in affected:
        shot.confirmed = False
        shot.storyboard_status = "pending"
        shot.storyboard_path = ""
        shot.image_path = ""
        shot.audio_path = ""
        shot.video_path = ""
        shot.last_frame_path = ""
        shot.continuity_reference_path = ""
        shot.pose_reference_path = ""
        shot.depth_reference_path = ""
        shot.status = "pending"
        shot.version = (shot.version or 1) + 1
    if affected_projects:
        for project in db.query(Project).filter(Project.id.in_(affected_projects)).all():
            project.status = "assets_ready"

    scopes = {f"shot:{shot.id}" for shot in affected}
    scopes.update(f"project:{project_id}" for project_id in affected_projects)
    return scopes


def _json_list(raw: str | None) -> list:
    try:
        value = json.loads(raw or "[]")
        return list(value) if isinstance(value, list) else []
    except (TypeError, ValueError):
        return []
