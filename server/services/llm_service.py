import json
import re

from openai import AsyncOpenAI

from config import settings


def _provider_config() -> dict[str, dict[str, str | None]]:
    return {
        "openai": {
            "api_key": settings.OPENAI_API_KEY,
            "base_url": settings.OPENAI_BASE_URL or None,
            "model": settings.OPENAI_MODEL,
        },
        "deepseek": {
            "api_key": settings.OPENAI_API_KEY,
            "base_url": settings.OPENAI_BASE_URL or "https://api.deepseek.com",
            "model": settings.OPENAI_MODEL or "deepseek-chat",
        },
        "mimo": {
            "api_key": settings.MIMO_API_KEY,
            "base_url": settings.MIMO_BASE_URL,
            "model": settings.MIMO_MODEL,
        },
        "seeddance": {
            "api_key": settings.SEEDDANCE_API_KEY,
            "base_url": settings.SEEDDANCE_BASE_URL,
            "model": settings.SEEDDANCE_MODEL,
        },
    }


class LLMService:
    """OpenAI-compatible LLM client with provider aliases and JSON cleanup."""

    def __init__(self):
        self._client: AsyncOpenAI | None = None
        self.provider = (settings.LLM_PROVIDER or "openai").lower()
        configs = _provider_config()
        cfg = configs.get(self.provider, configs["openai"])
        self.model = cfg["model"] or "gpt-4o-mini"
        self._api_key = cfg["api_key"] or ""
        self._base_url = cfg["base_url"]

    @property
    def available(self) -> bool:
        return bool(self._api_key)

    @property
    def client(self) -> AsyncOpenAI:
        if not self.available:
            raise RuntimeError("未配置可用的 LLM API Key")
        if self._client is None:
            self._client = AsyncOpenAI(
                api_key=self._api_key,
                base_url=self._base_url,
                timeout=20,
            )
        return self._client

    async def call(self, system_prompt: str, user_prompt: str, temperature: float = 0.7) -> str:
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=temperature,
        )
        return response.choices[0].message.content or ""

    async def call_json(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.3,
        max_retries: int = 2,
    ) -> dict:
        last_error: Exception | None = None
        for attempt in range(max_retries + 1):
            try:
                response = await self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=temperature,
                    response_format={"type": "json_object"},
                )
                return self._loads_json(response.choices[0].message.content or "{}")
            except Exception as exc:
                last_error = exc
                if attempt < max_retries:
                    continue

        raise ValueError(f"LLM JSON 解析失败，已重试 {max_retries} 次: {last_error}")

    def _loads_json(self, content: str) -> dict:
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", content, re.S)
            if fenced:
                return json.loads(fenced.group(1))
            start = content.find("{")
            end = content.rfind("}")
            if start >= 0 and end > start:
                return json.loads(content[start : end + 1])
            raise

    async def call_with_image(self, prompt: str, image_path: str) -> str:
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
        return response.choices[0].message.content or ""
