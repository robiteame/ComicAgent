from typing import TypedDict, Annotated, Literal
from operator import add


class CharacterCard(TypedDict):
    name: str
    appearance: dict  # {hair, eyes, body, features, default_outfit}
    personality: str
    visual_prompt: str
    negative_prompt: str
    voice_id: str
    key_features: list[str]
    emotion_variants: dict[str, str]  # emotion -> prompt fragment
    seed: int


class Shot(TypedDict):
    shot_id: str
    shot_type: Literal["wide", "medium", "close-up", "extreme_close"]
    scene_description: str
    characters_in_scene: list[str]
    character_action: str
    dialogue: str
    camera_angle: str  # 正面/侧面/俯视/仰视
    camera_movement: str  # 静止/缓慢推进/平移/跟随
    emotion: str
    duration: float
    transition: str  # fade/cut/dissolve/flash
    image_path: str
    audio_path: str
    confirmed: bool
    status: Literal["pending", "generating", "done", "failed", "needs_review"]
    version: int
    seed: int
    visual_notes: str


class StyleParams(TypedDict):
    style_id: str
    style_name: str
    prompt_prefix: str
    negative_prefix: str
    color_palette: dict
    camera_preferences: dict


class AgentState(TypedDict):
    # 项目标识
    project_id: str

    # 用户输入
    user_input: str
    input_type: Literal["text", "file", "ip"]
    uploaded_file_path: str
    file_type: str

    # 脚本解析结果
    script_title: str
    genre: str
    style_suggestion: str
    characters: list[CharacterCard]
    raw_script: str
    script_scenes: list[dict]
    logic_issues: list[dict]

    # 分镜
    shots: Annotated[list[Shot], add]

    # 风格
    style: str
    style_params: StyleParams

    # 渲染参数
    output_format: Literal["9:16", "16:9", "1:1"]
    resolution: str
    platform: Literal["douyin", "kuaishou", "bilibili", "custom"]
    target_duration: int  # 目标时长（秒）

    # 输出
    video_path: str

    # 流程控制
    current_step: str
    errors: Annotated[list[str], add]
    human_feedback: str
    needs_human_review: bool
    storyboard_confirmed: bool

    # 运行模式:auto = 经 LangGraph 端到端跑;manual = 由 api/routes 逐步触发(默认)
    mode: Literal["manual", "auto"]
    initial_state: dict  # 自动模式下传给阶段1 (_run_storyboard_phase) 的初始 state dict

    # 记忆上下文（从 RAG 和记忆系统注入）
    rag_context: list[str]
    narrative_context: dict  # 剧情上下文
    generation_preferences: dict  # 用户偏好
