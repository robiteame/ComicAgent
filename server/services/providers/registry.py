"""协议适配器注册表。

``ADAPTERS`` 以 ``(capability, protocol)`` 为键登记各能力的协议适配器；
接入同协议新服务无需改这里，接入全新协议时新增适配器文件并登记一行即可。
"""

from __future__ import annotations

from services.providers.base import BaseAdapter
from services.providers.llm_openai_chat import OpenAIChatAdapter

ADAPTERS: dict[tuple[str, str], type[BaseAdapter]] = {
    ("script", "openai-chat"): OpenAIChatAdapter,
}


class UnknownProtocolError(RuntimeError):
    """协议未注册适配器时抛出，消息中带该能力的可选协议列表。"""


def get_adapter(capability: str, protocol: str) -> type[BaseAdapter]:
    key = (str(capability).lower(), str(protocol or "").strip().lower())
    adapter = ADAPTERS.get(key)
    if adapter is None:
        options = protocols_for(key[0])
        raise UnknownProtocolError(
            f"未知的 {key[0]} 协议: {key[1] or '<empty>'}，可选值: {', '.join(options) if options else '（暂无）'}"
        )
    return adapter


def protocols_for(capability: str) -> list[str]:
    capability = str(capability).lower()
    return sorted({protocol for name, protocol in ADAPTERS if name == capability})


__all__ = ["ADAPTERS", "UnknownProtocolError", "get_adapter", "protocols_for"]
