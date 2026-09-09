"""无密钥占位图适配器：protocol 非法或缺 key 时的安全兜底，保证离线全流程可跑通。"""

from __future__ import annotations

import re
import textwrap
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

from services.providers.base import BaseAdapter, ImageCapabilities, ImageRequest


class PlaceholderImageAdapter(BaseAdapter):
    capabilities = ImageCapabilities(reference_images=False, requires_credentials=False)

    async def generate(self, request: ImageRequest) -> bytes:
        data = self._render(request.label, request.prompt, self._parse_size(request.size))
        self._verify(data)
        return data

    @staticmethod
    def _parse_size(preferred_size: str | None) -> tuple[int, int]:
        match = re.match(r"\s*(\d+)\s*[xX]\s*(\d+)", preferred_size or "")
        if match:
            return int(match.group(1)), int(match.group(2))
        return 1440, 2560

    @staticmethod
    def _placeholder_font(size: int):
        for name in ("msyh.ttc", "arial.ttf", "DejaVuSans.ttf"):
            try:
                return ImageFont.truetype(name, size)
            except Exception:
                continue
        return ImageFont.load_default()

    def _render(self, label: str, prompt: str, size: tuple[int, int]) -> bytes:
        """Render a deterministic placeholder image so the full pipeline runs without image API keys."""
        width, height = size
        tint = sum(ord(ch) for ch in label)
        background = (30 + tint * 53 % 60, 30 + tint * 97 % 60, 50 + tint * 131 % 60)
        image = Image.new("RGB", (width, height), background)
        draw = ImageDraw.Draw(image)
        font_px = max(width // 40, 16)
        title_font = self._placeholder_font(max(width // 18, 28))
        body_font = self._placeholder_font(font_px)
        margin = int(width * 0.06)
        draw.text((margin, margin), label, fill=(245, 245, 245), font=title_font)
        body = " ".join(str(prompt or "").split())[:600]
        chars_per_line = max(int(width * 0.9 / (font_px * 0.6)), 24)
        wrapped = textwrap.fill(body, width=chars_per_line, max_lines=12, placeholder=" …")
        draw.multiline_text((margin, int(height * 0.16)), wrapped, fill=(215, 215, 215), font=body_font, spacing=8)
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue()

    @staticmethod
    def _verify(data: bytes) -> None:
        with Image.open(BytesIO(data)) as image:
            image.verify()
