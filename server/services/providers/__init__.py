"""模型 Provider 体系：显式协议 + 协议适配器注册表 + 自由端点配置。

- ``endpoint``: EndpointConfig 与统一读取入口 ``get_endpoint(capability)``。
- ``registry``: ``(capability, protocol) -> 适配器`` 注册表。
- ``base``: 各能力适配器接口与能力声明。
"""

from services.providers.endpoint import EndpointConfig, get_endpoint  # noqa: F401
from services.providers.registry import UnknownProtocolError, get_adapter  # noqa: F401
