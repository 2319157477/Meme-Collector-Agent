"""Dify knowledge-base client with explicit write semantics."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import httpx

from meme_collector_app.schemas import WriteResult
from meme_collector_app.services.dedupe import is_duplicate_name


@dataclass(frozen=True)
class DifyConfig:
    dataset_id: str
    api_key: str
    base_url: str = "https://api.dify.ai/v1"
    proxy: str | None = None


class DifyClient:
    """Small async Dify client for document listing and create-by-text writes."""

    def __init__(self, config: DifyConfig, *, timeout: float = 30.0) -> None:
        self.config = config
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }

    def _client(self) -> httpx.AsyncClient:
        kwargs = {"timeout": self.timeout}
        if self.config.proxy:
            kwargs["proxy"] = self.config.proxy
        return httpx.AsyncClient(**kwargs)

    async def list_documents(self) -> list[str]:
        """List all document names in the configured Dify dataset."""

        names: list[str] = []
        page = 1
        url = f"{self.config.base_url.rstrip('/')}/datasets/{self.config.dataset_id}/documents"
        async with self._client() as client:
            while True:
                response = await client.get(
                    url, headers=self._headers(), params={"page": page, "limit": 100}
                )
                response.raise_for_status()
                data = response.json()
                names.extend(doc["name"] for doc in data.get("data", []) if "name" in doc)
                if not data.get("has_more", False):
                    break
                page += 1
        return names

    async def upload_document(self, name: str, text: str) -> str:
        """Create one Dify document by text and return its document id."""

        url = (
            f"{self.config.base_url.rstrip('/')}/datasets/"
            f"{self.config.dataset_id}/document/create_by_text"
        )
        payload = {
            "name": name,
            "text": text,
            "indexing_technique": "high_quality",
            "process_rule": {"mode": "automatic"},
        }
        async with self._client() as client:
            response = await client.post(url, headers=self._headers(), json=payload)
            response.raise_for_status()
            data = response.json()
        if "document" not in data:
            raise RuntimeError(str(data)[:500])
        return str(data["document"].get("id", "unknown"))

    async def batch_upload_approved(self, records: list[dict[str, str]]) -> WriteResult:
        """List existing docs, skip duplicates, and upload approved records sequentially."""

        result = WriteResult()
        existing = set(await self.list_documents())
        for index, record in enumerate(records):
            name = record["name"]
            if is_duplicate_name(name, existing):
                result.skipped += 1
                result.messages.append(f"skip duplicate: {name}")
                continue
            try:
                document_id = await self.upload_document(name, record["markdown"])
            except Exception as exc:  # noqa: BLE001 - preserve per-record failure
                result.failed += 1
                result.messages.append(f"failed {name}: {exc}")
            else:
                existing.add(name)
                result.success += 1
                result.messages.append(f"uploaded {name}: {document_id}")
            if index < len(records) - 1:
                await asyncio.sleep(1)
        return result
