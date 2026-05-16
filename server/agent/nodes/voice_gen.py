from agent.state import AgentState
from services.tts_service import TTSService

tts_service = TTSService()


async def run(state: AgentState) -> dict:
    """配音生成节点：为有台词的镜头生成配音"""

    shots = state.get("shots", [])
    characters = state.get("characters", [])
    project_id = state["project_id"]

    # 构建角色名 -> 音色映射
    voice_map = {}
    for char in characters:
        voice_map[char["name"]] = char.get("voice_id", "")

    updated_shots = []
    for shot in shots:
        if not shot.get("dialogue"):
            updated_shots.append(shot)
            continue

        try:
            # 确定音色
            characters_in_scene = shot.get("characters_in_scene", [])
            speaker = characters_in_scene[0] if characters_in_scene else ""
            voice_id = voice_map.get(speaker, "")

            audio_path = await tts_service.generate_dialogue(
                text=shot["dialogue"],
                voice_id=voice_id,
                emotion=shot.get("emotion", "neutral"),
                project_id=project_id,
                shot_id=shot["shot_id"],
            )
            shot["audio_path"] = audio_path
        except Exception as e:
            shot["audio_path"] = ""

        updated_shots.append(shot)

    return {
        "shots": updated_shots,
        "current_step": "generate_voice",
    }
