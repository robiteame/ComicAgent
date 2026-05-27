import asyncio
import json
import os
import traceback

import aiofiles
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from agent.nodes import image_gen, script_parser, storyboard_gen
from api.websocket import ws_manager
from config import settings
from db import SessionLocal
from models import Character as CharacterModel
from models import Project, Shot as ShotModel
from services.llm_service import LLMService

router = APIRouter(prefix="/api/script", tags=["script"])

_background_tasks: set[asyncio.Task] = set()
llm_service = LLMService()


class ScriptGenerateRequest(BaseModel):
    project_id: str | None = None
    prompt: str = "校园成长短剧"
    style: str = "anime"
    genre: str = "原创短剧"
    target_duration: int = 45
    characters_hint: str = ""


class ScriptParseRequest(BaseModel):
    project_id: str
    user_input: str
    input_type: str = "text"
    style: str = "anime"
    output_format: str = "9:16"
    resolution: str = "1080p"
    platform: str = "douyin"
    target_duration: int = 45


@router.post("/generate")
async def generate_script(data: ScriptGenerateRequest):
    script = await _generate_script_text(data)
    return {
        "project_id": data.project_id,
        "title": _script_title(script),
        "script": script,
        "style": data.style,
        "genre": data.genre,
        "target_duration": data.target_duration,
    }


@router.post("/parse")
async def parse_script(data: ScriptParseRequest):
    if not data.user_input.strip():
        raise HTTPException(status_code=400, detail="请输入剧本内容")
    task = asyncio.create_task(_run_storyboard_phase(data.project_id, _initial_state(data.model_dump())))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return {"status": "started", "project_id": data.project_id}


@router.post("/upload")
async def upload_script(
    project_id: str = Form(...),
    file: UploadFile = File(...),
    style: str = Form("anime"),
    output_format: str = Form("9:16"),
    resolution: str = Form("1080p"),
    platform: str = Form("douyin"),
):
    upload_dir = settings.DATA_DIR / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)

    file_ext = os.path.splitext(file.filename or "script.txt")[1] or ".txt"
    file_path = upload_dir / f"{project_id}{file_ext}"
    async with aiofiles.open(file_path, "wb") as f:
        await f.write(await file.read())

    if file_ext.lower() == ".docx":
        from docx import Document

        doc = Document(str(file_path))
        user_input = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    else:
        async with aiofiles.open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            user_input = await f.read()

    payload = {
        "project_id": project_id,
        "user_input": user_input,
        "input_type": "file",
        "uploaded_file_path": str(file_path),
        "file_type": file_ext.lstrip("."),
        "style": style,
        "output_format": output_format,
        "resolution": resolution,
        "platform": platform,
        "target_duration": 45,
    }
    task = asyncio.create_task(_run_storyboard_phase(project_id, _initial_state(payload)))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return {"status": "started", "project_id": project_id, "file": file.filename}


async def _generate_script_text(data: ScriptGenerateRequest) -> str:
    if llm_service.available:
        try:
            return await llm_service.call(
                "你是漫剧编剧。请输出完整中文漫剧剧本，包含标题、人物、场景、动作、对白和情绪，不要输出解释。",
                f"""
创作方向：{data.prompt}
类型：{data.genre}
画风：{data.style}
目标时长：{data.target_duration} 秒
人物提示：{data.characters_hint or "自行设计 1 到 3 名角色"}

请用清晰结构输出：标题、人物、场景一、动作、对白、情绪、场景二……
""",
                temperature=0.75,
            )
        except Exception:
            pass

    lead = data.characters_hint.strip() or "林夏，敏感但行动力很强的年轻创作者"
    return f"""标题：{data.prompt}的一天
人物：
{lead}
阿澈，冷静可靠，擅长把混乱想法整理成计划

场景一：清晨的共享办公室
动作：林夏把一叠手稿摊开，屏幕上停着未完成的分镜草稿。阳光从百叶窗落在桌面，她深吸一口气。
对白：林夏：“今天一定要把它做成真正的漫剧。”
情绪：期待、紧张

场景二：窗边白板前
动作：阿澈走近白板，把故事拆成几个镜头。林夏一边听一边补充角色表情，两人的节奏逐渐合拍。
对白：阿澈：“先让观众看见她的目标，再让冲突出现在第二个镜头。”
对白：林夏：“那第二个镜头给她一个迟疑的特写。”
情绪：专注、协作

场景三：傍晚的屏幕前
动作：第一版视频终于合成完成。林夏点下播放键，画面、对白和节奏连在一起，她露出释然的笑。
对白：林夏：“原来故事真的可以这样长出来。”
情绪：释然、惊喜"""


def _initial_state(data: dict) -> dict:
    return {
        "project_id": data["project_id"],
        "user_input": data.get("user_input", ""),
        "input_type": data.get("input_type", "text"),
        "uploaded_file_path": data.get("uploaded_file_path", ""),
        "file_type": data.get("file_type", ""),
        "script_title": "",
        "genre": "",
        "style_suggestion": data.get("style", "anime"),
        "characters": [],
        "raw_script": "",
        "script_scenes": [],
        "logic_issues": [],
        "shots": [],
        "style": data.get("style", "anime"),
        "style_params": {},
        "output_format": data.get("output_format", "9:16"),
        "resolution": data.get("resolution", "1080p"),
        "platform": data.get("platform", "douyin"),
        "target_duration": data.get("target_duration", 45),
        "video_path": "",
        "current_step": "",
        "errors": [],
        "human_feedback": "",
        "needs_human_review": False,
        "storyboard_confirmed": False,
        "rag_context": [],
        "narrative_context": {},
        "generation_preferences": {},
    }


async def _run_storyboard_phase(project_id: str, state: dict):
    db = SessionLocal()
    try:
        await _progress(project_id, "parse_script", 10, "正在解析剧本")
        state.update(await script_parser.run(state))

        await _progress(project_id, "generate_storyboard", 32, "正在生成分镜列表")
        state.update(await storyboard_gen.run(state))

        await _progress(project_id, "generate_reference_images", 46, "正在生成分镜参考画面")
        state.update(await image_gen.run(state))

        _persist_phase1(db, project_id, state)
        await _progress(project_id, "wait_storyboard_confirm", 55, "分镜和参考画面已生成")
        await ws_manager.send_to_project(
            project_id,
            {
                "type": "complete",
                "project_id": project_id,
                "shots": state.get("shots", []),
                "video_path": "",
            },
        )
    except Exception as exc:
        db.rollback()
        _mark_project_error(db, project_id)
        await ws_manager.send_to_project(
            project_id,
            {"type": "error", "message": f"剧本与分镜生成失败: {exc}\n{traceback.format_exc()}"},
        )
    finally:
        db.close()


def _persist_phase1(db, project_id: str, state: dict) -> None:
    project = db.query(Project).filter(Project.id == project_id).first()
    if project:
        project.title = state.get("script_title") or _script_title(state.get("user_input", "")) or project.title
        project.genre = state.get("genre") or project.genre
        project.style = state.get("style") or project.style
        project.input_text = state.get("user_input", "")
        project.input_type = state.get("input_type", "text")
        project.output_format = state.get("output_format", project.output_format)
        project.resolution = state.get("resolution", project.resolution)
        project.platform = state.get("platform", project.platform)
        project.status = "storyboard_ready"

    db.query(CharacterModel).filter(CharacterModel.project_id == project_id).delete()
    for index, char in enumerate(state.get("characters", [])):
        db.add(
            CharacterModel(
                id=f"{project_id}_char_{index + 1:04d}",
                project_id=project_id,
                name=char["name"],
                appearance=json.dumps(char.get("appearance", {}), ensure_ascii=False),
                personality=char.get("personality", ""),
                visual_prompt=char.get("visual_prompt", ""),
                negative_prompt=char.get("negative_prompt", ""),
                voice_id=char.get("voice_id", ""),
                emotion_variants=json.dumps(char.get("emotion_variants", {}), ensure_ascii=False),
                key_features=json.dumps(char.get("key_features", []), ensure_ascii=False),
                default_outfit=char.get("appearance", {}).get("default_outfit", ""),
                seed=str(char.get("seed", 42)),
            )
        )

    db.query(ShotModel).filter(ShotModel.project_id == project_id).delete()
    for index, shot in enumerate(state.get("shots", [])):
        db.add(_shot_model(project_id, shot, index + 1))

    db.commit()


def _shot_model(project_id: str, shot: dict, sequence: int) -> ShotModel:
    return ShotModel(
        id=shot.get("shot_id") or f"{project_id}_shot_{sequence:04d}",
        project_id=project_id,
        sequence=sequence,
        shot_type=shot.get("shot_type", "medium"),
        scene_description=shot.get("scene_description", ""),
        character_action=shot.get("character_action", ""),
        dialogue=shot.get("dialogue", ""),
        camera_angle=shot.get("camera_angle", "正面"),
        camera_movement=shot.get("camera_movement", "静止"),
        duration=shot.get("duration", 3.0),
        emotion=shot.get("emotion", "neutral"),
        transition=shot.get("transition", "cut"),
        image_path=shot.get("image_path", ""),
        audio_path=shot.get("audio_path", ""),
        status=shot.get("status", "done"),
        version=shot.get("version", 1),
        confirmed=shot.get("confirmed", False),
        characters_in_scene=json.dumps(shot.get("characters_in_scene", []), ensure_ascii=False),
        visual_notes=shot.get("visual_notes", ""),
    )


async def _progress(project_id: str, step: str, progress: int, message: str) -> None:
    await ws_manager.send_to_project(project_id, {"type": "progress", "step": step, "progress": progress, "message": message})


def _mark_project_error(db, project_id: str) -> None:
    project = db.query(Project).filter(Project.id == project_id).first()
    if project:
        project.status = "error"
        db.commit()


def _script_title(script: str) -> str:
    for line in script.splitlines():
        clean = line.strip()
        if clean.startswith("标题"):
            return clean.replace("标题：", "").replace("标题:", "").strip()[:30] or "未命名项目"
    return (script.strip().splitlines()[0] if script.strip() else "未命名项目")[:30]
