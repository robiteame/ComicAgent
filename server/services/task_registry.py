"""Durable claim and lifecycle handling for background jobs.

The local task map is only an execution convenience. SQLite records are the
authority, which makes competing requests and server restarts explicit.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Coroutine

from sqlalchemy import text

from config import settings
from db import SessionLocal
from models import BackgroundJob, Project, Shot


ACTIVE_STATUSES = ("queued", "running", "cancelling")
TERMINAL_STATUSES = ("completed", "failed", "cancelled", "interrupted")
_tasks: dict[str, asyncio.Task] = {}
_claim_tokens: dict[str, str] = {}
_task_tokens: dict[asyncio.Task, str] = {}


@dataclass(frozen=True)
class ScopeCancellation:
    cancelled_jobs: int
    blocker_ids: tuple[str, ...]


def claim(key: str, scope: str, *, version: int = 0) -> bool:
    """Atomically acquire an operation and its project/shot scope."""

    now = datetime.utcnow()
    run_token = uuid.uuid4().hex
    db = SessionLocal()
    try:
        # Serializes the scope read and claim for all local server processes.
        db.execute(text("BEGIN IMMEDIATE"))
        existing = db.query(BackgroundJob).filter(BackgroundJob.idempotency_key == key).first()
        if existing and existing.status in ACTIVE_STATUSES:
            db.rollback()
            return False
        scope_owner = _scope_owner(db, scope)
        if scope_owner and scope_owner.idempotency_key != key:
            db.rollback()
            return False
        if existing is None:
            db.add(
                BackgroundJob(
                    id=uuid.uuid4().hex,
                    idempotency_key=key,
                    scope=scope,
                    status="running",
                    progress=0,
                    version=version,
                    run_token=run_token,
                    started_at=now,
                    updated_at=now,
                )
            )
        else:
            existing.scope = scope
            existing.status = "running"
            existing.progress = 0
            existing.error = ""
            existing.version = version
            existing.run_token = run_token
            existing.started_at = now
            existing.finished_at = None
            existing.updated_at = now
        db.commit()
        _claim_tokens[key] = run_token
        return True
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def active(key: str) -> bool:
    task = _tasks.get(key)
    if task is not None and not task.done():
        return True
    db = SessionLocal()
    try:
        return bool(
            db.query(BackgroundJob)
            .filter(BackgroundJob.idempotency_key == key, BackgroundJob.status.in_(ACTIVE_STATUSES))
            .first()
        )
    finally:
        db.close()


def update_progress(key: str, progress: int, *, run_token: str | None = None) -> bool:
    token = run_token or _run_token_for_current_task(key)
    if not token:
        return False
    db = SessionLocal()
    try:
        updated = (
            db.query(BackgroundJob)
            .filter(
                BackgroundJob.idempotency_key == key,
                BackgroundJob.run_token == token,
                BackgroundJob.status.in_(ACTIVE_STATUSES),
            )
            .update(
                {
                    BackgroundJob.progress: max(0, min(100, int(progress))),
                    BackgroundJob.updated_at: datetime.utcnow(),
                },
                synchronize_session=False,
            )
        )
        db.commit()
        return bool(updated)
    finally:
        db.close()


def snapshot(key: str) -> dict[str, Any] | None:
    """Return a detached, durable view of a job's latest state."""

    db = SessionLocal()
    try:
        job = db.query(BackgroundJob).filter(BackgroundJob.idempotency_key == key).first()
        if not job:
            return None
        return {
            "idempotency_key": job.idempotency_key,
            "scope": job.scope,
            "status": job.status,
            "progress": job.progress,
            "error": job.error,
            "version": job.version,
            "run_token": job.run_token,
            "started_at": job.started_at,
            "finished_at": job.finished_at,
            "updated_at": job.updated_at,
        }
    finally:
        db.close()


def finish(key: str, status: str, error: str = "", *, run_token: str | None = None) -> bool:
    if status not in TERMINAL_STATUSES:
        raise ValueError(f"invalid terminal job status: {status}")
    token = run_token or _run_token_for_current_task(key)
    if not token:
        return False
    db = SessionLocal()
    try:
        # Serialize validation and completion so a reclaimed row cannot change
        # attempts between the token check and the terminal update.
        db.execute(text("BEGIN IMMEDIATE"))
        job = (
            db.query(BackgroundJob)
            .filter(BackgroundJob.idempotency_key == key, BackgroundJob.run_token == token)
            .first()
        )
        # Scope cancellation owns the transition from ``cancelling`` to its
        # terminal state after every local coroutine has actually unwound.
        if job and job.status == "cancelling":
            db.rollback()
            return False
        if job and job.status in ACTIVE_STATUSES:
            job.status = status
            job.error = error[:8000]
            job.progress = 100 if status == "completed" else job.progress
            job.finished_at = datetime.utcnow()
            job.updated_at = job.finished_at
            if status != "completed":
                _reconcile_abandoned_work(db, job, status)
            db.commit()
            if _claim_tokens.get(key) == token:
                _claim_tokens.pop(key, None)
            return True
        db.rollback()
        return False
    finally:
        db.close()


def recover_interrupted() -> int:
    """Make work abandoned by a process restart visible and retryable."""

    db = SessionLocal()
    try:
        db.execute(text("BEGIN IMMEDIATE"))
        now = datetime.utcnow()
        jobs = db.query(BackgroundJob).filter(BackgroundJob.status.in_(ACTIVE_STATUSES)).all()
        for job in jobs:
            job.status = "interrupted"
            job.error = "server restarted before background job finished"
            job.finished_at = now
            job.updated_at = now
            _reconcile_abandoned_work(db, job, "interrupted")
        db.commit()
        return len(jobs)
    finally:
        db.close()


def register(key: str, task: asyncio.Task, *, run_token: str | None = None) -> bool:
    """Attach durable completion bookkeeping to a claimed asyncio task."""

    token = run_token or _claim_tokens.get(key)
    if not token:
        return False
    current = _tasks.get(key)
    if current is not None and not current.done():
        return False
    _tasks[key] = task
    _task_tokens[task] = token

    def _cleanup(done: asyncio.Task) -> None:
        if _tasks.get(key) is done:
            _tasks.pop(key, None)
        _task_tokens.pop(done, None)
        if done.cancelled():
            finish(key, "cancelled", "background job was cancelled", run_token=token)
            return
        try:
            error = done.exception()
        except asyncio.CancelledError:
            finish(key, "cancelled", "background job was cancelled", run_token=token)
            return
        if error is None:
            finish(key, "completed", run_token=token)
        else:
            finish(key, "failed", str(error), run_token=token)

    task.add_done_callback(_cleanup)
    return True


def start(key: str, coroutine: Coroutine[Any, Any, Any]) -> asyncio.Task:
    """Create and register a previously claimed coroutine without leaking its claim."""

    run_token = _claim_tokens.get(key)
    if not run_token:
        coroutine.close()
        raise RuntimeError("后台任务缺少有效的运行令牌")
    current = _tasks.get(key)
    if current is not None and not current.done():
        coroutine.close()
        raise RuntimeError("后台任务注册失败")
    try:
        task = asyncio.create_task(coroutine)
    except BaseException as exc:
        coroutine.close()
        finish(key, "failed", f"background task could not be created: {exc}", run_token=run_token)
        raise
    try:
        if not register(key, task, run_token=run_token):
            task.cancel()
            # A different local task already owns this attempt. Do not mark
            # its durable row failed just because a duplicate caller tried to
            # attach another coroutine.
            raise RuntimeError("后台任务注册失败")
    except BaseException as exc:
        if not task.done():
            task.cancel()
        if _tasks.get(key) is task:
            unregister(key, task)
            finish(key, "failed", f"background task could not be registered: {exc}", run_token=run_token)
        raise
    return task


def cancel(key: str) -> bool:
    task = _tasks.get(key)
    if task is not None and not task.done():
        task.cancel()
        # Cancellation callbacks run on the next event-loop turn. Clear the
        # user-facing transient state now while retaining the durable claim
        # until the coroutine has actually unwound.
        db = SessionLocal()
        try:
            run_token = _task_tokens.get(task)
            job = (
                db.query(BackgroundJob)
                .filter(
                    BackgroundJob.idempotency_key == key,
                    BackgroundJob.run_token == run_token,
                    BackgroundJob.status.in_(ACTIVE_STATUSES),
                )
                .first()
            )
            if job:
                _reconcile_abandoned_work(db, job, "cancelled")
                db.commit()
        finally:
            db.close()
        return True
    return False


async def cancel_scopes(
    scopes: set[str] | list[str] | tuple[str, ...],
    reason: str = "scope was cancelled",
    *,
    keep_blocked: bool = False,
) -> int | ScopeCancellation:
    """Block scopes, cancel local work, and wait until it cannot publish again."""

    scope_set = {scope for scope in scopes if scope}
    if not scope_set:
        return 0

    db = SessionLocal()
    try:
        db.execute(text("BEGIN IMMEDIATE"))
        active_jobs = db.query(BackgroundJob).filter(BackgroundJob.status.in_(ACTIVE_STATUSES)).all()
        jobs_by_id = {job.id: job for job in active_jobs if job.scope in scope_set}
        project_ids = {scope.split(":", 1)[1] for scope in scope_set if scope.startswith("project:")}
        shot_ids = {scope.split(":", 1)[1] for scope in scope_set if scope.startswith("shot:")}
        if project_ids:
            project_shot_ids = {
                shot_id
                for (shot_id,) in db.query(Shot.id).filter(Shot.project_id.in_(project_ids)).all()
            }
            for job in active_jobs:
                if job.scope.startswith("shot:") and job.scope.split(":", 1)[1] in project_shot_ids:
                    jobs_by_id[job.id] = job
        if shot_ids:
            shot_project_ids = {
                project_id
                for (project_id,) in db.query(Shot.project_id).filter(Shot.id.in_(shot_ids)).all()
            }
            for job in active_jobs:
                if job.scope.startswith("project:") and job.scope.split(":", 1)[1] in shot_project_ids:
                    jobs_by_id[job.id] = job
        jobs = list(jobs_by_id.values())
        job_count = len(jobs)
        owned_scopes = {job.scope for job in jobs}
        for job in jobs:
            job.status = "cancelling"
            job.error = reason[:8000]
            job.updated_at = datetime.utcnow()
            _reconcile_abandoned_work(db, job, "cancelled")
        # Empty scopes also need a durable owner so another process cannot claim
        # them while deletion waits for existing local tasks to unwind.
        blocker_ids: list[str] = []
        scopes_to_block = scope_set if keep_blocked else scope_set - owned_scopes
        for scope in scopes_to_block:
            blocker_id = uuid.uuid4().hex
            blocker_ids.append(blocker_id)
            db.add(
                BackgroundJob(
                    id=blocker_id,
                    idempotency_key=f"scope-block:{uuid.uuid4().hex}",
                    scope=scope,
                    status="cancelling",
                    error=reason[:8000],
                    run_token=uuid.uuid4().hex,
                    started_at=datetime.utcnow(),
                    updated_at=datetime.utcnow(),
                )
            )
        db.commit()
        keys_to_cancel = {job.idempotency_key for job in jobs}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    local_tasks = []
    for key in keys_to_cancel:
        task = _tasks.get(key)
        if task is not None and not task.done():
            task.cancel()
            local_tasks.append(task)
    if local_tasks:
        _, pending = await asyncio.wait(
            local_tasks,
            timeout=max(1, int(settings.BACKGROUND_TASK_CANCEL_TIMEOUT_SECONDS)),
        )
        if pending:
            # Fail closed: ``cancelling`` remains an active durable owner, so a
            # caller cannot delete data or launch replacement work while an old
            # coroutine may still publish.
            raise TimeoutError("等待后台任务取消超时；作用域保持锁定")

    db = SessionLocal()
    try:
        now = datetime.utcnow()
        cancelling = (
            db.query(BackgroundJob)
            .filter(
                BackgroundJob.id.in_([job.id for job in jobs]),
                BackgroundJob.status == "cancelling",
            )
            .all()
        )
        for job in cancelling:
            job.status = "cancelled"
            job.error = reason[:8000]
            job.finished_at = now
            job.updated_at = now
        if blocker_ids and not keep_blocked:
            db.query(BackgroundJob).filter(BackgroundJob.id.in_(blocker_ids)).delete(synchronize_session=False)
        db.commit()
        if keep_blocked:
            return ScopeCancellation(job_count, tuple(blocker_ids))
        return job_count
    finally:
        db.close()


def release_scope_block(cancellation: ScopeCancellation) -> None:
    if not cancellation.blocker_ids:
        return
    db = SessionLocal()
    try:
        db.query(BackgroundJob).filter(BackgroundJob.id.in_(cancellation.blocker_ids)).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


def unregister(key: str, task: asyncio.Task | None = None) -> None:
    if task is None or _tasks.get(key) is task:
        removed = _tasks.pop(key, None)
        if removed is not None:
            _task_tokens.pop(removed, None)


def keys() -> set[str]:
    return {key for key in list(_tasks) if active(key)}


def _run_token_for_current_task(key: str) -> str | None:
    try:
        task = asyncio.current_task()
    except RuntimeError:
        task = None
    if task is not None:
        # A coroutine that is not the registered owner must never fall back to
        # the latest claim token: doing so would let an old attempt update a
        # reclaimed row. Synchronous legacy callers still use the latest token
        # below for API compatibility.
        return _task_tokens.get(task)
    return _claim_tokens.get(key)


def _reconcile_abandoned_work(db, job: BackgroundJob, terminal_status: str) -> None:
    """Remove business rows from transient states after work stops unexpectedly."""

    parts = job.idempotency_key.split(":")
    if len(parts) < 3:
        return
    owner_type, owner_id, operation = parts[0], parts[1], parts[2]
    cancelled = terminal_status == "cancelled"

    if owner_type == "shot":
        shot = db.query(Shot).filter(Shot.id == owner_id).first()
        if not shot or (job.version and (shot.version or 1) != job.version):
            return
        if operation == "storyboard" and shot.storyboard_status == "queued":
            shot.storyboard_status = "pending" if cancelled else "failed"
            if shot.status == "pending":
                shot.status = "pending" if cancelled else "failed"
        elif operation == "video" and shot.status == "video_generating":
            if cancelled:
                shot.status = "storyboard_approved" if shot.confirmed else "storyboard_done"
            else:
                shot.status = "failed"
        return

    if owner_type != "project":
        return
    project = db.query(Project).filter(Project.id == owner_id).first()
    if operation in {"storyboard", "pipeline"}:
        queued = db.query(Shot).filter(Shot.project_id == owner_id, Shot.storyboard_status == "queued").all()
        for shot in queued:
            shot.storyboard_status = "pending" if cancelled else "failed"
            if shot.status == "pending":
                shot.status = "pending" if cancelled else "failed"
    if operation == "pipeline":
        videos = db.query(Shot).filter(Shot.project_id == owner_id, Shot.status == "video_generating").all()
        for shot in videos:
            shot.status = "storyboard_approved" if cancelled and shot.confirmed else "failed"

    if not project:
        return
    if project.status == "storyboard_generating":
        project.status = "assets_ready" if cancelled else "error"
    elif project.status == "rendering":
        project.status = "error"


def _scope_owner(db, scope: str) -> BackgroundJob | None:
    """Find an active owner, including the project/shot scope hierarchy."""

    active_jobs = db.query(BackgroundJob).filter(BackgroundJob.status.in_(ACTIVE_STATUSES)).all()
    exact = next((job for job in active_jobs if job.scope == scope), None)
    if exact:
        return exact

    owner_type, separator, owner_id = scope.partition(":")
    if not separator:
        return None
    if owner_type == "shot":
        project_id = db.query(Shot.project_id).filter(Shot.id == owner_id).scalar()
        if project_id:
            return next((job for job in active_jobs if job.scope == f"project:{project_id}"), None)
        return None
    if owner_type == "project":
        active_shot_jobs = {
            job.scope.split(":", 1)[1]: job
            for job in active_jobs
            if job.scope.startswith("shot:")
        }
        if not active_shot_jobs:
            return None
        shot_id = (
            db.query(Shot.id)
            .filter(Shot.project_id == owner_id, Shot.id.in_(active_shot_jobs))
            .limit(1)
            .scalar()
        )
        return active_shot_jobs.get(shot_id) if shot_id else None
    return None


__all__ = [
    "ScopeCancellation", "active", "cancel", "cancel_scopes", "claim", "finish", "keys", "recover_interrupted",
    "register", "release_scope_block", "snapshot", "start", "unregister", "update_progress",
]
