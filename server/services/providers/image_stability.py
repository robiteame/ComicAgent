"""Stability AI 图像适配器（原 ImageService._call_stability 迁入）。"""

from __future__ import annotations

import httpx

from config import settings
from services.providers.base import BaseAdapter, ImageCapabilities, ImageRequest
from services.providers.image_common import read_bounded_response


class StabilityImageAdapter(BaseAdapter):
    capabilities = ImageCapabilities(reference_images=False, requires_credentials=True)

    async def generate(self, request: ImageRequest) -> bytes:
        if not self.endpoint.base_url:
            raise RuntimeError("Stability 端点未配置 Base URL")
        async with httpx.AsyncClient(timeout=45) as client:
            request_message = client.build_request(
                "POST",
                f"{self.endpoint.base_url.rstrip('/')}/stable-image/generate/core",
                headers={
                    "Authorization": f"Bearer {self.endpoint.api_key}",
                    "Accept": "image/*",
                },
                data={
                    "prompt": request.prompt,
                    "negative_prompt": request.negative_prompt,
                    "seed": request.seed,
                    "output_format": "png",
                },
            )
            response = await client.send(request_message, stream=True)
            try:
                response.raise_for_status()
                data = await read_bounded_response(response)
                if len(data) > settings.MAX_IMAGE_GENERATION_BYTES:
                    raise RuntimeError("图像数据超过大小限制")
                return data
            finally:
                await response.aclose()
