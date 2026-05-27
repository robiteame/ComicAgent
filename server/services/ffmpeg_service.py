import asyncio
from pathlib import Path

from config import settings


class FFmpegService:
    """Render shot images and optional audio into a short MP4."""

    def __init__(self):
        self.output_dir = settings.OUTPUT_DIR / "projects"
        self.fps = settings.DEFAULT_FPS

    async def compose_video(
        self,
        shots: list[dict],
        output_format: str = "9:16",
        resolution: str = "1080p",
        project_id: str = "",
    ) -> str:
        video_dir = self.output_dir / project_id / "output"
        video_dir.mkdir(parents=True, exist_ok=True)
        width, height = self._get_resolution(resolution, output_format)

        clip_paths: list[Path] = []
        for index, shot in enumerate(shots):
            if not shot.get("image_path"):
                continue
            clip_paths.append(await self._render_shot_clip(shot, width, height, index, video_dir))

        if not clip_paths:
            raise ValueError("没有可渲染的镜头图片")

        final_path = await self._concat_clips(clip_paths, video_dir)
        return str(final_path)

    async def _render_shot_clip(self, shot: dict, width: int, height: int, index: int, output_dir: Path) -> Path:
        clip_path = output_dir / f"clip_{index:04d}.mp4"
        duration = max(0.5, float(shot.get("duration") or 3.0))
        frames = max(1, int(duration * self.fps))
        image_path = str(shot["image_path"])
        zoom = self._zoom_filter(shot.get("shot_type", "medium"), width, height, frames)

        audio_path = Path(shot["audio_path"]) if shot.get("audio_path") else None
        if audio_path and audio_path.exists():
            audio_input = ["-i", str(audio_path)]
            audio_filter = ["-af", f"apad=pad_dur={duration}"]
        else:
            audio_input = ["-f", "lavfi", "-t", str(duration), "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"]
            audio_filter = []

        await self._run(
            [
                "ffmpeg",
                "-y",
                "-loop",
                "1",
                "-i",
                image_path,
                *audio_input,
                "-vf",
                zoom,
                "-t",
                str(duration),
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                *audio_filter,
                "-shortest",
                str(clip_path),
            ]
        )
        return clip_path

    async def _concat_clips(self, clip_paths: list[Path], output_dir: Path) -> Path:
        concat_path = output_dir / "final.mp4"
        inputs: list[str] = []
        for path in clip_paths:
            inputs.extend(["-i", str(path)])

        audio_filters = []
        concat_inputs = []
        for index in range(len(clip_paths)):
            audio_filters.append(f"[{index}:a:0]aresample=44100,aformat=channel_layouts=stereo[a{index}]")
            concat_inputs.append(f"[{index}:v:0][a{index}]")

        filter_complex = ";".join(audio_filters)
        filter_complex += ";" + "".join(concat_inputs)
        filter_complex += f"concat=n={len(clip_paths)}:v=1:a=1[v][a]"
        await self._run(
            [
                "ffmpeg",
                "-y",
                *inputs,
                "-filter_complex",
                filter_complex,
                "-map",
                "[v]",
                "-map",
                "[a]",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-movflags",
                "+faststart",
                str(concat_path),
            ]
        )
        return concat_path

    def _zoom_filter(self, shot_type: str, width: int, height: int, frames: int) -> str:
        if shot_type == "wide":
            zoom = "min(zoom+0.001,1.25)"
        elif shot_type in {"close-up", "extreme_close"}:
            zoom = "1.35"
        else:
            zoom = "1.10"
        return (
            f"scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},"
            f"zoompan=z='{zoom}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"d={frames}:s={width}x{height}:fps={self.fps}"
        )

    def _get_resolution(self, resolution: str, fmt: str) -> tuple[int, int]:
        sizes = {"720p": 720, "1080p": 1080, "2k": 1440, "4k": 2160}
        height = sizes.get(resolution, 1080)
        ratio = {"9:16": 9 / 16, "16:9": 16 / 9, "1:1": 1}.get(fmt, 9 / 16)
        width = int(height * ratio)
        return width - width % 2, height - height % 2

    async def _run(self, args: list[str]) -> None:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            message = stderr.decode("utf-8", errors="ignore")[-2000:]
            raise RuntimeError(f"FFmpeg 执行失败: {message}")
