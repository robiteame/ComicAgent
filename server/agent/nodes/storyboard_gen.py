import json
import uuid
from agent.state import AgentState
from services.llm_service import LLMService

llm_service = LLMService()


async def run(state: AgentState) -> dict:
    """分镜生成节点：根据脚本场景生成分镜方案"""

    system_prompt = _load_system_prompt()
    task_prompt = _build_task_prompt(
        script_scenes=state.get("script_scenes", []),
        characters=state.get("characters", []),
        style=state.get("style", "anime"),
        platform=state.get("platform", "douyin"),
        target_duration=state.get("target_duration", 30),
    )

    result = await llm_service.call_json(system_prompt, task_prompt)

    # 构建镜头列表
    shots = []
    for i, shot_data in enumerate(result if isinstance(result, list) else result.get("shots", [])):
        shot = {
            "shot_id": f"shot_{i+1:04d}",
            "shot_type": shot_data.get("shot_type", "medium"),
            "scene_description": shot_data.get("scene_description", ""),
            "characters_in_scene": shot_data.get("characters_in_scene", []),
            "character_action": shot_data.get("character_action", ""),
            "dialogue": shot_data.get("dialogue", ""),
            "camera_angle": shot_data.get("camera_angle", "正面"),
            "camera_movement": shot_data.get("camera_movement", "静止"),
            "emotion": shot_data.get("emotion", "neutral"),
            "duration": shot_data.get("duration", 3.0),
            "transition": shot_data.get("transition", "cut"),
            "image_path": "",
            "audio_path": "",
            "status": "pending",
            "visual_notes": shot_data.get("visual_notes", ""),
        }
        shots.append(shot)

    return {
        "shots": shots,
        "current_step": "generate_storyboard",
    }


def _load_system_prompt() -> str:
    return """你是一个专业的漫剧分镜师，精通镜头语言和漫剧节奏把控。

分镜原则：
1. 镜头类型选择要符合情绪表达：
   - 全景(wide)：交代环境、展示空间关系、转场
   - 中景(medium)：对话、日常互动、展示上半身动作
   - 近景(close-up)：表情特写、情绪高潮、关键动作
   - 特写(extreme_close)：眼神、手部细节、极致情绪
2. 镜头节奏要符合剧情：
   - 甜宠/日常：中景为主，节奏舒缓，每镜头3-5秒
   - 冲突/紧张：特写+快速切换，每镜头1-3秒
   - 转场/铺垫：全景，缓慢推进，3-6秒
3. 镜头之间要有视觉连贯性，避免跳跃
4. 总镜头数要适配目标时长"""


def _build_task_prompt(
    script_scenes: list, characters: list, style: str, platform: str, target_duration: int
) -> str:
    characters_summary = []
    for c in characters:
        characters_summary.append(
            f"- {c['name']}: {c.get('personality', '')} | 外貌: {c.get('visual_prompt', '')}"
        )

    scenes_text = json.dumps(script_scenes, ensure_ascii=False, indent=2)

    return f"""基于以下脚本场景，生成分镜方案：

脚本场景：
{scenes_text}

角色信息：
{chr(10).join(characters_summary)}

风格要求：{style}
目标平台：{platform}
目标时长：{target_duration}秒

请输出JSON格式：
{{
    "shots": [
        {{
            "shot_type": "wide/medium/close-up/extreme_close",
            "scene_description": "画面描述（英文，用于AI图像生成）",
            "characters_in_scene": ["角色A"],
            "character_action": "角色动作描述",
            "dialogue": "台词（如有）",
            "camera_angle": "正面/侧面/俯视/仰视",
            "camera_movement": "静止/缓慢推进/平移/跟随",
            "emotion": "画面情绪",
            "duration": 3.5,
            "transition": "fade/cut/dissolve/flash",
            "visual_notes": "画面注意事项"
        }}
    ]
}}"""
