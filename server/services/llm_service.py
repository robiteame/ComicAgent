import json
from openai import AsyncOpenAI
from config import settings


class LLMService:
    """LLM 调用服务"""

    def __init__(self):
        self.client = AsyncOpenAI(
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL or None,
        )
        self.model = settings.OPENAI_MODEL

    async def call(self, system_prompt: str, user_prompt: str, temperature: float = 0.7) -> str:
        """调用 LLM，返回纯文本"""
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=temperature,
        )
        return response.choices[0].message.content

    async def call_json(self, system_prompt: str, user_prompt: str, temperature: float = 0.3) -> dict:
        """调用 LLM，返回 JSON 对象"""
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=temperature,
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content
        return json.loads(content)

    async def call_with_image(self, prompt: str, image_path: str) -> str:
        """调用支持视觉的 LLM"""
        import base64

        with open(image_path, "rb") as f:
            image_data = base64.b64encode(f.read()).decode()

        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{image_data}"},
                        },
                    ],
                }
            ],
            temperature=0.3,
        )
        return response.choices[0].message.content
