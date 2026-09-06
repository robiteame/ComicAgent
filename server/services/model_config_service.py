"""模型与 API 自定义配置服务。

提供剧本(LLM)/图像/视频/配音四类生成模型的接口地址、密钥、模型名等可视化配置的
持久化与运行时生效能力。配置以全局 JSON 形式保存在 ``data/model_api_config.json``，
保存后立即覆盖到全局 ``settings`` 单例；各生成服务在调用时实时读取 ``settings``，
因此新任务会自动加载最新配置，而已生成的存量产物不受影响。

设计要点：
- 仅当某字段填写了非空值时才覆盖 ``settings``，留空表示沿用 ``.env`` / 默认值，
  避免误清空已有密钥。
- GET 返回「生效值」（持久化覆盖优先，否则回退到当前 settings），便于前端回填表单。
"""

from __future__ import annotations

import ipaddress
import json
import os
import re
import socket
import uuid
from typing import Any
from urllib.parse import urlparse

from config import settings


# 四类模型的可视化字段定义。每个字段映射到一个或多个 settings 属性，
# apply 时根据 provider 选择正确的目标属性，保证沿用现有调用链路。
CATEGORIES = ("script", "image", "video", "voice")
MASKED_SECRET = "********"
API_KEY_REQUIRED = "api_key_required"


def _store_path():
    return settings.DATA_DIR / "model_api_config.json"


def _load_raw() -> dict[str, Any]:
    path = _store_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8") or "{}")
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _save_raw(data: dict[str, Any]) -> None:
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as output:
            json.dump(data, output, ensure_ascii=False, indent=2)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        # The file contains API credentials. Set restrictive permissions before
        # publication so there is no window where another local user can read it.
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _validate_base_url(value: Any) -> str:
    """Reject malformed/private endpoints that could be used for SSRF."""

    text = _clean(value)
    if not text:
        return text
    if len(text) > 2048:
        raise ValueError("Base URL 过长")
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Base URL 必须是 http(s) 地址")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Base URL 端口非法") from exc
    host = parsed.hostname.rstrip(".").lower()
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None

    if ip is None:
        # inet_aton accepts ambiguous IPv4 forms such as 2130706433 and 127.1;
        # HTTP stacks may interpret those as loopback even though ip_address does
        # not. Reject them rather than treating them as ordinary DNS names.
        try:
            socket.inet_aton(host)
        except OSError:
            pass
        else:
            raise ValueError("Base URL 不允许使用非标准 IP 地址")
        try:
            ascii_host = host.encode("idna").decode("ascii")
        except UnicodeError as exc:
            raise ValueError("Base URL 主机名非法") from exc
        if len(ascii_host) > 253 or not all(
            label and len(label) <= 63 and re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?", label)
            for label in ascii_host.split(".")
        ):
            raise ValueError("Base URL 主机名非法")
        try:
            addresses = {
                result[4][0]
                for result in socket.getaddrinfo(ascii_host, port, type=socket.SOCK_STREAM)
            }
        except OSError as exc:
            raise ValueError("Base URL 主机名无法解析") from exc
        if not addresses:
            raise ValueError("Base URL 主机名无法解析")
        try:
            resolved = [ipaddress.ip_address(address.split("%", 1)[0]) for address in addresses]
        except ValueError as exc:
            raise ValueError("Base URL 解析结果非法") from exc
    else:
        resolved = [ip]

    if any(
        not address.is_global
        or address.is_loopback
        or address.is_link_local
        or address.is_private
        or address.is_reserved
        or address.is_multicast
        or address.is_unspecified
        for address in resolved
    ):
        raise ValueError("禁止使用本机/内网 Base URL")
    return text.rstrip("/")


def _endpoint_identity(value: Any) -> tuple[str, str, int | None] | None:
    text = _clean(value)
    if not text:
        return None
    parsed = urlparse(text)
    try:
        port = parsed.port
    except ValueError:
        return None
    if not parsed.scheme or not parsed.hostname:
        return None
    host = parsed.hostname.rstrip(".").lower()
    try:
        host = host.encode("idna").decode("ascii")
    except UnicodeError:
        return None
    effective_port = port if port is not None else {"http": 80, "https": 443}.get(parsed.scheme.lower())
    return parsed.scheme.lower(), host, effective_port


# ---------------------------------------------------------------------------
# 生效值读取（持久化覆盖 > 当前 settings）
# ---------------------------------------------------------------------------


def _mask_secret(value: Any) -> str:
    text = _clean(value)
    if not text:
        return ""
    return MASKED_SECRET


def _effective(*, mask_secrets: bool = True) -> dict[str, dict[str, Any]]:
    stored = _load_raw()

    def pick(category: str, field: str, fallback: Any) -> Any:
        cat = stored.get(category) or {}
        if field == "api_key" and cat.get(API_KEY_REQUIRED):
            return ""
        val = cat.get(field)
        if val is None or (isinstance(val, str) and not val.strip()):
            return fallback
        return val

    result = {
        "script": {
            "provider": pick("script", "provider", settings.LLM_PROVIDER or "openai"),
            "api_key": pick(
                "script",
                "api_key",
                settings.MIMO_API_KEY if (settings.LLM_PROVIDER or "").lower() == "mimo" else settings.OPENAI_API_KEY,
            ),
            "base_url": pick(
                "script",
                "base_url",
                settings.MIMO_BASE_URL if (settings.LLM_PROVIDER or "").lower() == "mimo" else settings.OPENAI_BASE_URL,
            ),
            "model": pick(
                "script",
                "model",
                settings.MIMO_MODEL if (settings.LLM_PROVIDER or "").lower() == "mimo" else settings.OPENAI_MODEL,
            ),
            "max_tokens": pick("script", "max_tokens", settings.LLM_MAX_TOKENS),
        },
        "image": {
            "provider": pick("image", "provider", settings.IMAGE_PROVIDER or "local"),
            "api_key": pick("image", "api_key", settings.ARK_API_KEY or settings.SEEDREAM_API_KEY),
            "base_url": pick("image", "base_url", settings.SEEDDANCE_BASE_URL),
            "model": pick("image", "model", settings.SEEDREAM_MODEL),
            "image_size": pick("image", "image_size", settings.SEEDREAM_IMAGE_SIZE),
        },
        "video": {
            "provider": pick("video", "provider", settings.VIDEO_PROVIDER),
            "api_key": pick("video", "api_key", settings.SEEDDANCE_API_KEY or settings.ARK_API_KEY),
            "base_url": pick("video", "base_url", settings.SEEDDANCE_BASE_URL),
            "model": pick("video", "model", settings.SEEDDANCE_MODEL),
        },
        "voice": {
            "api_key": pick("voice", "api_key", settings.MIMO_API_KEY),
            "base_url": pick("voice", "base_url", settings.MIMO_BASE_URL),
            "model": pick("voice", "model", settings.MIMO_TTS_MODEL),
            "voice": pick("voice", "voice", settings.MIMO_TTS_VOICE),
            "format": pick("voice", "format", settings.MIMO_TTS_FORMAT),
        },
    }
    if mask_secrets:
        for category in result.values():
            if "api_key" in category:
                category["api_key"] = _mask_secret(category["api_key"])
    return result


def get_model_config() -> dict[str, Any]:
    """返回四类模型的生效配置，供前端回填。"""
    return {"categories": _effective(mask_secrets=True)}


# ---------------------------------------------------------------------------
# 保存与应用
# ---------------------------------------------------------------------------


def save_model_config(data: dict[str, Any]) -> dict[str, Any]:
    """合并保存四类模型配置并立即应用到运行时 settings。"""
    stored = _load_raw()
    previous_effective = _effective(mask_secrets=False)
    incoming = data.get("categories") if isinstance(data.get("categories"), dict) else data
    for category in CATEGORIES:
        if category in (incoming or {}):
            payload = incoming[category] or {}
            if isinstance(payload, dict):
                # A masked/empty value from the UI means "leave the existing
                # secret untouched"; only a genuinely new key replaces it.
                sanitized_payload = dict(payload)
                explicit_api_key = bool(
                    "api_key" in sanitized_payload
                    and _clean(sanitized_payload["api_key"])
                    and _clean(sanitized_payload["api_key"]) != MASKED_SECRET
                )
                if "base_url" in sanitized_payload and sanitized_payload["base_url"] not in (None, ""):
                    sanitized_payload["base_url"] = _validate_base_url(sanitized_payload["base_url"])
                if "api_key" in sanitized_payload and (
                    not _clean(sanitized_payload["api_key"])
                    or _clean(sanitized_payload["api_key"]) == MASKED_SECRET
                ):
                    sanitized_payload.pop("api_key", None)
                merged = {**(stored.get(category) or {}), **sanitized_payload}
                old_endpoint = _endpoint_identity(previous_effective.get(category, {}).get("base_url"))
                new_endpoint = _endpoint_identity(merged.get("base_url"))
                if _clean(sanitized_payload.get("base_url")) and old_endpoint != new_endpoint and not explicit_api_key:
                    merged.pop("api_key", None)
                    merged[API_KEY_REQUIRED] = True
                elif explicit_api_key:
                    merged.pop(API_KEY_REQUIRED, None)
                stored[category] = {k: v for k, v in merged.items() if k is not None}
    _save_raw(stored)
    apply_model_config_to_settings()
    return get_model_config()


def _set(field: str, value: Any) -> None:
    """仅在值非空时覆盖 settings，留空沿用 .env / 默认值。"""
    if value is None:
        return
    if isinstance(value, str) and not value.strip():
        return
    setattr(settings, field, value)


def _set_api_key(field: str, category: dict[str, Any]) -> None:
    if category.get(API_KEY_REQUIRED):
        setattr(settings, field, "")
        return
    _set(field, category.get("api_key"))


def _set_base_url(field: str, value: Any) -> None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return
    try:
        _set(field, _validate_base_url(value))
    except ValueError:
        # Ignore unsafe persisted values and keep the environment/default.
        return


def apply_model_config_to_settings(config: dict[str, Any] | None = None) -> None:
    """将持久化配置覆盖到全局 settings 单例。

    各生成服务调用时实时读取 settings，因此覆盖后新任务即生效。
    """
    raw = config if config is not None else _load_raw()
    if not raw:
        return

    script = raw.get("script") or {}
    if script:
        provider = _clean(script.get("provider")).lower()
        if provider:
            settings.LLM_PROVIDER = provider
        active = provider or (settings.LLM_PROVIDER or "").lower()
        if active == "mimo":
            _set_api_key("MIMO_API_KEY", script)
            _set_base_url("MIMO_BASE_URL", script.get("base_url"))
            _set("MIMO_MODEL", script.get("model"))
        else:
            _set_api_key("OPENAI_API_KEY", script)
            _set_base_url("OPENAI_BASE_URL", script.get("base_url"))
            _set("OPENAI_MODEL", script.get("model"))
        max_tokens = script.get("max_tokens")
        if max_tokens not in (None, "", 0):
            try:
                settings.LLM_MAX_TOKENS = int(max_tokens)
            except (TypeError, ValueError):
                pass

    image = raw.get("image") or {}
    if image:
        provider = _clean(image.get("provider")).lower()
        if provider:
            settings.IMAGE_PROVIDER = provider
        if provider == "stability":
            _set_api_key("STABILITY_API_KEY", image)
            _set_base_url("STABILITY_API_URL", image.get("base_url"))
        else:
            _set_api_key("ARK_API_KEY", image)
            _set_base_url("SEEDDANCE_BASE_URL", image.get("base_url"))
        _set("SEEDREAM_MODEL", image.get("model"))
        _set("SEEDREAM_IMAGE_SIZE", image.get("image_size"))

    video = raw.get("video") or {}
    if video:
        _set("VIDEO_PROVIDER", video.get("provider"))
        _set_api_key("SEEDDANCE_API_KEY", video)
        _set_base_url("SEEDDANCE_BASE_URL", video.get("base_url"))
        _set("SEEDDANCE_MODEL", video.get("model"))

    voice = raw.get("voice") or {}
    if voice:
        _set_api_key("MIMO_API_KEY", voice)
        _set_base_url("MIMO_BASE_URL", voice.get("base_url"))
        _set("MIMO_TTS_MODEL", voice.get("model"))
        _set("MIMO_TTS_VOICE", voice.get("voice"))
        _set("MIMO_TTS_FORMAT", voice.get("format"))

    # Some services deliberately fall back across related provider keys, and
    # image/video plus script/voice share base URL settings. Enforce the marker
    # after every category has been applied so a later category cannot restore
    # an old credential for an endpoint that was changed without a new key.
    if script.get(API_KEY_REQUIRED):
        active = _clean(script.get("provider")).lower() or (settings.LLM_PROVIDER or "").lower()
        setattr(settings, "MIMO_API_KEY" if active == "mimo" else "OPENAI_API_KEY", "")
    if image.get(API_KEY_REQUIRED):
        for field in ("ARK_API_KEY", "SEEDDANCE_API_KEY", "SEEDREAM_API_KEY", "STABILITY_API_KEY"):
            setattr(settings, field, "")
    if video.get(API_KEY_REQUIRED):
        for field in ("ARK_API_KEY", "SEEDDANCE_API_KEY", "SEEDREAM_API_KEY"):
            setattr(settings, field, "")
    if voice.get(API_KEY_REQUIRED):
        settings.MIMO_API_KEY = ""


__all__ = [
    "get_model_config",
    "save_model_config",
    "apply_model_config_to_settings",
]
