import traceback

from langgraph.graph import END, START, StateGraph

from .nodes import quality_check, script_parser, storyboard_gen, video_compose, voice_gen
from .state import AgentState


def build_graph() -> StateGraph:
    """Build the guarded Agent workflow.

    Phase 1: parse script -> generate shot list -> stop for project asset confirmation.
    Phase 2: storyboard approval happens outside the graph, then voice -> compose -> quality check.
    """
    graph = StateGraph(AgentState)

    graph.add_node("parse_script", _safe_node(script_parser.run, "parse_script"))
    graph.add_node("generate_storyboard", _safe_node(storyboard_gen.run, "generate_storyboard"))
    graph.add_node("wait_asset_confirm", _wait_asset_confirm_node)
    graph.add_node("wait_storyboard_approval", _wait_storyboard_approval_node)
    graph.add_node("generate_voice", _safe_node(voice_gen.run, "generate_voice"))
    graph.add_node("compose_video", _safe_node(video_compose.run, "compose_video"))
    graph.add_node("quality_check", _safe_node(quality_check.run, "quality_check"))
    graph.add_node("human_review", _human_review_node)
    graph.add_node("error_handler", _error_handler_node)

    graph.add_edge(START, "parse_script")
    graph.add_edge("parse_script", "generate_storyboard")
    graph.add_edge("generate_storyboard", "wait_asset_confirm")
    graph.add_edge("wait_asset_confirm", END)

    graph.add_edge("wait_storyboard_approval", "generate_voice")
    graph.add_edge("generate_voice", "compose_video")
    graph.add_edge("compose_video", "quality_check")
    graph.add_conditional_edges(
        "quality_check",
        _route_after_quality_check,
        {
            "pass": END,
            "human_review": "human_review",
        },
    )
    graph.add_edge("human_review", END)
    graph.add_edge("error_handler", END)
    return graph


def _safe_node(node_fn, node_name: str):
    async def wrapper(state: AgentState) -> dict:
        try:
            return await node_fn(state)
        except Exception as exc:
            return {
                "current_step": "error_handler",
                "errors": [f"[{node_name}] {exc}\n{traceback.format_exc()}"],
            }

    return wrapper


def _wait_asset_confirm_node(state: AgentState) -> dict:
    return {
        "current_step": "wait_asset_confirm",
        "needs_human_review": True,
    }


def _wait_storyboard_approval_node(state: AgentState) -> dict:
    return {
        "current_step": "wait_storyboard_approval",
        "needs_human_review": True,
    }


def _human_review_node(state: AgentState) -> dict:
    return {
        "current_step": "human_review",
        "needs_human_review": True,
    }


def _error_handler_node(state: AgentState) -> dict:
    return {
        "current_step": "error_handler",
        "needs_human_review": True,
        "errors": state.get("errors", []),
    }


def _route_after_quality_check(state: AgentState) -> str:
    if state.get("needs_human_review"):
        return "human_review"
    shots = state.get("shots", [])
    if any(s.get("status") in {"failed", "needs_review"} for s in shots):
        return "human_review"
    return "pass"


_graph = None


def get_graph() -> StateGraph:
    global _graph
    if _graph is None:
        _graph = build_graph().compile()
    return _graph
