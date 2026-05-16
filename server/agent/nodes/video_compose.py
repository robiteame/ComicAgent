from agent.state import AgentState
from services.ffmpeg_service import FFmpegService

ffmpeg_service = FFmpegService()


async def run(state: AgentState) -> dict:
    """视频合成节点：将所有镜头合成为完整视频"""

    shots = state.get("shots", [])
    output_format = state.get("output_format", "9:16")
    resolution = state.get("resolution", "1080p")
    project_id = state["project_id"]

    try:
        video_path = await ffmpeg_service.compose_video(
            shots=shots,
            output_format=output_format,
            resolution=resolution,
            project_id=project_id,
        )
        return {
            "video_path": video_path,
            "current_step": "compose_video",
        }
    except Exception as e:
        return {
            "video_path": "",
            "errors": [f"视频合成失败: {str(e)}"],
            "current_step": "compose_video",
        }
