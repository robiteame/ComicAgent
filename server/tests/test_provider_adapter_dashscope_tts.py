"""阿里云百炼语音合成（dashscope-tts / CosyVoice）适配器的离线验收测试。

不发起真实网络请求：httpx.AsyncClient 用替身按序返回预置响应。
"""

from __future__ import annotations

import asyncio
import base64
import struct
import sys
import unittest
import wave
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

_SERVER_DIR = Path(__file__).resolve().parents[1]
if str(_SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(_SERVER_DIR))

from test_environment import TEST_ROOT  # noqa: F401,E402

from services.providers.endpoint import (  # noqa: E402
    EndpointConfig,
    normalize_protocol,
    settings_defaults,
)
from services.providers.registry import get_adapter  # noqa: E402
from services.providers.tts_dashscope import (  # noqa: E402
    DashscopeTTSAdapter,
    normalize_dashscope_voice,
)
from services.providers.usage import CAPABILITY_TTS  # noqa: E402


class _FakeResponse:
    def __init__(self, payload=None, status_code=200, text=""):
        self._payload = payload or {}
        self.status_code = status_code
        self.text = text

    def json(self):
        return self._payload


class _FakeAsyncClient:
    """按序返回预置响应并记录请求的 httpx.AsyncClient 替身。"""

    def __init__(self, responses):
        self._responses = list(responses)
        self.requests: list[dict] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, **kwargs):
        self.requests.append({"method": "POST", "url": url, **kwargs})
        return self._responses.pop(0)

    async def get(self, url, **kwargs):
        self.requests.append({"method": "GET", "url": url, **kwargs})
        return self._responses.pop(0)


def _dashscope_endpoint(api_key: str = "sk-test") -> EndpointConfig:
    return EndpointConfig(
        protocol="dashscope-tts",
        base_url="https://dashscope.aliyuncs.com/api/v1",
        api_key=api_key,
        model="cosyvoice-v2",
        params={"voice": "longwan_v2", "format": "wav"},
    )


def _make_wav(marker: int, frames: int = 160) -> bytes:
    buffer = BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(22050)
        writer.writeframes(b"".join(struct.pack("<h", 1000 * marker) for _ in range(frames)))
    return buffer.getvalue()


class DashscopeTTSProtocolTests(unittest.TestCase):
    def test_protocol_registered(self) -> None:
        self.assertIs(get_adapter("voice", "dashscope-tts"), DashscopeTTSAdapter)

    def test_normalize_protocol_aliases(self) -> None:
        for alias in ("dashscope", "dashscope-tts", "bailian", "aliyun", "cosyvoice", "qwen-tts"):
            self.assertEqual(normalize_protocol("voice", alias), "dashscope-tts")
        # 既有别名不受影响
        self.assertEqual(normalize_protocol("voice", "mimo"), "mimo-tts")
        self.assertEqual(normalize_protocol("voice", "tencent"), "tencent-tts")

    def test_voice_defaults_follow_tts_provider(self) -> None:
        from services.providers import endpoint as endpoint_module

        settings_obj = endpoint_module.settings
        original = (
            settings_obj.TTS_PROVIDER,
            settings_obj.DASHSCOPE_TTS_API_KEY,
            settings_obj.DASHSCOPE_API_KEY,
        )
        try:
            settings_obj.TTS_PROVIDER = "dashscope"
            settings_obj.DASHSCOPE_TTS_API_KEY = ""
            settings_obj.DASHSCOPE_API_KEY = "sk-shared"
            defaults = settings_defaults("voice")
            self.assertEqual(defaults["protocol"], "dashscope-tts")
            self.assertEqual(defaults["api_key"], "sk-shared")  # 未单独配置 TTS Key 时复用百炼 Key
            self.assertEqual(defaults["model"], settings_obj.DASHSCOPE_TTS_MODEL)
            self.assertEqual(defaults["params"]["voice"], settings_obj.DASHSCOPE_TTS_VOICE)
            settings_obj.DASHSCOPE_TTS_API_KEY = "sk-tts"
            self.assertEqual(settings_defaults("voice")["api_key"], "sk-tts")
            # 未显式选择百炼时保持 Mimo 默认，不因共用百炼 Key 而被劫持
            settings_obj.TTS_PROVIDER = "mimo"
            self.assertEqual(settings_defaults("voice")["protocol"], "mimo-tts")
        finally:
            (
                settings_obj.TTS_PROVIDER,
                settings_obj.DASHSCOPE_TTS_API_KEY,
                settings_obj.DASHSCOPE_API_KEY,
            ) = original

    def test_voice_defaults_tencent_credentials_win(self) -> None:
        from services.providers import endpoint as endpoint_module

        settings_obj = endpoint_module.settings
        original = (
            settings_obj.TTS_PROVIDER,
            settings_obj.TENCENT_SECRET_ID,
            settings_obj.TENCENT_SECRET_KEY,
        )
        try:
            settings_obj.TTS_PROVIDER = "dashscope"
            settings_obj.TENCENT_SECRET_ID = "AKIDtest"
            settings_obj.TENCENT_SECRET_KEY = "secret"
            self.assertEqual(settings_defaults("voice")["protocol"], "tencent-tts")
        finally:
            (settings_obj.TTS_PROVIDER, settings_obj.TENCENT_SECRET_ID, settings_obj.TENCENT_SECRET_KEY) = original

    def test_pricing_defaults_include_dashscope_tts(self) -> None:
        from services.pricing_service import DEFAULT_PRICING_PROVIDERS

        self.assertIn("dashscope-tts", DEFAULT_PRICING_PROVIDERS[CAPABILITY_TTS])


class DashscopeTTSAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = DashscopeTTSAdapter(_dashscope_endpoint())

    def test_normalize_dashscope_voice(self) -> None:
        self.assertEqual(normalize_dashscope_voice("冰糖"), "longwan_v2")
        self.assertEqual(normalize_dashscope_voice("Milo"), "longshuo_v2")
        self.assertEqual(normalize_dashscope_voice("御姐"), "longyue_v2")
        self.assertEqual(normalize_dashscope_voice("longwan_v2"), "longwan_v2")  # 百炼音色 ID 透传
        self.assertEqual(normalize_dashscope_voice("longwan"), "longwan")  # v1 音色 ID 透传
        self.assertEqual(normalize_dashscope_voice("loongstella_v2"), "loongstella_v2")
        self.assertEqual(normalize_dashscope_voice("未知音色", default_voice="longyue_v2"), "longyue_v2")
        self.assertEqual(normalize_dashscope_voice(""), "longwan_v2")

    def test_synthesize_single_segment(self) -> None:
        from services.providers.base import TTSRequest

        wav = _make_wav(1)
        client = _FakeAsyncClient([_FakeResponse({"output": {"audio": base64.b64encode(wav).decode("ascii")}})])
        with patch("services.providers.tts_dashscope.httpx.AsyncClient", return_value=client):
            audio = asyncio.run(self.adapter.synthesize(TTSRequest(text="你好", voice_id="冰糖")))
        self.assertEqual(audio, wav)
        sent = client.requests[0]
        self.assertEqual(sent["url"], "https://dashscope.aliyuncs.com/api/v1/services/audio/tts")
        self.assertEqual(sent["headers"]["Authorization"], "Bearer sk-test")
        self.assertEqual(sent["json"]["model"], "cosyvoice-v2")
        self.assertEqual(sent["json"]["input"]["text"], "你好")
        self.assertEqual(sent["json"]["parameters"]["voice"], "longwan_v2")
        self.assertEqual(sent["json"]["parameters"]["format"], "wav")

    def test_api_base_appends_api_v1(self) -> None:
        adapter = DashscopeTTSAdapter(
            EndpointConfig(protocol="dashscope-tts", base_url="https://dashscope.aliyuncs.com", api_key="sk")
        )
        self.assertEqual(adapter._api_base(), "https://dashscope.aliyuncs.com/api/v1")

    def test_synthesize_http_error_raises(self) -> None:
        from services.providers.base import TTSRequest

        client = _FakeAsyncClient(
            [
                _FakeResponse(
                    {"code": "InvalidApiKey", "message": "Invalid API-key"},
                    status_code=401,
                    text='{"code":"InvalidApiKey","message":"Invalid API-key"}',
                )
            ]
        )
        with patch("services.providers.tts_dashscope.httpx.AsyncClient", return_value=client):
            with self.assertRaisesRegex(RuntimeError, "InvalidApiKey"):
                asyncio.run(self.adapter.synthesize(TTSRequest(text="你好")))

    def test_synthesize_missing_audio_raises(self) -> None:
        from services.providers.base import TTSRequest

        client = _FakeAsyncClient([_FakeResponse({"output": {}})])
        with patch("services.providers.tts_dashscope.httpx.AsyncClient", return_value=client):
            with self.assertRaisesRegex(RuntimeError, "缺少 audio"):
                asyncio.run(self.adapter.synthesize(TTSRequest(text="你好")))

    def test_synthesize_without_api_key_raises(self) -> None:
        from services.providers.base import TTSRequest

        adapter = DashscopeTTSAdapter(_dashscope_endpoint(api_key=""))
        with self.assertRaisesRegex(RuntimeError, "API Key"):
            asyncio.run(adapter.synthesize(TTSRequest(text="你好")))

    def test_synthesize_multi_segment_concatenates_wav(self) -> None:
        from services.providers.base import TTSRequest

        wavs = [_make_wav(marker) for marker in (1, 2)]
        client = _FakeAsyncClient(
            [_FakeResponse({"output": {"audio": base64.b64encode(item).decode("ascii")}}) for item in wavs]
        )
        text = "这是一句测试台词，" * 260  # 2600 字符 → 每段 ≤1800 字符共 2 段
        with patch("services.providers.tts_dashscope.httpx.AsyncClient", return_value=client):
            audio = asyncio.run(self.adapter.synthesize(TTSRequest(text=text, voice_id="Milo")))
        self.assertEqual(len(client.requests), 2)
        self.assertTrue(all(request["json"]["parameters"]["voice"] == "longshuo_v2" for request in client.requests))
        with wave.open(BytesIO(audio)) as reader:
            self.assertEqual(reader.getnchannels(), 1)
            self.assertEqual(reader.getframerate(), 22050)
            self.assertEqual(reader.getnframes(), 160 * 2)

    def test_split_text_keeps_segments_within_limit(self) -> None:
        text = "一句话。" * 500  # 2000 字符
        segments = self.adapter._split_text(text)
        self.assertGreater(len(segments), 1)
        for segment in segments:
            self.assertLessEqual(len(segment), 1800)
        self.assertEqual("".join(segments), text)

    def test_split_text_short_text_single_segment(self) -> None:
        self.assertEqual(self.adapter._split_text("你好呀"), ["你好呀"])

    def test_usage_for_request_bills_by_characters(self) -> None:
        from services.providers.base import TTSRequest

        usage = self.adapter.usage_for_request(CAPABILITY_TTS, TTSRequest(text="  你好世界  ", voice_id="冰糖"))
        self.assertEqual(usage.characters, 4)
        self.assertTrue(usage.known)
        self.assertTrue(usage.billable)
        self.assertEqual(usage.extra.get("voice"), "longwan_v2")
        self.assertEqual(usage.extra.get("format"), "wav")


if __name__ == "__main__":
    unittest.main()
