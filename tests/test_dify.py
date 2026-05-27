from __future__ import annotations

import unittest

import httpx

from meme_collector_app.services.dify import DifyClient, DifyConfig


class MockedDifyClient(DifyClient):
    def __init__(self, config: DifyConfig, handler):
        super().__init__(config)
        self.handler = handler

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))


class DifyClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_list_documents_paginates(self) -> None:
        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(str(request.url))
            page = request.url.params.get("page")
            if page == "1":
                return httpx.Response(
                    200,
                    json={"data": [{"name": "梗A"}], "has_more": True},
                )
            return httpx.Response(200, json={"data": [{"name": "梗B"}], "has_more": False})

        client = MockedDifyClient(DifyConfig("dataset", "key"), handler)
        self.assertEqual(await client.list_documents(), ["梗A", "梗B"])
        self.assertEqual(len(calls), 2)

    async def test_upload_document_payload(self) -> None:
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["auth"] = request.headers.get("authorization")
            captured["json"] = request.content.decode()
            return httpx.Response(200, json={"document": {"id": "doc-1"}})

        client = MockedDifyClient(DifyConfig("dataset", "key"), handler)
        document_id = await client.upload_document("梗A", "# 梗A")
        self.assertEqual(document_id, "doc-1")
        self.assertIn("/datasets/dataset/document/create_by_text", captured["url"])
        self.assertEqual(captured["auth"], "Bearer key")
        self.assertIn('"indexing_technique":"high_quality"', captured["json"].replace(" ", ""))


if __name__ == "__main__":
    unittest.main()
