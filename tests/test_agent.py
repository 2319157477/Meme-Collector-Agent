from __future__ import annotations

import unittest
from unittest.mock import patch

from meme_collector_app.services import agent as agent_module


class AgentClientConfigTests(unittest.TestCase):
    def test_openai_client_ignores_ambient_proxy_and_uses_explicit_proxy(self) -> None:
        captured_http: dict = {}
        captured_openai: dict = {}

        class FakeHttpClient:
            def __init__(self, **kwargs) -> None:
                captured_http.update(kwargs)

        class FakeAsyncOpenAI:
            def __init__(self, **kwargs) -> None:
                captured_openai.update(kwargs)

        class FakeProvider:
            def __init__(self, **kwargs) -> None:
                self.kwargs = kwargs

        class FakeRunConfig:
            def __init__(self, **kwargs) -> None:
                self.kwargs = kwargs

        service = agent_module.OpenAIMemeAgent(
            model="gpt-test",
            openai_api_key="sk-test",
            openai_base_url="https://llm.example.test/v1",
            openai_proxy="http://proxy.example.test:7890",
            anysearch_api_key=None,
            anysearch_mcp_url="https://api.anysearch.com/mcp",
            anysearch_proxy=None,
        )

        with (
            patch.object(agent_module.httpx, "AsyncClient", FakeHttpClient),
            patch.object(agent_module, "AsyncOpenAI", FakeAsyncOpenAI),
            patch.object(agent_module, "OpenAIProvider", FakeProvider),
            patch.object(agent_module, "RunConfig", FakeRunConfig),
        ):
            run_config, http_client = service._run_config()

        self.assertIsNotNone(run_config)
        self.assertIsNotNone(http_client)
        self.assertIs(captured_http["trust_env"], False)
        self.assertEqual(captured_http["proxy"], "http://proxy.example.test:7890")
        self.assertEqual(captured_openai["api_key"], "sk-test")
        self.assertEqual(captured_openai["base_url"], "https://llm.example.test/v1")
        self.assertIs(captured_openai["http_client"], http_client)

    def test_openai_client_does_not_set_proxy_without_explicit_config(self) -> None:
        captured_http: dict = {}

        class FakeHttpClient:
            def __init__(self, **kwargs) -> None:
                captured_http.update(kwargs)

        class FakeAsyncOpenAI:
            def __init__(self, **kwargs) -> None:
                self.kwargs = kwargs

        class FakeProvider:
            def __init__(self, **kwargs) -> None:
                self.kwargs = kwargs

        class FakeRunConfig:
            def __init__(self, **kwargs) -> None:
                self.kwargs = kwargs

        service = agent_module.OpenAIMemeAgent(
            model="gpt-test",
            openai_api_key="sk-test",
            openai_base_url=None,
            openai_proxy=None,
            anysearch_api_key=None,
            anysearch_mcp_url="https://api.anysearch.com/mcp",
            anysearch_proxy=None,
        )

        with (
            patch.object(agent_module.httpx, "AsyncClient", FakeHttpClient),
            patch.object(agent_module, "AsyncOpenAI", FakeAsyncOpenAI),
            patch.object(agent_module, "OpenAIProvider", FakeProvider),
            patch.object(agent_module, "RunConfig", FakeRunConfig),
        ):
            service._run_config()

        self.assertIs(captured_http["trust_env"], False)
        self.assertNotIn("proxy", captured_http)


if __name__ == "__main__":
    unittest.main()
