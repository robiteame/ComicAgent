from langgraph.graph import StateGraph, START, END
from .state import AgentState
from .nodes import script_parser, storyboard_gen, image_gen, voice_gen, video_compose, quality_check
from .edges.conditions import route_after_quality_check


def build_graph() -> StateGraph:
    """构建 LangGraph Agent 流水线"""
    graph = StateGraph(AgentState)

    # 注册节点
    graph.add_node("parse_script", script_parser.run)
    graph.add_node("generate_storyboard", storyboard_gen.run)
    graph.add_node("generate_images", image_gen.run)
    graph.add_node("generate_voice", voice_gen.run)
    graph.add_node("compose_video", video_compose.run)
    graph.add_node("quality_check", quality_check.run)
    graph.add_node("human_review", _human_review_node)
    graph.add_node("shot_regeneration", _shot_regeneration_node)

    # 主流程边
    graph.add_edge(START, "parse_script")
    graph.add_edge("parse_script", "generate_storyboard")
    graph.add_edge("generate_storyboard", "generate_images")
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

    return graph


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


# 全局图实例
_graph = None


def get_graph() -> StateGraph:
    global _graph
    if _graph is None:
        _graph = build_graph().compile()
    return _graph
