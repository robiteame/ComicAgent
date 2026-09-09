"""基于 openai-chat 协议适配器的 LLM 客户端。

通过 ``get_endpoint("script")`` 实时读取主端点、``get_endpoint("script_fallback")``
读取备端点，保存模型/API 配置后新任务即生效。主端点调用失败且备端点可用
（配置了 api_key 且端点标识不同）时自动回落。解析层保留 reasoning_content
与 markdown 围栏 JSON 容错。
"""

import json
import re

from config import settings
from services.providers.base import BaseAdapter
from services.providers.endpoint import EndpointConfig, endpoint_identity, get_endpoint
from services.providers.registry import get_adapter


class LLMService:
    """OpenAI 兼容协议 LLM 客户端：主/备端点自动回落 + JSON 清洗。"""

    def __init__(self):
        self._adapters: dict[tuple, BaseAdapter] = {}
        self._sync_config()

    @staticmethod
    def _connection_key(endpoint: EndpointConfig | None) -> tuple | None:
        if endpoint is None:
            return None
        return (endpoint.protocol, endpoint.base_url, endpoint.api_key, endpoint.auth_style)

    def _adapter_for(self, endpoint: EndpointConfig) -> BaseAdapter:
        key = self._connection_key(endpoint)
        adapter = self._adapters.get(key)
        if adapter is None:
            adapter = get_adapter("script", endpoint.protocol)(endpoint)
            self._adapters[key] = adapter
        return adapter

    def _sync_config(self) -> None:
        """实时从端点配置读取，保证保存模型/API 配置后新任务即生效。"""
        endpoint = get_endpoint("script")
        fallback = get_endpoint("script_fallback")
        # 备端点必须配置了密钥、且与主端点不是同一个服务地址时才参与回落。
        if not fallback.api_key or endpoint_identity(fallback.base_url) == endpoint_identity(endpoint.base_url):
            fallback = None

        self._endpoint = endpoint
        self._fallback_endpoint = fallback
        self.model = endpoint.model or "gpt-4o-mini"
        self.vision_model = endpoint.param("vision_model") or self.model
        self.max_tokens = self._int_param(endpoint.param("max_tokens"), settings.LLM_MAX_TOKENS)
        self.last_provider_used = self._endpoint_label(endpoint)

    @staticmethod
    def _int_param(value, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _endpoint_label(endpoint: EndpointConfig) -> str:
        return f"{endpoint.protocol}:{endpoint.model or 'default'}"

    @property
    def available(self) -> bool:
        self._sync_config()
        return bool(self._endpoint.api_key or self._fallback_endpoint)

    @property
    def client(self):
        self._sync_config()
        if not self.available:
            raise RuntimeError("未配置可用的 LLM API Key")
        return self._adapter_for(self._endpoint).client

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
            lambda adapter, model: adapter.complete(
                messages=messages,
                model=model_override or model,
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
        return await self._completion_with_fallback(
            lambda adapter, model: adapter.complete_json(
                messages=messages,
                model=model_override or model,
                temperature=temperature,
                max_tokens=self.max_tokens,
            ),
            allow_fallback=allow_fallback,
        )

    async def _completion_with_fallback(self, create_completion, allow_fallback: bool = True):
        self._sync_config()
        try:
            response = await create_completion(self._adapter_for(self._endpoint), self.model)
            self.last_provider_used = self._endpoint_label(self._endpoint)
            return response
        except Exception as primary_error:
            fallback = self._fallback_endpoint
            if not allow_fallback or fallback is None:
                raise
            try:
                response = await create_completion(
                    self._adapter_for(fallback), fallback.model or self.model
                )
            except Exception as fallback_error:
                # 备端点也失败时优先暴露主端点错误（更具诊断价值）。
                raise primary_error from fallback_error
            self.last_provider_used = self._endpoint_label(fallback)
            return response

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
