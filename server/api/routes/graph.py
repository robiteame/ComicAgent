from fastapi import APIRouter

router = APIRouter(prefix="/api/graph", tags=["graph"])


@router.get("/structure")
async def get_graph_structure():
    """Return the Agent pipeline structure for frontend visualization."""
    nodes = [
        {"id": "start", "label": "开始", "type": "input", "description": "流水线入口"},
        {"id": "generate_script", "label": "剧本生成", "type": "process", "description": "Agent 自动生成完整漫剧剧本"},
        {"id": "parse_script", "label": "剧本解析", "type": "process", "description": "解析人物、场景、对白和情绪"},
        {"id": "generate_storyboard", "label": "分镜拆解", "type": "process", "description": "生成规范分镜列表"},
        {"id": "generate_reference_images", "label": "参考画面", "type": "process", "description": "为每个分镜生成参考画面"},
        {"id": "wait_storyboard_confirm", "label": "分镜确认", "type": "condition", "description": "用户确认或微调分镜"},
        {"id": "generate_images", "label": "画面渲染", "type": "process", "description": "渲染定稿镜头画面"},
        {"id": "generate_voice", "label": "配音合成", "type": "process", "description": "为角色对白生成音频"},
        {"id": "compose_video", "label": "视频合成", "type": "process", "description": "拼接完整漫剧视频"},
        {"id": "quality_check", "label": "质量校验", "type": "condition", "description": "校验最终结果完整性"},
        {"id": "end", "label": "完成", "type": "output", "description": "输出可播放成片"},
    ]

    edges = [
        {"source": "start", "target": "generate_script", "label": ""},
        {"source": "generate_script", "target": "parse_script", "label": ""},
        {"source": "parse_script", "target": "generate_storyboard", "label": ""},
        {"source": "generate_storyboard", "target": "generate_reference_images", "label": ""},
        {"source": "generate_reference_images", "target": "wait_storyboard_confirm", "label": "待确认"},
        {"source": "wait_storyboard_confirm", "target": "generate_images", "label": "已确认"},
        {"source": "generate_images", "target": "generate_voice", "label": ""},
        {"source": "generate_voice", "target": "compose_video", "label": ""},
        {"source": "compose_video", "target": "quality_check", "label": ""},
        {"source": "quality_check", "target": "end", "label": "通过"},
    ]

    return {"nodes": nodes, "edges": edges}
