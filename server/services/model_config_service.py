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

import copy
import json
from typing import Any

from config import settings


# 四类模型的可视化字段定义。每个字段映射到一个或多个 settings 属性，
# apply 时根据 provider 选择正确的目标属性，保证沿用现有调用链路。
CATEGORIES = ("script", "image", "video", "voice")


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
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""


# ---------------------------------------------------------------------------
# 生效值读取（持久化覆盖 > 当前 settings）
# ---------------------------------------------------------------------------


def _effective() -> dict[str, dict[str, Any]]:
    stored = _load_raw()

    def pick(category: str, field: str, fallback: Any) -> Any:
        cat = stored.get(category) or {}
        val = cat.get(field)
        if val is None or (isinstance(val, str) and not val.strip()):
            return fallback
        return val

    return {
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


def get_model_config() -> dict[str, Any]:
    """返回四类模型的生效配置，供前端回填。"""
    return {"categories": _effective()}


# ---------------------------------------------------------------------------
# 保存与应用
# ---------------------------------------------------------------------------


def save_model_config(data: dict[str, Any]) -> dict[str, Any]:
    """合并保存四类模型配置并立即应用到运行时 settings。"""
    stored = _load_raw()
    incoming = data.get("categories") if isinstance(data.get("categories"), dict) else data
    for category in CATEGORIES:
        if category in (incoming or {}):
            payload = incoming[category] or {}
            if isinstance(payload, dict):
                merged = {**(stored.get(category) or {}), **payload}
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
            _set("MIMO_API_KEY", script.get("api_key"))
            _set("MIMO_BASE_URL", script.get("base_url"))
            _set("MIMO_MODEL", script.get("model"))
        else:
            _set("OPENAI_API_KEY", script.get("api_key"))
            _set("OPENAI_BASE_URL", script.get("base_url"))
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
            _set("STABILITY_API_KEY", image.get("api_key"))
            _set("STABILITY_API_URL", image.get("base_url"))
        else:
            _set("ARK_API_KEY", image.get("api_key"))
            _set("SEEDDANCE_BASE_URL", image.get("base_url"))
        _set("SEEDREAM_MODEL", image.get("model"))
        _set("SEEDREAM_IMAGE_SIZE", image.get("image_size"))

    video = raw.get("video") or {}
    if video:
        _set("VIDEO_PROVIDER", video.get("provider"))
        _set("SEEDDANCE_API_KEY", video.get("api_key"))
        _set("SEEDDANCE_BASE_URL", video.get("base_url"))
        _set("SEEDDANCE_MODEL", video.get("model"))

    voice = raw.get("voice") or {}
    if voice:
        _set("MIMO_API_KEY", voice.get("api_key"))
        _set("MIMO_BASE_URL", voice.get("base_url"))
        _set("MIMO_TTS_MODEL", voice.get("model"))
        _set("MIMO_TTS_VOICE", voice.get("voice"))
        _set("MIMO_TTS_FORMAT", voice.get("format"))


__all__ = [
    "get_model_config",
    "save_model_config",
    "apply_model_config_to_settings",
]
