import json

from agent.state import AgentState
from services.llm_service import LLMService

llm_service = LLMService()


async def run(state: AgentState) -> dict:
    """Generate storyboard shots from parsed scenes."""
    if state.get("storyboard_confirmed") and state.get("shots"):
        return {"current_step": "generate_storyboard"}

    result = None
    if llm_service.available:
        try:
            result = await llm_service.call_json(
                _load_system_prompt(),
                _build_task_prompt(
                    script_scenes=state.get("script_scenes", []),
                    characters=state.get("characters", []),
                    style=state.get("style", "anime"),
                    platform=state.get("platform", "douyin"),
                    target_duration=state.get("target_duration", 30),
                ),
                temperature=0.35,
            )
        except Exception:
            result = None

    raw_shots = result if isinstance(result, list) else (result or {}).get("shots", [])
    shots = _normalize_shots(raw_shots, state)

    return {
        "shots": shots,
        "current_step": "generate_storyboard",
    }


def _normalize_shots(raw_shots: list, state: AgentState) -> list[dict]:
    project_id = state["project_id"]
    characters = state.get("characters", [])
    default_character = characters[0]["name"] if characters else "主角"
    scenes = state.get("script_scenes", [])
    source = raw_shots if raw_shots else _fallback_shots(scenes, default_character)

    shots: list[dict] = []
    for i, item in enumerate(source[:12]):
        dialogue = item.get("dialogue", "")
        if isinstance(dialogue, list):
            dialogue = dialogue[0].get("line", "") if dialogue else ""
        characters_in_scene = item.get("characters_in_scene") or [default_character]
        shots.append(
            {
                "shot_id": item.get("shot_id") or f"{project_id}_shot_{i + 1:04d}",
                "shot_type": item.get("shot_type") or item.get("camera_suggestion") or "medium",
                "scene_description": item.get("scene_description") or item.get("actions") or "角色推进剧情",
                "characters_in_scene": characters_in_scene,
                "character_action": item.get("character_action") or item.get("actions") or "",
                "dialogue": dialogue,
                "camera_angle": _normalize_camera_angle(item.get("camera_angle", "正面")),
                "camera_movement": item.get("camera_movement", "静止"),
                "emotion": item.get("emotion", "neutral"),
                "duration": float(item.get("duration") or 3.0),
                "transition": item.get("transition", "cut"),
                "image_path": item.get("image_path", ""),
                "audio_path": item.get("audio_path", ""),
                "status": item.get("status", "pending"),
                "confirmed": bool(item.get("confirmed", False)),
                "version": int(item.get("version", 1)),
                "seed": int(item.get("seed", 42 + i)),
                "visual_notes": item.get("visual_notes", ""),
            }
        )
    return shots


def _fallback_shots(scenes: list[dict], default_character: str) -> list[dict]:
    if not scenes:
        scenes = [{"actions": "主角站在窗边，故事开始", "emotion": "neutral", "dialogue": []}]

    shots: list[dict] = []
    shot_types = ["wide", "medium", "close-up"]
    for index, scene in enumerate(scenes[:5]):
        dialogue = scene.get("dialogue") or []
        line = dialogue[0].get("line", "") if isinstance(dialogue, list) and dialogue else ""
        shots.append(
            {
                "shot_type": shot_types[index % len(shot_types)],
                "scene_description": scene.get("actions") or scene.get("description") or "故事场景中的关键瞬间",
                "characters_in_scene": scene.get("characters_in_scene") or [default_character],
                "character_action": scene.get("actions", ""),
                "dialogue": line,
                "camera_angle": "正面",
                "camera_movement": "缓慢推进" if index % 2 else "静止",
                "emotion": scene.get("emotion", "neutral"),
                "duration": 3.0 + (index % 2),
                "transition": "cut",
                "visual_notes": "本地降级生成，可在右侧继续细化",
            }
        )
    return shots


def _normalize_camera_angle(value: str) -> str:
    aliases = {
        "front": "正面",
        "side": "侧面",
        "overhead": "俯视",
        "high": "俯视",
        "low": "仰视",
        "正面": "正面",
        "侧面": "侧面",
        "俯视": "俯视",
        "仰视": "仰视",
    }
    return aliases.get(value, "正面")


def _load_system_prompt() -> str:
    return "你是专业漫剧分镜师。根据剧本场景输出可执行分镜 JSON，不要输出 Markdown。"


def _build_task_prompt(script_scenes: list, characters: list, style: str, platform: str, target_duration: int) -> str:
    return f"""
剧本场景：
{json.dumps(script_scenes, ensure_ascii=False, indent=2)}

角色：
{json.dumps(characters, ensure_ascii=False, indent=2)}

风格：{style}
平台：{platform}
目标时长：{target_duration} 秒
输出 JSON：
{{
  "shots": [
    {{
      "shot_type": "wide/medium/close-up/extreme_close",
      "scene_description": "画面描述",
      "characters_in_scene": ["角色名"],
      "character_action": "动作",
      "dialogue": "台词",
      "camera_angle": "正面/侧面/俯视/仰视",
      "camera_movement": "静止/缓慢推进/平移/跟随",
      "emotion": "neutral/happy/shy/sad/angry/surprised",
      "duration": 3.5,
      "transition": "cut/fade/dissolve",
      "visual_notes": "画面注意事项"
    }}
  ]
}}
"""
