import unittest
from unittest.mock import patch

from backend import ai_client, ai_config, main


class _Response:
    status_code = 200

    @staticmethod
    def json():
        return {"choices": [{"message": {"content": "OK"}}]}


class _Client:
    requests = []

    def __init__(self, **_kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def post(self, url, *, headers, json):
        self.requests.append({"url": url, "headers": headers, "json": json})
        return _Response()


class OpenCodeGoHeaderTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        _Client.requests.clear()

    def test_header_helper_identifies_apex_and_session(self):
        with patch.object(ai_config, "OPENCODE_USER_AGENT", "Stella-Test/1.0"), patch.object(
            ai_config, "OPENCODE_SESSION_ID", "apex-test-session"
        ):
            headers = ai_config.opencode_request_headers("test-key")

        self.assertEqual(headers["Authorization"], "Bearer test-key")
        self.assertEqual(headers["User-Agent"], "Stella-Test/1.0")
        self.assertEqual(headers["x-opencode-session"], "apex-test-session")

    async def test_ai_client_adds_go_headers(self):
        with patch.object(
            ai_client, "api_config", return_value=("https://example.test/chat/completions", "test-key", "model")
        ), patch.object(ai_client, "fallback_model", return_value="opencode:model"), patch.object(
            ai_client, "opencode_request_headers", return_value={"x-opencode-session": "apex-test"}
        ) as headers, patch.object(ai_client.httpx, "AsyncClient", _Client):
            await ai_client.call_ai_with_fallback("opencode:model", [{"role": "user", "content": "OK"}])

        headers.assert_called_once_with("test-key")
        self.assertEqual(_Client.requests[0]["headers"], {"x-opencode-session": "apex-test"})

    async def test_provider_check_adds_go_headers(self):
        with patch.object(main, "require_remote_management_enabled"), patch.object(
            main, "_current_ai_value", side_effect=["test-key", "https://example.test/chat/completions"]
        ), patch.object(main, "opencode_request_headers", return_value={"x-opencode-session": "apex-test"}) as headers, patch.object(
            main.httpx, "AsyncClient", _Client
        ):
            result = await main.test_ai_provider("opencode", object())

        self.assertTrue(result["ok"])
        headers.assert_called_once_with("test-key")
        self.assertEqual(_Client.requests[0]["headers"], {"x-opencode-session": "apex-test"})
