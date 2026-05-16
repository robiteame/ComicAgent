import json
from agent.state import AgentState
from services.llm_service import LLMService

llm_service = LLMService()


async def run(state: AgentState) -> dict:
    """质量校验节点：检查镜头质量，标记有问题的镜头"""

    shots = state.get("shots", [])
    characters = state.get("characters", [])

    updated_shots = []
    issues_found = False

    for shot in shots:
        if shot.get("status") == "failed":
            updated_shots.append(shot)
            issues_found = True
            continue

        # 基础检查：图像和音频是否存在
        if not shot.get("image_path"):
            shot["status"] = "failed"
            shot["visual_notes"] = "图像未生成"
            issues_found = True
            updated_shots.append(shot)
            continue

        # LLM 视觉质量校验（可选，Demo 阶段可简化）
        check_result = await _check_shot_quality(shot, characters)

        if not check_result["passed"]:
            shot["status"] = "needs_review"
            shot["visual_notes"] = "; ".join(check_result.get("issues", []))
            issues_found = True

        updated_shots.append(shot)

    needs_human = state.get("needs_human_review", False) or issues_found

    return {
        "shots": updated_shots,
        "needs_human_review": needs_human,
        "current_step": "quality_check",
    }


async def _check_shot_quality(shot: dict, characters: list) -> dict:
    """单镜头质量校验（Demo 阶段简化版）"""

    # 简化校验：只检查基本完整性
    if not shot.get("image_path"):
        return {"passed": False, "issues": ["图像未生成"], "score": 0}

    if not shot.get("scene_description"):
        return {"passed": False, "issues": ["缺少场景描述"], "score": 0}

    # 通过基础校验
    return {"passed": True, "issues": [], "score": 85}
