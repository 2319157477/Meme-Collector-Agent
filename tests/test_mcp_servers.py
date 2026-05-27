from __future__ import annotations

import unittest
from unittest.mock import patch

from meme_collector_app.services import mcp_servers
from meme_collector_app.services.mcp_servers import McpConfig, McpServerBundle


class FakeMcpServer:
    captured: list[dict] = []

    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.servers = []
        FakeMcpServer.captured.append(kwargs)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


class McpServerBundleTests(unittest.IsolatedAsyncioTestCase):
    async def test_anysearch_url_headers_and_proxy_are_configurable(self) -> None:
        FakeMcpServer.captured = []
        config = McpConfig(
            anysearch_api_key="any-key",
            anysearch_mcp_url="https://mcp.example.test/anysearch",
            anysearch_proxy="http://127.0.0.1:7890",
        )

        with patch("meme_collector_app.services.mcp_servers.MCPServerStreamableHttp", FakeMcpServer):
            async with McpServerBundle(config):
                pass

        params = FakeMcpServer.captured[0]["params"]
        self.assertEqual(params["url"], "https://mcp.example.test/anysearch")
        self.assertEqual(params["headers"], {"Authorization": "Bearer any-key"})
        self.assertIn("httpx_client_factory", params)

    def test_anysearch_http_client_ignores_ambient_proxy_by_default(self) -> None:
        captured: dict = {}

        class FakeAsyncClient:
            def __init__(self, **kwargs) -> None:
                captured.update(kwargs)

        with patch.object(mcp_servers.httpx, "AsyncClient", FakeAsyncClient):
            client_factory = mcp_servers._httpx_client_factory()
            client_factory(headers={"X-Test": "1"}, timeout=None, auth=None)

        self.assertIs(captured["trust_env"], False)
        self.assertNotIn("proxy", captured)

    def test_anysearch_http_client_uses_explicit_proxy_only(self) -> None:
        captured: dict = {}

        class FakeAsyncClient:
            def __init__(self, **kwargs) -> None:
                captured.update(kwargs)

        with patch.object(mcp_servers.httpx, "AsyncClient", FakeAsyncClient):
            client_factory = mcp_servers._httpx_client_factory("http://proxy.example:7890")
            client_factory(headers=None, timeout=None, auth=None)

        self.assertIs(captured["trust_env"], False)
        self.assertEqual(captured["proxy"], "http://proxy.example:7890")


if __name__ == "__main__":
    unittest.main()
