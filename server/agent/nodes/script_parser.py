import json
import re

from agent.state import AgentState
from memory.project_memory import ProjectMemory
from rag.rag_service import RAGService
from services.llm_service import LLMService

llm_service = LLMService()
rag_service = RAGService()
project_memory = ProjectMemory()


async def run(state: AgentState) -> dict:
    """Parse free-form input into characters and script scenes."""
    if state.get("storyboard_confirmed") and state.get("characters"):
        return {"current_step": "parse_script"}

    project_id = state["project_id"]
    user_input = (state.get("user_input") or "").strip()
    rag_context: list[str] = []

    if state.get("input_type") == "file" and state.get("uploaded_file_path"):
        try:
            await rag_service.ingest_document(
                project_id=project_id,
                file_path=state["uploaded_file_path"],
                file_type=state.get("file_type", "txt"),
                doc_type="script",
            )
            rag_context = await rag_service.query_context(
                project_id=project_id,
                query="主要人物、场景、冲突、对白",
                n_results=8,
            )
        except Exception:
            rag_context = []

    result = None
    if llm_service.available and user_input:
        try:
            result = await llm_service.call_json(
                _load_system_prompt(),
                _build_task_prompt(user_input, rag_context),
                temperature=0.25,
            )
        except Exception:
            result = None

    if not result:
        result = _fallback_parse(user_input)

    characters = _normalize_characters(result.get("characters", []), user_input)
    script_scenes = _normalize_scenes(result.get("script_scenes") or result.get("scenes") or [], user_input, characters)

    project_memory.save_characters(project_id, characters)
    project_memory.save_narrative_context(
        project_id,
        {
            "script_scenes": script_scenes,
            "genre": result.get("genre", "原创短剧"),
            "style_suggestion": result.get("style_suggestion", state.get("style", "anime")),
        },
    )

    return {
        "script_title": result.get("title") or _guess_title(user_input),
        "genre": result.get("genre", "原创短剧"),
        "style_suggestion": result.get("style_suggestion", state.get("style", "anime")),
        "characters": characters,
        "raw_script": json.dumps(script_scenes, ensure_ascii=False),
        "script_scenes": script_scenes,
        "logic_issues": result.get("logic_issues", []),
        "rag_context": rag_context,
        "current_step": "parse_script",
    }


def _normalize_characters(raw: list, user_input: str) -> list[dict]:
    characters: list[dict] = []
    for index, item in enumerate(raw[:6]):
        name = str(item.get("name") or f"角色{index + 1}").strip()
        if not name:
            continue
        appearance = item.get("appearance") if isinstance(item.get("appearance"), dict) else {}
        features = appearance.get("features", [])
        if isinstance(features, str):
            features = [part.strip() for part in re.split(r"[,，、]", features) if part.strip()]
        characters.append(
            {
                "name": name,
                "appearance": appearance,
                "personality": item.get("personality", "性格鲜明，行动目标清晰"),
                "visual_prompt": item.get("visual_prompt") or f"{name}, expressive comic character, clean line art",
                "negative_prompt": item.get("negative_prompt", "low quality, blurry, watermark"),
                "voice_id": item.get("voice_type") or item.get("voice_id") or "少女",
                "key_features": features,
                "emotion_variants": {
                    "neutral": "calm expression",
                    "happy": "gentle smile",
                    "shy": "slight blush",
                    "sad": "downcast eyes",
                    "angry": "determined eyes",
                    "surprised": "wide eyes",
                },
                "seed": 42 + index,
            }
        )

    if characters:
        return characters

    names = re.findall(r"(?:人物|角色)[:：]\s*([^\n，。]+)", user_input)
    name = names[0].strip() if names else "主角"
    return [
        {
            "name": name,
            "appearance": {"features": ["清爽造型", "表情细腻"], "default_outfit": "日常服装"},
            "personality": "敏感而有行动力",
            "visual_prompt": f"{name}, modern Chinese comic character, clean office-light illustration",
            "negative_prompt": "low quality, blurry, watermark, extra fingers",
            "voice_id": "少女",
            "key_features": ["清爽造型", "表情细腻"],
            "emotion_variants": {
                "neutral": "calm expression",
                "happy": "gentle smile",
                "shy": "slight blush",
                "sad": "downcast eyes",
                "angry": "determined eyes",
                "surprised": "wide eyes",
            },
            "seed": 42,
        }
    ]


def _normalize_scenes(raw: list, user_input: str, characters: list[dict]) -> list[dict]:
    scenes: list[dict] = []
    for index, item in enumerate(raw[:8]):
        dialogue = item.get("dialogue", [])
        if isinstance(dialogue, str):
            dialogue = [{"character": characters[0]["name"], "line": dialogue, "emotion": "neutral", "action": ""}]
        scenes.append(
            {
                "scene_number": int(item.get("scene_number") or index + 1),
                "location": item.get("location") or "室内创作空间",
                "characters_in_scene": item.get("characters_in_scene") or [characters[0]["name"]],
                "actions": item.get("actions") or item.get("description") or "角色推进剧情",
                "dialogue": dialogue,
                "emotion": item.get("emotion") or "neutral",
                "camera_suggestion": item.get("camera_suggestion") or "medium",
            }
        )

    if scenes:
        return scenes

    chunks = [part.strip() for part in re.split(r"\n\s*\n|[。！？]\s*", user_input) if part.strip()]
    if not chunks:
        chunks = ["主角进入场景，故事开始推进"]
    return [
        {
            "scene_number": i + 1,
            "location": _guess_location(chunk),
            "characters_in_scene": [characters[0]["name"]],
            "actions": chunk[:120],
            "dialogue": _extract_dialogue(chunk, characters[0]["name"]),
            "emotion": _guess_emotion(chunk),
            "camera_suggestion": "medium",
        }
        for i, chunk in enumerate(chunks[:5])
    ]


def _fallback_parse(user_input: str) -> dict:
    return {
        "title": _guess_title(user_input),
        "genre": "原创短剧",
        "style_suggestion": "anime",
        "characters": [],
        "script_scenes": [],
        "logic_issues": [],
    }


def _guess_title(text: str) -> str:
    first = re.sub(r"\s+", "", text or "")[:14]
    return first or "未命名项目"


def _guess_location(text: str) -> str:
    match = re.search(r"(?:场景|地点)[:：]\s*([^\n，。]+)", text)
    return match.group(1).strip() if match else "故事场景"


def _extract_dialogue(text: str, character: str) -> list[dict]:
    lines = re.findall(r"[“\"']([^”\"']{2,80})[”\"']", text)
    return [{"character": character, "line": line, "emotion": _guess_emotion(line), "action": ""} for line in lines[:2]]


def _guess_emotion(text: str) -> str:
    if re.search(r"笑|开心|惊喜|甜", text):
        return "happy"
    if re.search(r"哭|难过|失落|雨|深夜", text):
        return "sad"
    if re.search(r"怒|冲突|争吵", text):
        return "angry"
    if re.search(r"突然|震惊|发现", text):
        return "surprised"
    return "neutral"


def _load_system_prompt() -> str:
    return (
        "你是资深漫剧编导。请把用户输入解析成角色、场景、对白和情绪，"
        "输出严格 JSON，不要输出 Markdown。"
    )


def _build_task_prompt(user_input: str, rag_context: list[str]) -> str:
    context = "\n\n参考内容：\n" + "\n---\n".join(rag_context) if rag_context else ""
    return f"""
请解析以下剧本或故事，输出 JSON：
{user_input}{context}

JSON 结构：
{{
  "title": "剧名",
  "genre": "类型",
  "style_suggestion": "anime/chinese/chibi/realistic",
  "characters": [
    {{
      "name": "角色名",
      "appearance": {{
        "hair": "发型发色",
        "eyes": "眼睛特征",
        "body": "身形",
        "features": "标志特征",
        "default_outfit": "默认服装"
      }},
      "personality": "性格",
      "visual_prompt": "English image prompt",
      "negative_prompt": "English negative prompt",
      "voice_type": "少女/少年/御姐/大叔/儿童/老人"
    }}
  ],
  "script_scenes": [
    {{
      "scene_number": 1,
      "location": "地点",
      "characters_in_scene": ["角色名"],
      "actions": "动作与剧情",
      "dialogue": [
        {{"character": "角色名", "line": "台词", "emotion": "neutral", "action": "说话动作"}}
      ],
      "emotion": "neutral/happy/shy/sad/angry/surprised",
      "camera_suggestion": "wide/medium/close-up/extreme_close"
    }}
  ],
  "logic_issues": []
}}
"""
