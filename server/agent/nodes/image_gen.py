from agent.state import AgentState
from services.image_service import ImageService

image_service = ImageService()


async def run(state: AgentState) -> dict:
    """图像生成节点：为每个镜头生成图像，注入角色卡片保持一致性"""

    shots = state.get("shots", [])
    characters = state.get("characters", [])
    style_params = state.get("style_params", {})
    project_id = state["project_id"]

    updated_shots = []
    for shot in shots:
        if shot.get("status") == "done":
            updated_shots.append(shot)
            continue

        try:
            image_path = await image_service.generate_shot_image(
                shot=shot,
                characters=characters,
                style_params=style_params,
                project_id=project_id,
            )
            shot["image_path"] = image_path
            shot["status"] = "done"
        except Exception as e:
            shot["status"] = "failed"
            shot["visual_notes"] = f"生成失败: {str(e)}"

        updated_shots.append(shot)

    return {
        "shots": updated_shots,
        "current_step": "generate_images",
    }


async def regenerate_failed_shots(state: AgentState) -> dict:
    """重新生成失败的镜头"""
    shots = state.get("shots", [])
    characters = state.get("characters", [])
    style_params = state.get("style_params", {})
    project_id = state["project_id"]

    updated_shots = []
    for shot in shots:
        if shot.get("status") != "failed":
            updated_shots.append(shot)
            continue

        try:
            # 使用不同 seed 重试
            new_seed = (shot.get("seed", 42) or 42) + 100
            image_path = await image_service.generate_shot_image(
                shot=shot,
                characters=characters,
                style_params=style_params,
                project_id=project_id,
                seed=new_seed,
            )
            shot["image_path"] = image_path
            shot["status"] = "done"
            shot["version"] = shot.get("version", 1) + 1
        except Exception as e:
            shot["status"] = "failed"
            shot["visual_notes"] = f"重生成失败: {str(e)}"

        updated_shots.append(shot)

    return {
        "shots": updated_shots,
        "current_step": "shot_regeneration",
    }
