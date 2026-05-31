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
            "vision_model": settings.MIMO_MULTIMODAL_MODEL,
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
        self._fallback_client: AsyncOpenAI | None = None
        self.provider = (settings.LLM_PROVIDER or "openai").lower()
        configs = _provider_config()
        cfg = configs.get(self.provider, configs["openai"])
        self.model = cfg["model"] or "gpt-4o-mini"
        self.vision_model = cfg.get("vision_model") or self.model
        self._api_key = cfg["api_key"] or ""
        self._base_url = cfg["base_url"]
        self.max_tokens = settings.LLM_MAX_TOKENS
        self.last_provider_used = self.provider
        self._fallback_cfg = self._build_fallback_config()

    @property
    def available(self) -> bool:
        return bool(self._api_key or self._fallback_cfg)

    @property
    def client(self) -> AsyncOpenAI:
        if not self.available:
            raise RuntimeError("未配置可用的 LLM API Key")
        if self._client is None:
            default_headers = {"api-key": self._api_key} if self.provider == "mimo" else None
            self._client = AsyncOpenAI(
                api_key=self._api_key,
                base_url=self._base_url,
                timeout=60,
                default_headers=default_headers,
            )
        return self._client

    @property
    def fallback_client(self) -> AsyncOpenAI:
        if not self._fallback_cfg:
            raise RuntimeError("未配置可用的 LLM 兜底接口")
        if self._fallback_client is None:
            self._fallback_client = AsyncOpenAI(
                api_key=self._fallback_cfg["api_key"] or "",
                base_url=self._fallback_cfg["base_url"],
                timeout=60,
            )
        return self._fallback_client

    async def call(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.7,
        allow_fallback: bool = True,
        model_override: str | None = None,
    ) -> str:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        response = await self._completion_with_fallback(
            lambda client, model: client.chat.completions.create(
                model=model_override or model,
                messages=messages,
                temperature=temperature,
                max_tokens=self.max_tokens,
            ),
            allow_fallback=allow_fallback,
        )
        return self._message_text(response.choices[0].message)

    async def call_json(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.3,
        max_retries: int = 2,
        allow_fallback: bool = True,
        model_override: str | None = None,
    ) -> dict:
        last_error: Exception | None = None
        for attempt in range(max_retries + 1):
            try:
                response = await self._create_json_completion(
                    system_prompt,
                    user_prompt,
                    temperature,
                    allow_fallback,
                    model_override,
                )
                return self._loads_json(self._message_text(response.choices[0].message) or "{}")
            except Exception as exc:
                last_error = exc
                if attempt < max_retries:
                    continue

        raise ValueError(f"LLM JSON 解析失败，已重试 {max_retries} 次: {last_error}")

    async def _create_json_completion(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        allow_fallback: bool = True,
        model_override: str | None = None,
    ):
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        try:
            return await self._completion_with_fallback(
                lambda client, model: client.chat.completions.create(
                    model=model_override or model,
                    messages=messages,
                    temperature=temperature,
                    response_format={"type": "json_object"},
                    max_tokens=self.max_tokens,
                ),
                allow_fallback=allow_fallback,
            )
        except Exception as exc:
            if "response_format" not in str(exc):
                raise
            return await self._completion_with_fallback(
                lambda client, model: client.chat.completions.create(
                    model=model_override or model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=self.max_tokens,
                ),
                allow_fallback=allow_fallback,
            )

    async def _completion_with_fallback(self, create_completion, allow_fallback: bool = True):
        try:
            response = await create_completion(self.client, self.model)
            self.last_provider_used = self.provider
            return response
        except Exception as primary_error:
            if not allow_fallback or not self._fallback_cfg:
                raise
            response = await create_completion(self.fallback_client, self._fallback_cfg["model"])
            self.last_provider_used = self._fallback_cfg["provider"]
            return response

    def _build_fallback_config(self) -> dict[str, str | None] | None:
        if not settings.OPENAI_API_KEY:
            return None
        if self.provider in {"openai", "deepseek"} and settings.OPENAI_API_KEY == self._api_key:
            return None
        return {
            "provider": "deepseek",
            "api_key": settings.OPENAI_API_KEY,
            "base_url": settings.OPENAI_BASE_URL or "https://api.deepseek.com",
            "model": settings.OPENAI_MODEL or "deepseek-chat",
        }

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

    def _message_text(self, message) -> str:
        content = getattr(message, "content", None)
        if content:
            return content
        return getattr(message, "reasoning_content", None) or ""

    async def call_with_image(self, prompt: str, image_path: str) -> str:
        import base64
        import mimetypes

        with open(image_path, "rb") as f:
            image_data = base64.b64encode(f.read()).decode()
        mime_type = mimetypes.guess_type(image_path)[0] or "image/png"

        response = await self.client.chat.completions.create(
            model=self.vision_model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{mime_type};base64,{image_data}"},
                        },
                    ],
                }
            ],
            temperature=0.3,
            max_tokens=self.max_tokens,
        )
        return self._message_text(response.choices[0].message)
