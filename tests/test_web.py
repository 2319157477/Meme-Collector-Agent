from __future__ import annotations

import re
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from meme_collector_app.db import repositories as repo
from meme_collector_app.main import create_app
from meme_collector_app.schemas import CandidateStatus, CollectionTaskIn, MemeCandidate
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


class FakeScheduler:
    def __init__(self) -> None:
        self.reloads = 0
        self.runs: list[int] = []

    def reload_jobs(self) -> None:
        self.reloads += 1

    async def run_now(self, task_id: int) -> int:
        self.runs.append(task_id)
        return task_id


def csrf_from(html: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    if not match:
        raise AssertionError("csrf token not found")
    return match.group(1)


def login(client: TestClient, target: str = "/") -> str:
    response = client.post(
        "/login",
        data={"username": "admin", "password": "admin-pass", "next": target},
        follow_redirects=False,
    )
    if response.status_code != 303:
        raise AssertionError(response.text)
    page = client.get(target)
    if page.status_code != 200:
        raise AssertionError(page.text)
    return csrf_from(page.text)


class WebSmokeTests(TempDatabaseMixin, unittest.TestCase):
    def test_health_public_and_homepage_requires_login(self) -> None:
        app = create_app()
        with TestClient(app) as client:
            self.assertEqual(client.get("/health").json(), {"status": "ok"})
            response = client.get("/", follow_redirects=False)
            self.assertEqual(response.status_code, 303)
            self.assertIn("/login", response.headers["location"])

            login(client)
            response = client.get("/")
            self.assertEqual(response.status_code, 200)
            self.assertIn("热梗采集控制台", response.text)
            self.assertIn("运营概览", response.text)


    def test_login_next_url_rejects_external_redirect(self) -> None:
        app = create_app()
        with TestClient(app) as client:
            response = client.post(
                "/login",
                data={"username": "admin", "password": "admin-pass", "next": "//evil.test"},
                follow_redirects=False,
            )
            self.assertEqual(response.status_code, 303)
            self.assertEqual(response.headers["location"], "/")

    def test_login_rejects_invalid_credentials_and_logout_clears_cookie(self) -> None:
        app = create_app()
        with TestClient(app) as client:
            bad = client.post(
                "/login",
                data={"username": "admin", "password": "wrong", "next": "/"},
            )
            self.assertEqual(bad.status_code, 200)
            self.assertIn("用户名或密码不正确", bad.text)
            self.assertNotIn("meme_collector_auth", client.cookies)

            csrf = login(client)
            self.assertIn("meme_collector_auth", client.cookies)
            logout = client.post("/logout", data={"csrf_token": csrf}, follow_redirects=False)
            self.assertEqual(logout.status_code, 303)
            self.assertNotIn("meme_collector_auth", client.cookies)

    def test_csrf_required_for_mutating_actions(self) -> None:
        app = create_app()
        with TestClient(app) as client:
            login(client, "/settings")
            response = client.post(
                "/settings",
                data={"openai_model": "gpt-test"},
                follow_redirects=False,
            )
            self.assertEqual(response.status_code, 403)
            self.assertEqual(repo.get_settings_map(), {})

    def test_settings_task_and_review_flow(self) -> None:
        app = create_app()
        with TestClient(app) as client:
            csrf = login(client, "/settings")
            settings_response = client.post(
                "/settings",
                data={
                    "csrf_token": csrf,
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
            self.assertIn("测试模式：采集 dry-run 跳过 Dify 强制检查", settings_page.text)
            csrf = csrf_from(settings_page.text)

            task_response = client.post(
                "/tasks",
                data={
                    "csrf_token": csrf,
                    "name": "任务",
                    "query": "最近一周网络热梗",
                    "schedule_kind": "every_hours",
                    "interval_hours": "1",
                    "freshness": "week",
                    "max_candidates": "10",
                    "enabled": "on",
                },
                follow_redirects=False,
            )
            self.assertEqual(task_response.status_code, 303)
            self.assertEqual(len(repo.list_tasks()), 1)
            self.assertEqual(repo.list_tasks()[0]["schedule_cron"], "0 */1 * * *")

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
            csrf = csrf_from(pending_page.text)

            approve_response = client.post(
                "/pending/approve",
                data={"csrf_token": csrf, "candidate_id": str(candidate_id)},
                follow_redirects=False,
            )
            self.assertEqual(approve_response.status_code, 303)
            status = repo.get_candidates([candidate_id])[0]["status"]
            self.assertEqual(status, CandidateStatus.APPROVED)

    def test_task_direct_edit_delete_and_scheduler_reload(self) -> None:
        app = create_app()
        fake_scheduler = FakeScheduler()
        with TestClient(app) as client:
            app.state.scheduler_service = fake_scheduler
            csrf = login(client, "/tasks")
            create_response = client.post(
                "/tasks",
                data={
                    "csrf_token": csrf,
                    "name": "旧任务",
                    "query": "旧 query",
                    "schedule_kind": "daily",
                    "daily_time": "08:30",
                    "freshness": "week",
                    "max_candidates": "5",
                    "enabled": "on",
                },
                follow_redirects=False,
            )
            self.assertEqual(create_response.status_code, 303)
            task = repo.list_tasks()[0]
            self.assertEqual(task["schedule_cron"], "30 8 * * *")
            self.assertEqual(fake_scheduler.reloads, 1)

            csrf = csrf_from(client.get("/tasks").text)
            edit_response = client.post(
                "/tasks",
                data={
                    "csrf_token": csrf,
                    "task_id": str(task["id"]),
                    "name": "新任务",
                    "query": "新 query",
                    "schedule_kind": "weekly",
                    "weekly_day": "fri",
                    "weekly_time": "18:45",
                    "freshness": "day",
                    "max_candidates": "7",
                    "enabled": "on",
                },
                follow_redirects=False,
            )
            self.assertEqual(edit_response.status_code, 303)
            edited = repo.get_task(task["id"])
            self.assertIsNotNone(edited)
            self.assertEqual(edited["name"], "新任务")
            self.assertEqual(edited["schedule_cron"], "45 18 * * fri")
            self.assertEqual(fake_scheduler.reloads, 2)

            run_id = repo.create_run(task["id"], "completed")
            csrf = csrf_from(client.get("/tasks").text)
            delete_response = client.post(
                f"/tasks/{task['id']}/delete",
                data={"csrf_token": csrf, "confirm_delete": str(task["id"])},
                follow_redirects=False,
            )
            self.assertEqual(delete_response.status_code, 303)
            self.assertIsNone(repo.get_task(task["id"]))
            self.assertEqual(fake_scheduler.reloads, 3)
            runs_page = client.get("/runs")
            self.assertIn(f"#{run_id}", runs_page.text)
            self.assertIn("<td>-</td>", runs_page.text)

    def test_legacy_custom_cron_renders_and_invalid_schedule_rejected(self) -> None:
        repo.save_task(
            task=CollectionTaskIn(
                name="Legacy",
                query="q",
                schedule_cron="15 10 1 * *",
                max_candidates=5,
            )
        )
        app = create_app()
        with TestClient(app) as client:
            csrf = login(client, "/tasks")
            tasks_page = client.get("/tasks")
            self.assertIn("legacy/custom", tasks_page.text)
            self.assertIn("15 10 1 * *", tasks_page.text)
            response = client.post(
                "/tasks",
                data={
                    "csrf_token": csrf,
                    "name": "Bad",
                    "query": "q",
                    "schedule_kind": "custom",
                    "custom_cron": "bad cron",
                    "max_candidates": "5",
                    "freshness": "week",
                    "enabled": "on",
                },
            )
            self.assertEqual(response.status_code, 200)
            self.assertIn("无效定时规则", response.text)
            self.assertEqual(len(repo.list_tasks()), 1)

    def test_settings_checkbox_persists_true_and_explicit_false(self) -> None:
        app = create_app()
        with TestClient(app) as client:
            csrf = login(client, "/settings")
            enabled_response = client.post(
                "/settings",
                data={
                    "csrf_token": csrf,
                    "openai_model": "gpt-test",
                    "dify_base_url": "https://api.dify.ai/v1",
                    "dify_skip_check_for_dry_run": "on",
                },
                follow_redirects=False,
            )
            self.assertEqual(enabled_response.status_code, 303)
            self.assertEqual(repo.get_settings_map()["dify_skip_check_for_dry_run"], "true")
            page = client.get("/settings").text
            self.assertIn('name="dify_skip_check_for_dry_run" type="checkbox" checked', page)
            csrf = csrf_from(page)

            disabled_response = client.post(
                "/settings",
                data={
                    "csrf_token": csrf,
                    "openai_model": "gpt-test",
                    "dify_base_url": "https://api.dify.ai/v1",
                },
                follow_redirects=False,
            )
            self.assertEqual(disabled_response.status_code, 303)
            self.assertEqual(repo.get_settings_map()["dify_skip_check_for_dry_run"], "false")
            settings_page = client.get("/settings").text
            self.assertNotIn(
                'name="dify_skip_check_for_dry_run" type="checkbox" checked', settings_page
            )
            self.assertIn("不影响写入 Dify", settings_page)

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
            patch(
                "meme_collector_app.services.scheduler.run_collection",
                side_effect=fake_run_collection,
            ),
            patch("meme_collector_app.services.collector.make_dify_client", return_value=fake_dify),
            TestClient(app) as client,
        ):
            csrf = login(client, "/settings")
            settings_response = client.post(
                "/settings",
                data={
                    "csrf_token": csrf,
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
            csrf = csrf_from(client.get("/tasks").text)

            task_response = client.post(
                "/tasks",
                data={
                    "csrf_token": csrf,
                    "name": "E2E 任务",
                    "query": "最近一周网络热梗",
                    "schedule_kind": "every_hours",
                    "interval_hours": "1",
                    "freshness": "week",
                    "max_candidates": "5",
                    "enabled": "on",
                },
                follow_redirects=False,
            )
            self.assertEqual(task_response.status_code, 303)
            task_id = repo.list_tasks()[0]["id"]
            csrf = csrf_from(client.get("/tasks").text)

            run_response = client.post(
                f"/tasks/{task_id}/run", data={"csrf_token": csrf}, follow_redirects=False
            )
            self.assertEqual(run_response.status_code, 303)
            pending_page = client.get("/pending")
            self.assertIn("端到端热梗", pending_page.text)
            self.assertIn("https://example.com/e2e", pending_page.text)
            csrf = csrf_from(pending_page.text)

            candidate_id = repo.list_candidates("pending")[0]["id"]
            approve_response = client.post(
                "/pending/approve",
                data={"csrf_token": csrf, "candidate_id": str(candidate_id)},
                follow_redirects=False,
            )
            self.assertEqual(approve_response.status_code, 303)
            csrf = csrf_from(client.get("/pending").text)

            write_response = client.post(
                "/write",
                data={"csrf_token": csrf, "candidate_id": str(candidate_id)},
            )
            self.assertEqual(write_response.status_code, 200)
            self.assertIn("doc-web-e2e", write_response.text)
            self.assertEqual(fake_dify.list_calls, 1)
            self.assertEqual(fake_dify.uploaded[0][0], "端到端热梗")
            self.assertIn("## 基本信息", fake_dify.uploaded[0][1])

        restarted_app = create_app()
        with TestClient(restarted_app) as restarted:
            login(restarted, "/tasks")
            self.assertIn("E2E 任务", restarted.get("/tasks").text)
            settings_after_restart = restarted.get("/settings").text
            self.assertIn("sk-e...enai", settings_after_restart)
            self.assertIn("https://llm.example.test/v1", settings_after_restart)
            pending_after_restart = restarted.get("/pending")
            self.assertIn("端到端热梗", pending_after_restart.text)
            self.assertIn("doc-web-e2e", pending_after_restart.text)
            written_status = repo.get_candidates([candidate_id])[0]["status"]
            self.assertEqual(written_status, CandidateStatus.WRITTEN)


if __name__ == "__main__":
    unittest.main()
