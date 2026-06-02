from agent.state import AgentState


def route_after_quality_check(state: AgentState) -> str:
    """质量校验后的路由决策。"""
    if state.get("needs_human_review"):
        return "human_review"

    shots = state.get("shots", [])
    if any(s.get("status") in {"failed", "needs_review"} for s in shots):
        return "human_review"

    return "pass"
