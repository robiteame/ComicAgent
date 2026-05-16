import json
import uuid
from agent.state import AgentState
from services.llm_service import LLMService
from rag.rag_service import RAGService
from memory.project_memory import ProjectMemory

llm_service = LLMService()
rag_service = RAGService()
project_memory = ProjectMemory()


async def run(state: AgentState) -> dict:
    """脚本解析节点：解析用户输入，提取人物、场景、台词等结构化数据"""

    project_id = state["project_id"]
    user_input = state["user_input"]
    input_type = state.get("input_type", "text")

    # 如果是文件导入，先进行 RAG ingest
    rag_context = []
    if input_type == "file" and state.get("uploaded_file_path"):
        ingest_result = await rag_service.ingest_document(
            project_id=project_id,
            file_path=state["uploaded_file_path"],
            file_type=state.get("file_type", "txt"),
            doc_type="novel",
        )
        # 检索相关上下文
        rag_context = await rag_service.query_context(
            project_id=project_id,
            query="主要人物外貌性格、场景描述、剧情概要",
            n_results=10,
        )

    # 构建解析提示词
    system_prompt = _load_system_prompt()
    task_prompt = _build_task_prompt(user_input, rag_context)

    # 调用 LLM 解析
    result = await llm_service.call_json(system_prompt, task_prompt)

    # 生成角色卡片
    characters = []
    for char in result.get("characters", []):
        characters.append(
            {
                "name": char["name"],
                "appearance": char.get("appearance", {}),
                "personality": char.get("personality", ""),
                "visual_prompt": char.get("visual_prompt", ""),
                "negative_prompt": char.get("negative_prompt", ""),
                "voice_id": char.get("voice_type", ""),
                "key_features": char.get("appearance", {}).get("features", "").split(", ")
                if isinstance(char.get("appearance", {}).get("features"), str)
                else char.get("appearance", {}).get("features", []),
                "emotion_variants": {
                    "neutral": "calm expression, gentle smile",
                    "happy": "bright smile, sparkling eyes",
                    "shy": "looking away, faint blush",
                    "sad": "downcast eyes, slight frown",
                    "angry": "furrowed brows, sharp gaze",
                    "surprised": "wide eyes, raised eyebrows",
                },
                "seed": 42,
            }
        )

    # 保存到项目记忆
    project_memory.save_characters(project_id, characters)
    project_memory.save_narrative_context(
        project_id,
        {
            "script_scenes": result.get("script_scenes", []),
            "genre": result.get("genre", ""),
            "style_suggestion": result.get("style_suggestion", "anime"),
        },
    )

    return {
        "script_title": result.get("title", "未命名"),
        "genre": result.get("genre", ""),
        "style_suggestion": result.get("style_suggestion", "anime"),
        "characters": characters,
        "raw_script": json.dumps(result.get("script_scenes", []), ensure_ascii=False),
        "script_scenes": result.get("script_scenes", []),
        "logic_issues": result.get("logic_issues", []),
        "rag_context": rag_context,
        "current_step": "parse_script",
    }


def _load_system_prompt() -> str:
    return """你是一个资深的漫剧脚本分析师，拥有10年漫剧编导经验。

你的职责：
1. 深度解析用户输入（自然语言/小说/剧本），提取漫剧所需的全部结构化信息
2. 识别并标注每个角色的外貌、性格、情绪特征（用于后续AI图像生成）
3. 检测剧情逻辑问题（断层、OOC、矛盾），给出优化建议
4. 将文本拆分为可执行的场景单元

专业要求：
- 角色描述要具体到可视觉化的程度（发型、发色、瞳色、身材、标志性特征）
- 场景描述要包含空间关系、光线、氛围
- 情绪标注要精确，避免笼统
- 台词要符合角色性格"""


def _build_task_prompt(user_input: str, rag_context: list[str]) -> str:
    context_section = ""
    if rag_context:
        context_section = "\n\n参考内容（来自上传的剧本/小说）：\n" + "\n---\n".join(rag_context)

    return f"""请分析以下输入，输出严格的JSON格式：

{user_input}{context_section}

输出格式：
{{
    "title": "剧名",
    "genre": "类型（甜宠/悬疑/古风/都市等）",
    "style_suggestion": "建议风格（anime/chinese/chibi/realistic）",
    "characters": [
        {{
            "name": "角色名",
            "appearance": {{
                "hair": "发型、发色",
                "eyes": "瞳色、眼型",
                "body": "身材描述",
                "features": "标志性特征（如泪痣、虎牙）",
                "default_outfit": "默认服装"
            }},
            "personality": "性格描述",
            "visual_prompt": "英文AI绘画prompt，用于生成该角色",
            "negative_prompt": "英文negative prompt，排除不符合的特征",
            "voice_type": "建议音色（少年/少女/御姐/大叔等）"
        }}
    ],
    "scenes": [
        {{
            "location": "场景地点",
            "description": "详细场景描述",
            "atmosphere": "氛围关键词",
            "lighting": "光线描述",
            "props": ["场景中的重要道具"]
        }}
    ],
    "script_scenes": [
        {{
            "scene_number": 1,
            "location": "场景",
            "characters_in_scene": ["角色A"],
            "actions": "详细动作描述",
            "dialogue": [
                {{"character": "角色A", "line": "台词", "emotion": "说话时的情绪", "action": "说话时的动作"}}
            ],
            "emotion": "场景整体情绪基调",
            "camera_suggestion": "建议镜头类型"
        }}
    ],
    "logic_issues": [
        {{
            "type": "断层/OOC/矛盾",
            "description": "问题描述",
            "suggestion": "优化建议"
        }}
    ]
}}"""
