from __future__ import annotations

import unittest
from unittest.mock import patch

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


if __name__ == "__main__":
    unittest.main()
