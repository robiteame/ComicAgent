import base64
import mimetypes
from pathlib import Path

from PIL import Image, ImageFilter, ImageOps

from config import settings
from services.security import existing_file


class ReferenceAssetService:
    """Prepare persisted visual references for model payloads and continuity controls."""

    def __init__(self):
        self.output_dir = settings.OUTPUT_DIR / "projects"

    def to_image_url(self, path_or_url: str) -> str:
        value = str(path_or_url or "").strip()
        if not value:
            return ""
        if value.startswith(("http://", "https://", "data:image/")):
            return value
        path = existing_file(
            value,
            minimum_size=1,
            allowed_roots=(settings.OUTPUT_DIR, settings.ASSETS_DIR, settings.DATA_DIR),
        )
        if path is None:
            return ""
        mime = mimetypes.guess_type(path.name)[0] or "image/png"
        # These references must be embedded in an API payload, so keep the
        # unavoidable in-memory base64 conversion tightly bounded.
        if path.stat().st_size > settings.MAX_INLINE_REFERENCE_BYTES:
            return ""
        data = base64.b64encode(path.read_bytes()).decode("ascii")
        return f"data:{mime};base64,{data}"

    def materialize_continuity_controls(
        self,
        project_id: str,
        shot_id: str,
        source_path: str,
        enabled: bool,
    ) -> dict[str, str]:
        if not enabled or not source_path:
            return {}
        source = existing_file(
            source_path,
            minimum_size=1,
            allowed_roots=(settings.OUTPUT_DIR, settings.ASSETS_DIR, settings.DATA_DIR),
        )
        if source is None:
            return {}

        control_dir = self.output_dir / project_id / "controls"
        control_dir.mkdir(parents=True, exist_ok=True)
        safe_name = "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in shot_id) or "shot"
        pose_path = control_dir / f"{safe_name}_openpose_ref.png"
        depth_path = control_dir / f"{safe_name}_depth_ref.png"

        with Image.open(source) as image:
            rgb = image.convert("RGB")
            width, height = rgb.size
            if max(width, height) > 1024:
                rgb.thumbnail((1024, 1024))

            gray = ImageOps.grayscale(rgb)
            edge = gray.filter(ImageFilter.FIND_EDGES)
            edge = ImageOps.autocontrast(edge)
            pose = edge.point(lambda value: 255 if value > 36 else 0)
            pose.save(pose_path)

            depth = ImageOps.autocontrast(gray.filter(ImageFilter.GaussianBlur(radius=6)))
            depth.save(depth_path)

        return {
            "pose_reference_path": str(pose_path),
            "depth_reference_path": str(depth_path),
        }
