from agent.state import AgentState


def route_after_quality_check(state: AgentState) -> str:
    """质量校验后的路由决策"""
    if state.get("needs_human_review"):
        return "human_review"

    shots = state.get("shots", [])
    failed_shots = [s for s in shots if s.get("status") == "failed"]
    needs_review_shots = [s for s in shots if s.get("status") == "needs_review"]

    if needs_review_shots:
        return "human_review"

    if failed_shots:
        return "regenerate_shot"

    return "pass"


def should_regenerate_shot(state: AgentState) -> bool:
    """判断是否需要重新生成某个镜头"""
    shots = state.get("shots", [])
    return any(s.get("status") == "failed" for s in shots)


def has_pending_shots(state: AgentState) -> bool:
    """判断是否有待处理的镜头"""
    shots = state.get("shots", [])
    return any(s.get("status") == "pending" for s in shots)
