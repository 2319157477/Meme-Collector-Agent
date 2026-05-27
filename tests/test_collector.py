from __future__ import annotations

import unittest
import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch

from meme_collector_app.core.config import parse_bool
from meme_collector_app.db import repositories as repo
from meme_collector_app.schemas import CandidateStatus, CollectionTaskIn, MemeCandidate
from meme_collector_app.services.collector import (
    load_runtime_config,
    make_agent,
    run_collection,
    write_approved,
)
from tests.helpers import TempDatabaseMixin


class FakeDifyClient:
    def __init__(self, existing: list[str] | None = None) -> None:
        self.existing = existing or []
        self.uploaded: list[tuple[str, str]] = []

    async def list_documents(self) -> list[str]:
        return self.existing

    async def upload_document(self, name: str, text: str) -> str:
        self.uploaded.append((name, text))
        return f"doc-{len(self.uploaded)}"


class CollectorFlowTests(TempDatabaseMixin, unittest.IsolatedAsyncioTestCase):
    def test_parse_bool_accepts_expected_persisted_spellings(self) -> None:
        for value in ("1", "true", "yes", "on", True):
            self.assertTrue(parse_bool(value))
        for value in ("0", "false", "no", "off", "", False):
            self.assertFalse(parse_bool(value, default=True))
        self.assertTrue(parse_bool("unexpected", default=True))
        self.assertFalse(parse_bool("unexpected", default=False))

    def sample_candidate(self, name: str = "发疯文学") -> MemeCandidate:
        return MemeCandidate(
            name=name,
            meme_type="流行语",
            heat_level="🔥🔥",
            popularity_period="最近一周",
            derivative_potential="高",
            platforms=["微博"],
            meaning="用夸张语气表达压力和情绪的网络表达方式，常用于自嘲和调侃。",
            catchphrases=["我真的会谢"],
            origin="社交平台表达演化",
            emotion_tags=["自嘲"],
            scenarios=["职场"],
            usage_examples=["项目延期时：我开始发疯文学。"],
            script_integration_guide="适合压力大的角色吐槽，用夸张语气制造笑点。",
            source_urls=["https://example.com/a"],
            confidence=0.75,
        )

    async def test_write_approved_requires_selected_candidate_and_updates_status(self) -> None:
        candidate_id = repo.insert_candidate(None, self.sample_candidate())
        self.assertIsNotNone(candidate_id)
        fake = FakeDifyClient()

        pending_result = await write_approved([candidate_id], client=fake)  # type: ignore[arg-type]
        self.assertEqual(pending_result.success, 0)
        self.assertEqual(len(fake.uploaded), 0)

        repo.update_candidate_status(candidate_id, CandidateStatus.APPROVED)
        result = await write_approved([candidate_id], client=fake)  # type: ignore[arg-type]
        self.assertEqual(result.success, 1)
        rows = repo.list_candidates("written")
        self.assertEqual(rows[0]["name"], "发疯文学")
        self.assertEqual(rows[0]["dify_document_id"], "doc-1")
        self.assertEqual(len(fake.uploaded), 1)

    async def test_direct_candidate_insert_is_pending_without_writing(self) -> None:
        candidate_id = repo.insert_candidate(None, self.sample_candidate("躺平"))
        self.assertIsNotNone(candidate_id)
        pending = repo.list_candidates("pending")
        self.assertEqual(pending[0]["name"], "躺平")

    async def test_run_collection_uses_fake_boundaries_and_inserts_pending(self) -> None:
        task_id = repo.save_task(
            CollectionTaskIn(name="test", query="q", schedule_cron="0 * * * *", max_candidates=5)
        )
        fake_dify = FakeDifyClient(existing=["已存在"])

        class FakeAgent:
            async def collect(self, **kwargs):
                self.kwargs = kwargs
                return [self_outer.sample_candidate("新梗")]

        self_outer = self
        fake_agent = FakeAgent()
        with patch("meme_collector_app.services.collector.make_dify_client", return_value=fake_dify):
            run_id = await run_collection(task_id, agent=fake_agent)

        pending = repo.list_candidates("pending")
        runs = repo.list_runs()
        self.assertEqual(pending[0]["name"], "新梗")
        self.assertEqual(runs[0]["id"], run_id)
        self.assertEqual(runs[0]["status"], "completed")
        self.assertEqual(fake_agent.kwargs["existing_names"], ["已存在"])

    async def test_run_collection_dry_run_skip_avoids_dify_and_inserts_pending(self) -> None:
        repo.save_settings({"dify_skip_check_for_dry_run": "true"})
        task_id = repo.save_task(
            CollectionTaskIn(name="test", query="q", schedule_cron="0 * * * *", max_candidates=5)
        )

        class FakeAgent:
            async def collect(self, **kwargs):
                self.kwargs = kwargs
                return [self_outer.sample_candidate("测试梗")]

        self_outer = self
        fake_agent = FakeAgent()
        with patch(
            "meme_collector_app.services.collector.make_dify_client",
            side_effect=AssertionError("make_dify_client must not be called in dry-run skip mode"),
        ):
            run_id = await run_collection(task_id, agent=fake_agent)

        pending = repo.list_candidates("pending")
        runs = repo.list_runs()
        self.assertEqual(pending[0]["name"], "测试梗")
        self.assertEqual(runs[0]["id"], run_id)
        self.assertEqual(runs[0]["status"], "completed")
        self.assertEqual(fake_agent.kwargs["existing_names"], [])

    async def test_dry_run_skip_preserves_local_duplicate_protection(self) -> None:
        repo.save_settings({"dify_skip_check_for_dry_run": "true"})
        task_id = repo.save_task(
            CollectionTaskIn(name="test", query="q", schedule_cron="0 * * * *", max_candidates=5)
        )
        repo.insert_candidate(None, self.sample_candidate("本地重复梗"))

        class FakeAgent:
            async def collect(self, **kwargs):
                return [self_outer.sample_candidate("本地重复梗")]

        self_outer = self
        with patch(
            "meme_collector_app.services.collector.make_dify_client",
            side_effect=AssertionError("make_dify_client must not be called in dry-run skip mode"),
        ):
            await run_collection(task_id, agent=FakeAgent())

        self.assertEqual(len(repo.list_candidates("pending")), 1)
        self.assertEqual(repo.list_runs()[0]["skipped_count"], 1)

    async def test_write_approved_still_requires_dify_credentials_without_fake_client(self) -> None:
        repo.save_settings({"dify_skip_check_for_dry_run": "true"})
        candidate_id = repo.insert_candidate(None, self.sample_candidate("写入仍需凭据"))
        repo.update_candidate_status(candidate_id, CandidateStatus.APPROVED)

        with self.assertRaisesRegex(RuntimeError, "Dify dataset id and API key are required"):
            await write_approved([candidate_id])

    async def test_run_collection_skips_when_task_already_running(self) -> None:
        task_id = repo.save_task(
            CollectionTaskIn(name="test", query="q", schedule_cron="0 * * * *", max_candidates=5)
        )
        repo.create_run(task_id, "running")
        run_id = await run_collection(task_id, agent=None)
        runs = repo.list_runs()
        self.assertEqual(runs[0]["id"], run_id)
        self.assertEqual(runs[0]["status"], "skipped")

    async def test_concurrent_run_collection_only_one_runs(self) -> None:
        task_id = repo.save_task(
            CollectionTaskIn(name="test", query="q", schedule_cron="0 * * * *", max_candidates=5)
        )

        class SlowFakeAgent:
            async def collect(self, **kwargs):
                await asyncio.sleep(0.05)
                return [self_outer.sample_candidate("并发梗")]

        self_outer = self
        fake_dify = FakeDifyClient()
        with patch("meme_collector_app.services.collector.make_dify_client", return_value=fake_dify):
            await asyncio.gather(
                run_collection(task_id, agent=SlowFakeAgent()),
                run_collection(task_id, agent=SlowFakeAgent()),
            )

        statuses = sorted(row["status"] for row in repo.list_runs())
        self.assertEqual(statuses, ["completed", "skipped"])
        self.assertEqual(len(repo.list_candidates("pending")), 1)

    async def test_create_run_or_skip_is_atomic_under_thread_contention(self) -> None:
        task_id = repo.save_task(
            CollectionTaskIn(name="test", query="q", schedule_cron="0 * * * *", max_candidates=5)
        )
        barrier = Barrier(2)

        def contend() -> tuple[int, bool]:
            barrier.wait(timeout=5)
            return repo.create_run_or_skip(task_id)

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: contend(), range(2)))

        should_run_values = sorted(should_run for _, should_run in results)
        statuses = sorted(row["status"] for row in repo.list_runs())
        self.assertEqual(should_run_values, [False, True])
        self.assertEqual(statuses, ["running", "skipped"])

    async def test_saved_openai_settings_reach_runtime_agent(self) -> None:
        repo.save_settings(
            {
                "openai_api_key": "sk-from-ui",
                "openai_model": "gpt-test",
                "openai_base_url": "https://llm.example.test/v1",
            }
        )
        config = load_runtime_config()
        self.assertEqual(config.openai_api_key, "sk-from-ui")
        self.assertEqual(config.openai_model, "gpt-test")
        self.assertEqual(config.openai_base_url, "https://llm.example.test/v1")

        agent = make_agent(config)
        self.assertEqual(agent.openai_base_url, "https://llm.example.test/v1")

    async def test_dify_dry_run_skip_env_and_saved_bool_precedence(self) -> None:
        self.assertFalse(load_runtime_config().dify_skip_check_for_dry_run)

        os.environ["DIFY_SKIP_CHECK_FOR_DRY_RUN"] = "true"
        from meme_collector_app.core.config import get_settings

        get_settings.cache_clear()
        self.assertTrue(load_runtime_config().dify_skip_check_for_dry_run)

        repo.save_settings({"dify_skip_check_for_dry_run": "false"})
        self.assertFalse(load_runtime_config().dify_skip_check_for_dry_run)

        os.environ["DIFY_SKIP_CHECK_FOR_DRY_RUN"] = "false"
        get_settings.cache_clear()
        repo.save_settings({"dify_skip_check_for_dry_run": "true"})
        self.assertTrue(load_runtime_config().dify_skip_check_for_dry_run)


if __name__ == "__main__":
    unittest.main()

