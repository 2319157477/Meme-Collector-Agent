from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from meme_collector_app.db import repositories as repo
from meme_collector_app.main import create_app
from meme_collector_app.schemas import CandidateStatus, MemeCandidate
from tests.helpers import TempDatabaseMixin


class FakeDifyClient:
    def __init__(self) -> None:
        self.list_calls = 0
        self.uploaded: list[tuple[str, str]] = []

    async def list_documents(self) -> list[str]:
        self.list_calls += 1
        return []

    async def upload_document(self, name: str, text: str) -> str:
        self.uploaded.append((name, text))
        return "doc-web-e2e"


class WebSmokeTests(TempDatabaseMixin, unittest.TestCase):
    def test_health_and_homepage(self) -> None:
        app = create_app()
        with TestClient(app) as client:
            self.assertEqual(client.get("/health").json(), {"status": "ok"})
            response = client.get("/")
            self.assertEqual(response.status_code, 200)
            self.assertIn("热梗采集服务", response.text)

    def test_settings_task_and_review_flow(self) -> None:
        app = create_app()
        with TestClient(app) as client:
            settings_response = client.post(
                "/settings",
                data={
                    "openai_model": "gpt-test",
                    "openai_api_key": "sk-test-openai",
                    "openai_base_url": "https://llm.example.test/v1",
                    "anysearch_api_key": "any-test",
                    "dify_base_url": "https://api.dify.ai/v1",
                    "dify_dataset_id": "dataset",
                    "dify_api_key": "dify-test",
                    "dify_proxy": "",
                },
                follow_redirects=False,
            )
            self.assertEqual(settings_response.status_code, 303)
            settings_page = client.get("/settings")
            self.assertIn("sk-t...enai", settings_page.text)
            self.assertIn("https://llm.example.test/v1", settings_page.text)

            task_response = client.post(
                "/tasks",
                data={
                    "name": "任务",
                    "query": "最近一周网络热梗",
                    "schedule_cron": "0 * * * *",
                    "freshness": "week",
                    "max_candidates": "10",
                    "enabled": "on",
                },
                follow_redirects=False,
            )
            self.assertEqual(task_response.status_code, 303)
            self.assertEqual(len(repo.list_tasks()), 1)

            candidate_id = repo.insert_candidate(
                None,
                MemeCandidate(
                    name="审核梗",
                    meme_type="流行语",
                    heat_level="🔥",
                    popularity_period="最近一周",
                    derivative_potential="中",
                    platforms=["微博"],
                    meaning="用于测试审核页面来源链接展示的候选热梗记录。",
                    catchphrases=["测试一下"],
                    origin="测试来源",
                    emotion_tags=["搞笑"],
                    scenarios=["日常"],
                    usage_examples=["看到候选后先审核。"],
                    script_integration_guide="用于测试审核流程，不代表真实热梗。",
                    source_urls=["https://example.com/a"],
                    confidence=0.7,
                ),
            )
            pending_page = client.get("/pending")
            self.assertIn("https://example.com/a", pending_page.text)

            approve_response = client.post(
                "/pending/approve",
                data={"candidate_id": str(candidate_id)},
                follow_redirects=False,
            )
            self.assertEqual(approve_response.status_code, 303)
            self.assertEqual(repo.get_candidates([candidate_id])[0]["status"], CandidateStatus.APPROVED)

    def test_mocked_webui_e2e_manual_run_approve_write_and_restart_persistence(self) -> None:
        fake_dify = FakeDifyClient()

        async def fake_run_collection(task_id: int) -> int:
            run_id, should_run = repo.create_run_or_skip(task_id)
            self.assertTrue(should_run)
            repo.insert_candidate(
                run_id,
                MemeCandidate(
                    name="端到端热梗",
                    meme_type="流行语",
                    heat_level="🔥🔥",
                    popularity_period="最近一周",
                    derivative_potential="高",
                    platforms=["微博"],
                    meaning="用于验证 WebUI 从手动采集到审核写入的完整安全链路。",
                    catchphrases=["这很端到端"],
                    origin="测试代理输出",
                    emotion_tags=["测试"],
                    scenarios=["验收"],
                    usage_examples=["验收时说：这很端到端。"],
                    script_integration_guide="可作为测试角色台词，不代表真实热梗。",
                    source_urls=["https://example.com/e2e"],
                    confidence=0.82,
                ),
            )
            repo.finish_run(run_id, "completed", found_count=1, inserted_count=1)
            return run_id

        app = create_app()
        with (
            patch("meme_collector_app.services.scheduler.run_collection", side_effect=fake_run_collection),
            patch("meme_collector_app.services.collector.make_dify_client", return_value=fake_dify),
            TestClient(app) as client,
        ):
            settings_response = client.post(
                "/settings",
                data={
                    "openai_model": "gpt-test",
                    "openai_api_key": "sk-e2e-openai",
                    "openai_base_url": "https://llm.example.test/v1",
                    "anysearch_api_key": "any-e2e",
                    "dify_base_url": "https://api.dify.ai/v1",
                    "dify_dataset_id": "dataset-e2e",
                    "dify_api_key": "dify-e2e",
                    "dify_proxy": "",
                },
                follow_redirects=False,
            )
            self.assertEqual(settings_response.status_code, 303)

            task_response = client.post(
                "/tasks",
                data={
                    "name": "E2E 任务",
                    "query": "最近一周网络热梗",
                    "schedule_cron": "0 * * * *",
                    "freshness": "week",
                    "max_candidates": "5",
                    "enabled": "on",
                },
                follow_redirects=False,
            )
            self.assertEqual(task_response.status_code, 303)
            task_id = repo.list_tasks()[0]["id"]

            run_response = client.post(f"/tasks/{task_id}/run", follow_redirects=False)
            self.assertEqual(run_response.status_code, 303)
            pending_page = client.get("/pending")
            self.assertIn("端到端热梗", pending_page.text)
            self.assertIn("https://example.com/e2e", pending_page.text)

            candidate_id = repo.list_candidates("pending")[0]["id"]
            approve_response = client.post(
                "/pending/approve",
                data={"candidate_id": str(candidate_id)},
                follow_redirects=False,
            )
            self.assertEqual(approve_response.status_code, 303)

            write_response = client.post(
                "/write",
                data={"candidate_id": str(candidate_id)},
            )
            self.assertEqual(write_response.status_code, 200)
            self.assertIn("doc-web-e2e", write_response.text)
            self.assertEqual(fake_dify.list_calls, 1)
            self.assertEqual(fake_dify.uploaded[0][0], "端到端热梗")
            self.assertIn("## 基本信息", fake_dify.uploaded[0][1])

        restarted_app = create_app()
        with TestClient(restarted_app) as restarted:
            self.assertIn("E2E 任务", restarted.get("/tasks").text)
            settings_after_restart = restarted.get("/settings").text
            self.assertIn("sk-e...enai", settings_after_restart)
            self.assertIn("https://llm.example.test/v1", settings_after_restart)
            pending_after_restart = restarted.get("/pending")
            self.assertIn("端到端热梗", pending_after_restart.text)
            self.assertIn("doc-web-e2e", pending_after_restart.text)
            self.assertEqual(repo.get_candidates([candidate_id])[0]["status"], CandidateStatus.WRITTEN)


if __name__ == "__main__":
    unittest.main()
