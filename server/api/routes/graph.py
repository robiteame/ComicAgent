from fastapi import APIRouter

router = APIRouter(prefix="/api/graph", tags=["graph"])


@router.get("/structure")
async def get_graph_structure():
    """返回 LangGraph 流水线的图结构定义，供前端可视化渲染"""
    nodes = [
        {"id": "start", "label": "开始", "type": "input", "description": "流水线入口"},
        {"id": "parse_script", "label": "剧本解析", "type": "process", "description": "LLM 解析剧本文本，提取角色、场景、情节"},
        {"id": "generate_storyboard", "label": "分镜拆解", "type": "process", "description": "LLM 将场景拆解为具体镜头，规划景别与运镜"},
        {"id": "generate_images", "label": "画面渲染", "type": "process", "description": "Stability AI 生成每个镜头的画面"},
        {"id": "generate_voice", "label": "配音合成", "type": "process", "description": "Edge-TTS 为角色台词生成配音"},
        {"id": "compose_video", "label": "视频合成", "type": "process", "description": "FFmpeg 合成最终视频，添加字幕与转场"},
        {"id": "quality_check", "label": "质量校验", "type": "condition", "description": "校验画面质量与镜头完整性"},
        {"id": "human_review", "label": "人工审核", "type": "process", "description": "等待用户审核并提供反馈"},
        {"id": "shot_regeneration", "label": "镜头重生成", "type": "process", "description": "重新生成失败的镜头"},
        {"id": "end", "label": "完成", "type": "output", "description": "流水线结束，输出成片"},
    ]

    edges = [
        {"source": "start", "target": "parse_script", "label": ""},
        {"source": "parse_script", "target": "generate_storyboard", "label": ""},
        {"source": "generate_storyboard", "target": "generate_images", "label": ""},
        {"source": "generate_images", "target": "generate_voice", "label": ""},
        {"source": "generate_voice", "target": "compose_video", "label": ""},
        {"source": "compose_video", "target": "quality_check", "label": ""},
        {"source": "quality_check", "target": "end", "label": "通过"},
        {"source": "quality_check", "target": "shot_regeneration", "label": "镜头失败"},
        {"source": "quality_check", "target": "human_review", "label": "需审核"},
        {"source": "human_review", "target": "compose_video", "label": "反馈完成"},
        {"source": "shot_regeneration", "target": "quality_check", "label": "重新校验"},
    ]

    return {"nodes": nodes, "edges": edges}
