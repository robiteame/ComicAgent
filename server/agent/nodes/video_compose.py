from agent.state import AgentState
from services.ffmpeg_service import FFmpegService

ffmpeg_service = FFmpegService()


async def run(state: AgentState) -> dict:
    """Compose all rendered shots into a complete video."""

    shots = state.get("shots", [])
    output_format = state.get("output_format", "9:16")
    resolution = state.get("resolution", "1080p")
    project_id = state["project_id"]

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
