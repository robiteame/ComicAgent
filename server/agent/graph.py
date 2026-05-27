import traceback
from langgraph.graph import StateGraph, START, END
from .state import AgentState
from .nodes import script_parser, storyboard_gen, image_gen, voice_gen, video_compose, quality_check
from .edges.conditions import route_after_storyboard, route_after_quality_check


def build_graph() -> StateGraph:
    """构建 LangGraph Agent 流水线

    两阶段流水线：
      Phase 1: parse_script → generate_storyboard → [等待用户确认分镜]
      Phase 2: 用户确认后 → generate_images → generate_voice → compose_video → quality_check
    """
    graph = StateGraph(AgentState)

    # 注册节点
    graph.add_node("parse_script", _safe_node(script_parser.run, "parse_script"))
    graph.add_node("generate_storyboard", _safe_node(storyboard_gen.run, "generate_storyboard"))
    graph.add_node("generate_images", _safe_node(image_gen.run, "generate_images"))
    graph.add_node("generate_voice", _safe_node(voice_gen.run, "generate_voice"))
    graph.add_node("compose_video", _safe_node(video_compose.run, "compose_video"))
    graph.add_node("quality_check", _safe_node(quality_check.run, "quality_check"))
    graph.add_node("human_review", _human_review_node)
    graph.add_node("shot_regeneration", _shot_regeneration_node)
    graph.add_node("error_handler", _error_handler_node)
    graph.add_node("wait_storyboard_confirm", _wait_storyboard_confirm_node)

    # 主流程边
    graph.add_edge(START, "parse_script")
    graph.add_edge("parse_script", "generate_storyboard")

    # 分镜确认门控：未确认则暂停流水线等待用户确认
    graph.add_conditional_edges(
        "generate_storyboard",
        route_after_storyboard,
        {
            "continue": "generate_images",
            "wait_confirm": "wait_storyboard_confirm",
        },
    )
    graph.add_edge("wait_storyboard_confirm", END)

    graph.add_edge("generate_images", "generate_voice")
    graph.add_edge("generate_voice", "compose_video")
    graph.add_edge("compose_video", "quality_check")

    # 条件路由：质量校验后
    graph.add_conditional_edges(
        "quality_check",
        route_after_quality_check,
        {
            "pass": END,
            "regenerate_shot": "shot_regeneration",
            "human_review": "human_review",
        },
    )

    # 人工审核/镜头重生成后回到合成
    graph.add_edge("human_review", "compose_video")
    graph.add_edge("shot_regeneration", "quality_check")

    # 异常处理节点直接终止
    graph.add_edge("error_handler", END)

    return graph


def _safe_node(node_fn, node_name: str):
    """包装节点函数，捕获异常并路由到 error_handler"""
    async def wrapper(state: AgentState) -> dict:
        try:
            return await node_fn(state)
        except Exception as e:
            return {
                "current_step": "error_handler",
                "errors": [f"[{node_name}] {str(e)}\n{traceback.format_exc()}"],
            }
    return wrapper


def _human_review_node(state: AgentState) -> dict:
    """人工审核节点 - 等待用户反馈"""
    return {
        "current_step": "human_review",
        "needs_human_review": True,
    }


def _shot_regeneration_node(state: AgentState) -> dict:
    """镜头重生成节点 - 重新生成失败的镜头"""
    from .nodes.image_gen import regenerate_failed_shots
    return regenerate_failed_shots(state)


def _wait_storyboard_confirm_node(state: AgentState) -> dict:
    """等待用户确认分镜 - 流水线暂停点"""
    return {
        "current_step": "wait_storyboard_confirm",
        "needs_human_review": True,
    }


def _error_handler_node(state: AgentState) -> dict:
    """统一异常处理节点"""
    errors = state.get("errors", [])
    return {
        "current_step": "error_handler",
        "needs_human_review": True,
        "errors": errors,
    }


# 全局图实例
_graph = None


def get_graph() -> StateGraph:
    global _graph
    if _graph is None:
        _graph = build_graph().compile()
    return _graph
