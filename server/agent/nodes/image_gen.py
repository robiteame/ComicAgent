import inspect

from agent.state import AgentState
from services.image_service import ImageService

image_service = ImageService()


async def run(state: AgentState) -> dict:
    """Generate one image for each storyboard shot."""

    shots = state.get("shots", [])
    characters = state.get("characters", [])
    style_params = state.get("style_params", {})
    project_id = state["project_id"]
    on_shot_done = state.get("on_shot_done")

    updated_shots = []
    failures: list[str] = []
    for shot in shots:
        if shot.get("status") == "done" and shot.get("image_path"):
            updated_shots.append(shot)
            if callable(on_shot_done):
                result = on_shot_done(shot)
                if inspect.isawaitable(result):
                    await result
            continue

        try:
            scene_chars = shot.get("characters_in_scene", [])
            char_seed = next((c.get("seed", 42) for c in characters if c["name"] in scene_chars), None)
            effective_seed = shot.get("seed", char_seed or 42)

            image_path = await image_service.generate_shot_image(
                shot=shot,
                characters=characters,
                style_params=style_params,
                project_id=project_id,
                seed=effective_seed,
            )
            shot["image_path"] = image_path
            shot["status"] = "done"
        except Exception as e:
            shot["status"] = "failed"
            shot["visual_notes"] = f"生成失败: {str(e)}"
            failures.append(f"{shot.get('shot_id')}: {e}")

        updated_shots.append(shot)
        if callable(on_shot_done):
            result = on_shot_done(shot)
            if inspect.isawaitable(result):
                await result

    if failures:
        raise RuntimeError("分镜画面生成失败: " + " | ".join(failures))

    return {
        "shots": updated_shots,
        "current_step": "generate_images",
    }


async def regenerate_failed_shots(state: AgentState) -> dict:
    """Regenerate shots that failed in the image stage."""
    shots = state.get("shots", [])
    characters = state.get("characters", [])
    style_params = state.get("style_params", {})
    project_id = state["project_id"]

    updated_shots = []
    failures: list[str] = []
    for shot in shots:
        if shot.get("status") != "failed":
            updated_shots.append(shot)
            continue

        try:
            shot["seed"] = shot.get("seed", 42) + 100
            shot["version"] = shot.get("version", 1) + 1

            image_path = await image_service.generate_shot_image(
                shot=shot,
                characters=characters,
                style_params=style_params,
                project_id=project_id,
                seed=shot["seed"],
            )
            shot["image_path"] = image_path
            shot["status"] = "done"
        except Exception as e:
            shot["status"] = "failed"
            shot["visual_notes"] = f"重新生成失败: {str(e)}"
            failures.append(f"{shot.get('shot_id')}: {e}")

        updated_shots.append(shot)

    if failures:
        raise RuntimeError("失败镜头重新生成仍失败: " + " | ".join(failures))

    return {
        "shots": updated_shots,
        "current_step": "shot_regeneration",
    }
