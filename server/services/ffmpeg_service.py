import asyncio
import time
from pathlib import Path
from config import settings


class FFmpegService:
    """FFmpeg 视频渲染服务"""

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
        """将所有镜头合成为完整视频"""

        video_dir = self.output_dir / project_id / "output"
        video_dir.mkdir(parents=True, exist_ok=True)
        w, h = self._get_resolution(resolution, output_format)

        # 1. 为每个镜头生成视频片段
        clip_paths = []
        for i, shot in enumerate(shots):
            if not shot.get("image_path"):
                continue
            clip_path = await self._render_shot_clip(shot, w, h, i, video_dir)
            clip_paths.append(clip_path)

        if not clip_paths:
            raise ValueError("没有有效的镜头片段")

        # 2. 拼接所有片段
        concat_path = await self._concat_clips(clip_paths, video_dir)

        # 3. 混入配音
        final_path = await self._mix_audio(concat_path, shots, video_dir)

        return str(final_path)

    async def _render_shot_clip(
        self, shot: dict, w: int, h: int, index: int, output_dir: Path
    ) -> Path:
        """渲染单个镜头为视频片段（Ken Burns 效果）"""

        clip_path = output_dir / f"clip_{index:04d}.mp4"
        duration = shot.get("duration", 3.0)
        image_path = shot["image_path"]
        fps = self.fps

        # 构建 FFmpeg 命令
        shot_type = shot.get("shot_type", "medium")

        if shot_type == "wide":
            # 全景：缓慢推进
            zoom_filter = f"zoompan=z='min(zoom+0.001,1.3)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={int(duration * fps)}:s={w}x{h}:fps={fps}"
        elif shot_type in ("close-up", "extreme_close"):
            # 特写：轻微抖动 + 聚焦
            zoom_filter = f"zoompan=z='1.5':x='iw/2-(iw/zoom/2)+sin(n*0.1)*5':y='ih/2-(ih/zoom/2)+cos(n*0.1)*5':d={int(duration * fps)}:s={w}x{h}:fps={fps}"
        else:
            # 中景：静止
            zoom_filter = f"zoompan=z='1.1':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={int(duration * fps)}:s={w}x{h}:fps={fps}"

        # 字幕滤镜
        subtitle_filter = ""
        if shot.get("dialogue"):
            dialogue = shot["dialogue"].replace("'", "'\\''").replace(":", "\\:")
            font_size = int(h * 0.04)
            subtitle_filter = f",drawtext=text='{dialogue}':fontsize={font_size}:fontcolor=white:borderw=2:bordercolor=black:x=(w-text_w)/2:y=h-text_h-30:font=Microsoft YaHei"

        cmd = (
            f'ffmpeg -y -loop 1 -i "{image_path}" '
            f'-vf "{zoom_filter}{subtitle_filter}" '
            f'-t {duration} -c:v libx264 -pix_fmt yuv420p '
            f'"{clip_path}"'
        )

        await self._run_cmd(cmd)
        return clip_path

    async def _concat_clips(self, clip_paths: list[Path], output_dir: Path) -> Path:
        """拼接所有镜头片段"""
        concat_path = output_dir / "concat.mp4"
        list_path = output_dir / "concat_list.txt"

        with open(list_path, "w", encoding="utf-8") as f:
            for p in clip_paths:
                f.write(f"file '{p}'\n")

        cmd = f'ffmpeg -y -f concat -safe 0 -i "{list_path}" -c copy "{concat_path}"'
        await self._run_cmd(cmd)
        return concat_path

    async def _mix_audio(
        self, video_path: Path, shots: list[dict], output_dir: Path
    ) -> Path:
        """混入配音音轨"""
        output_path = output_dir / "final.mp4"

        audio_clips = [s["audio_path"] for s in shots if s.get("audio_path")]
        if not audio_clips:
            # 无配音，直接复制
            import shutil

            shutil.copy2(video_path, output_path)
            return output_path

        # 拼接音频
        audio_concat = output_dir / "audio_full.wav"
        list_path = output_dir / "audio_list.txt"

        with open(list_path, "w", encoding="utf-8") as f:
            for p in audio_clips:
                f.write(f"file '{p}'\n")

        cmd = f'ffmpeg -y -f concat -safe 0 -i "{list_path}" -c:a aac "{audio_concat}"'
        await self._run_cmd(cmd)

        # 合并视频和音频
        cmd = f'ffmpeg -y -i "{video_path}" -i "{audio_concat}" -c:v copy -c:a aac -shortest "{output_path}"'
        await self._run_cmd(cmd)

        return output_path

    def _get_resolution(self, resolution: str, fmt: str) -> tuple[int, int]:
        """根据分辨率和画幅返回宽高"""
        sizes = {"720p": 720, "1080p": 1080, "4k": 2160}
        h = sizes.get(resolution, 1080)

        ratios = {"9:16": 9 / 16, "16:9": 16 / 9, "1:1": 1}
        ratio = ratios.get(fmt, 9 / 16)
        w = int(h * ratio)
        w = w - (w % 2)
        h = h - (h % 2)
        return w, h

    async def _run_cmd(self, cmd: str):
        """执行 shell 命令"""
        proc = await asyncio.create_subprocess_shell(
            cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"FFmpeg 执行失败: {stderr.decode()}")
