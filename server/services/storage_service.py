import os
import shutil
from pathlib import Path
from config import settings


class StorageService:
    """文件存储服务"""

    def __init__(self):
        self.base_dir = settings.OUTPUT_DIR

    def get_project_dir(self, project_id: str) -> Path:
        project_dir = self.base_dir / "projects" / project_id
        project_dir.mkdir(parents=True, exist_ok=True)
        return project_dir

    def get_shots_dir(self, project_id: str) -> Path:
        shots_dir = self.get_project_dir(project_id) / "shots"
        shots_dir.mkdir(parents=True, exist_ok=True)
        return shots_dir

    def get_audio_dir(self, project_id: str) -> Path:
        audio_dir = self.get_project_dir(project_id) / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)
        return audio_dir

    def get_output_dir(self, project_id: str) -> Path:
        output_dir = self.get_project_dir(project_id) / "output"
        output_dir.mkdir(parents=True, exist_ok=True)
        return output_dir

    def save_file(self, project_id: str, sub_dir: str, filename: str, content: bytes) -> str:
        dir_path = self.get_project_dir(project_id) / sub_dir
        dir_path.mkdir(parents=True, exist_ok=True)
        file_path = dir_path / filename
        with open(file_path, "wb") as f:
            f.write(content)
        return str(file_path)

    def delete_file(self, file_path: str) -> bool:
        try:
            Path(file_path).unlink(missing_ok=True)
            return True
        except Exception:
            return False

    def get_relative_url(self, file_path: str) -> str:
        """将文件路径转换为可访问的 URL 路径"""
        try:
            rel = Path(file_path).relative_to(self.base_dir)
            return f"/output/{rel.as_posix()}"
        except ValueError:
            return file_path
