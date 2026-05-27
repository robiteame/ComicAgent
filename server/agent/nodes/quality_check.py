from agent.state import AgentState


async def run(state: AgentState) -> dict:
    """Mark shots that still need attention after generation."""
    updated_shots = []
    issues_found = False

    for shot in state.get("shots", []):
        issues = []
        if shot.get("status") == "failed":
            issues.append("生成失败")
        if not shot.get("image_path"):
            issues.append("缺少画面")
        if shot.get("dialogue") and not shot.get("audio_path"):
            issues.append("缺少配音")
        if not shot.get("scene_description"):
            issues.append("缺少场景描述")

        if issues:
            shot["status"] = "needs_review"
            shot["visual_notes"] = "，".join(issues)
            issues_found = True
        elif shot.get("status") != "done":
            shot["status"] = "done"

        updated_shots.append(shot)

    return {
        "shots": updated_shots,
        "needs_human_review": issues_found,
        "current_step": "quality_check",
    }
