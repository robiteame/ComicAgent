from __future__ import annotations

import json
import os
import stat
import socket
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_SERVER_DIR = Path(__file__).resolve().parents[1]
if str(_SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(_SERVER_DIR))

from test_environment import TEST_ROOT  # noqa: F401,E402

from services import model_config_service


class ModelConfigSecurityTests(unittest.TestCase):
    def test_credentials_are_atomically_stored_with_private_permissions_and_masked(self) -> None:
        payload = {
            "script": {
                "provider": "openai",
                "api_key": "test-secret-value",
                "base_url": "https://api.example.test/v1",
                "model": "example-model",
            }
        }

        public_dns = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]
        with tempfile.TemporaryDirectory(prefix="comic-agent-config-") as root:
            with (
                patch.object(model_config_service.settings, "DATA_DIR", Path(root)),
                patch.object(model_config_service.socket, "getaddrinfo", return_value=public_dns),
            ):
                model_config_service._save_raw(payload)
                config_path = Path(root) / "model_api_config.json"

                self.assertEqual(json.loads(config_path.read_text(encoding="utf-8")), payload)
                # POSIX permission bits are not enforceable via os.chmod on
                # Windows; the private-mode contract is a POSIX-only check.
                if os.name != "nt":
                    self.assertEqual(stat.S_IMODE(config_path.stat().st_mode) & 0o077, 0)
                self.assertEqual(model_config_service.get_model_config()["categories"]["script"]["api_key"], "********")
                self.assertEqual(list(Path(root).glob(".model_api_config.json.*.tmp")), [])

    def test_base_url_rejects_ambiguous_ip_and_non_public_dns(self) -> None:
        with self.assertRaisesRegex(ValueError, "非标准 IP"):
            model_config_service._validate_base_url("http://2130706433/v1")

        private_dns = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))]
        with patch.object(model_config_service.socket, "getaddrinfo", return_value=private_dns):
            with self.assertRaisesRegex(ValueError, "本机/内网"):
                model_config_service._validate_base_url("https://api.example.test/v1")

        reserved_dns = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.0.2.10", 443))]
        with patch.object(model_config_service.socket, "getaddrinfo", return_value=reserved_dns):
            with self.assertRaisesRegex(ValueError, "本机/内网"):
                model_config_service._validate_base_url("https://api.example.test/v1")

    def test_endpoint_identity_tracks_only_scheme_host_and_effective_port(self) -> None:
        identity = model_config_service._endpoint_identity
        self.assertEqual(identity("http://API.EXAMPLE.test/v1"), identity("http://api.example.test:80/v2"))
        self.assertNotEqual(identity("http://api.example.test"), identity("https://api.example.test"))
        self.assertNotEqual(identity("https://api.example.test"), identity("https://api.example.test:8443"))

    def test_image_endpoint_marker_clears_all_fallback_keys(self) -> None:
        fields = ("ARK_API_KEY", "SEEDDANCE_API_KEY", "SEEDREAM_API_KEY", "STABILITY_API_KEY")
        originals = {field: getattr(model_config_service.settings, field) for field in fields}
        try:
            for field in fields:
                setattr(model_config_service.settings, field, "old-key")
            model_config_service.apply_model_config_to_settings(
                {"image": {"provider": "stability", model_config_service.API_KEY_REQUIRED: True}}
            )
            self.assertTrue(all(getattr(model_config_service.settings, field) == "" for field in fields))
        finally:
            for field, value in originals.items():
                setattr(model_config_service.settings, field, value)

    def test_endpoint_change_requires_explicit_new_api_key(self) -> None:
        public_dns = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]
        original_key = model_config_service.settings.OPENAI_API_KEY
        original_base_url = model_config_service.settings.OPENAI_BASE_URL
        original_provider = model_config_service.settings.LLM_PROVIDER
        try:
            with tempfile.TemporaryDirectory(prefix="comic-agent-config-") as root:
                with (
                    patch.object(model_config_service.settings, "DATA_DIR", Path(root)),
                    patch.object(model_config_service.socket, "getaddrinfo", return_value=public_dns),
                ):
                    model_config_service._save_raw(
                        {"script": {"provider": "openai", "api_key": "old-key", "base_url": "https://old.example.test/v1"}}
                    )
                    model_config_service.settings.OPENAI_API_KEY = "old-key"

                    model_config_service.save_model_config(
                        {"script": {"base_url": "https://new.example.test/v1", "api_key": "********"}}
                    )
                    stored = model_config_service._load_raw()["script"]
                    self.assertNotIn("api_key", stored)
                    self.assertTrue(stored[model_config_service.API_KEY_REQUIRED])
                    self.assertEqual(model_config_service.settings.OPENAI_API_KEY, "")
                    self.assertEqual(model_config_service.get_model_config()["categories"]["script"]["api_key"], "")

                    model_config_service.settings.OPENAI_API_KEY = "environment-old-key"
                    model_config_service.apply_model_config_to_settings()
                    self.assertEqual(model_config_service.settings.OPENAI_API_KEY, "")

                    model_config_service.save_model_config(
                        {"script": {"base_url": "https://third.example.test/v1", "api_key": "new-key"}}
                    )
                    stored = model_config_service._load_raw()["script"]
                    self.assertNotIn(model_config_service.API_KEY_REQUIRED, stored)
                    self.assertEqual(model_config_service.settings.OPENAI_API_KEY, "new-key")
        finally:
            model_config_service.settings.OPENAI_API_KEY = original_key
            model_config_service.settings.OPENAI_BASE_URL = original_base_url
            model_config_service.settings.LLM_PROVIDER = original_provider


if __name__ == "__main__":
    unittest.main()
