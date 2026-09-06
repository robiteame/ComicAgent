"""自动模式 LangGraph 流水线。

本图是【自动模式】的真实执行器:一次 `ainvoke` 从剧本解析跑到成片导出,中途无人工卡点。
每个节点都是薄包装,在函数体内**惰性 import** 并复用 `api/routes` 里已验证的步骤函数 ——
与【手动模式】(前端逐步触发 `api/routes`)共用同一批业务函数,不重复实现业务逻辑。

`/api/graph/structure` 由 `build_graph()` + `GRAPH_NODE_META` 派生,保证可视化与真实流程一致。

注:各步骤函数沿用其手动模式的 WebSocket 进度百分比,自动模式下数值会跳变,属已知 cosmetic。
"""

import traceback

from langgraph.graph import END, START, StateGraph

from .state import AgentState

# 节点可视化元数据(供 /api/graph/structure 派生中文标签/类型/描述)
GRAPH_NODE_META: dict[str, dict] = {
    "parse_and_storyboard": {
        "label": "剧本解析+分镜",
        "type": "process",
        "description": "解析人物/场景/对白,生成分镜列表、角色三视图与场景基准图",
    },
    "generate_storyboard_images": {
        "label": "定稿故事板",
        "type": "process",
        "description": "逐镜头生成成品故事板参考图",
    },
    "auto_approve_storyboard": {
        "label": "自动审核",
        "type": "process",
        "description": "自动模式跳过人工卡点,直接确认全部已出图镜头",
    },
    "generate_shot_videos": {
        "label": "逐镜头视频",
        "type": "process",
        "description": "逐镜头生成配音并调用 Seedance 出视频",
    },
    "compose": {
        "label": "合成成片",
        "type": "output",
        "description": "FFmpeg 合成最终成片",
    },
}


def build_graph() -> StateGraph:
    """构建自动模式的端到端流水线图(线性串联,失败即短路至 END)。"""
    graph = StateGraph(AgentState)

    graph.add_node("parse_and_storyboard", _parse_and_storyboard)
    graph.add_node("generate_storyboard_images", _generate_storyboard_images)
    graph.add_node("auto_approve_storyboard", _auto_approve_storyboard)
    graph.add_node("generate_shot_videos", _generate_shot_videos)
    graph.add_node("compose", _compose)

    graph.add_edge(START, "parse_and_storyboard")
    graph.add_edge("parse_and_storyboard", "generate_storyboard_images")
    graph.add_edge("generate_storyboard_images", "auto_approve_storyboard")
    graph.add_edge("auto_approve_storyboard", "generate_shot_videos")
    graph.add_edge("generate_shot_videos", "compose")
    graph.add_edge("compose", END)
    return graph


# --- 节点实现:复用 route 层步骤函数 ---


async def _parse_and_storyboard(state: AgentState) -> dict:
    if state.get("errors"):
        return {}
    from api.routes.script import _run_storyboard_phase

    project_id = state["project_id"]
    try:
        await _run_storyboard_phase(project_id, dict(state.get("initial_state") or {}))
    except Exception as exc:
        return _abort("parse_and_storyboard", exc)
    if _project_failed(project_id):
        return _abort("parse_and_storyboard", "剧本解析或分镜生成失败")
    return {"current_step": "parse_and_storyboard"}


async def _generate_storyboard_images(state: AgentState) -> dict:
    if state.get("errors"):
        return {}
    from api.routes.shot import _run_storyboard_generation

    project_id = state["project_id"]
    shot_ids = _shot_ids(project_id)
    if not shot_ids:
        return _abort("generate_storyboard_images", "无分镜可生成定稿故事板")
    try:
        await _run_storyboard_generation(project_id, shot_ids)
    except Exception as exc:
        return _abort("generate_storyboard_images", exc)
    if _project_failed(project_id):
        return _abort("generate_storyboard_images", "定稿故事板生成失败")
    return {"current_step": "generate_storyboard_images"}


async def _auto_approve_storyboard(state: AgentState) -> dict:
    if state.get("errors"):
        return {}
    from db import SessionLocal
    from models import Shot

    project_id = state["project_id"]
    db = SessionLocal()
    try:
        shots = db.query(Shot).filter(Shot.project_id == project_id).all()
        for shot in shots:
            if shot.storyboard_path or shot.image_path:
                shot.confirmed = True
                shot.status = "storyboard_approved"
        db.commit()
    finally:
        db.close()
    return {"current_step": "auto_approve_storyboard"}


async def _generate_shot_videos(state: AgentState) -> dict:
    if state.get("errors"):
        return {}
    from api.routes.shot import _run_single_shot_video

    project_id = state["project_id"]
    for shot_id in _shot_ids(project_id):
        try:
            await _run_single_shot_video(shot_id, force=False)
        except Exception as exc:
            return _abort("generate_shot_videos", exc)
    if _has_unfinished_videos(project_id):
        return _abort("generate_shot_videos", "仍有镜头视频未生成")
    return {"current_step": "generate_shot_videos"}


async def _compose(state: AgentState) -> dict:
    if state.get("errors"):
        return {}
    from api.routes.render import _render_task

    project_id = state["project_id"]
    try:
        await _render_task(project_id, state.get("output_format") or "9:16", state.get("resolution") or "1080p")
    except Exception as exc:
        return _abort("compose", exc)
    # A route may report a non-throwing status for compatibility with older
    # callers. Treat anything except completed as a failed graph node.
    from api.routes.render import _render_status

    render_status = _render_status.get(project_id, {})
    if render_status.get("status") != "completed":
        return _abort("compose", render_status.get("message") or "成片导出未完成")
    return {"current_step": "compose"}


# --- 辅助 ---


def _abort(node: str, exc) -> dict:
    detail = f"{exc}\n{traceback.format_exc()}" if isinstance(exc, Exception) else str(exc)
    return {"errors": [f"[{node}] {detail}"], "current_step": "aborted"}


def _shot_ids(project_id: str) -> list[str]:
    from db import SessionLocal
    from models import Shot

    db = SessionLocal()
    try:
        return [s.id for s in db.query(Shot).filter(Shot.project_id == project_id).order_by(Shot.sequence).all()]
    finally:
        db.close()


def _project_failed(project_id: str) -> bool:
    from db import SessionLocal
    from models import Project

    db = SessionLocal()
    try:
        project = db.query(Project).filter(Project.id == project_id).first()
        return bool(project and project.status == "error")
    finally:
        db.close()


def _has_unfinished_videos(project_id: str) -> bool:
    from db import SessionLocal
    from models import Shot

    db = SessionLocal()
    try:
        shots = db.query(Shot).filter(Shot.project_id == project_id).all()
        return (not shots) or any(not s.video_path for s in shots)
    finally:
        db.close()


_graph = None


def get_graph() -> StateGraph:
    global _graph
    if _graph is None:
        _graph = build_graph().compile()
    return _graph
