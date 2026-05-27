"""FastAPI routes and server-rendered WebUI."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from meme_collector_app.core.config import get_settings, mask_secret, parse_bool
from meme_collector_app.db import repositories as repo
from meme_collector_app.schemas import CandidateStatus, CollectionTaskIn, WriteResult
from meme_collector_app.services.collector import write_approved

TEMPLATE_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
router = APIRouter()

CONFIG_KEYS = [
    "openai_model",
    "openai_api_key",
    "openai_base_url",
    "anysearch_api_key",
    "dify_base_url",
    "dify_dataset_id",
    "dify_api_key",
    "dify_proxy",
]
BOOL_CONFIG_KEYS = [
    "dify_skip_check_for_dry_run",
]
SECRET_KEYS = {"openai_api_key", "anysearch_api_key", "dify_api_key"}


def _html(request: Request, template: str, context: dict[str, object]) -> HTMLResponse:
    context.setdefault("request", request)
    return templates.TemplateResponse(request, template, context)


def _candidate_views(status: str, limit: int = 100) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    for row in repo.list_candidates(status, limit):
        item = dict(row)
        try:
            item["source_urls"] = json.loads(row["source_urls_json"] or "[]")
        except json.JSONDecodeError:
            item["source_urls"] = []
        items.append(item)
    return items


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    return _html(
        request,
        "index.html",
        {
            "tasks": repo.list_tasks(),
            "runs": repo.list_runs(5),
            "pending": repo.list_candidates("pending", 10),
        },
    )


@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request) -> HTMLResponse:
    env = get_settings()
    saved = repo.get_settings_map(include_secrets=True)
    values: dict[str, str] = {}
    masked: dict[str, str] = {}
    bool_values: dict[str, bool] = {}
    for key in CONFIG_KEYS:
        value = saved.get(key) or str(getattr(env, key, "") or "")
        values[key] = value if key not in SECRET_KEYS else ""
        masked[key] = mask_secret(value) if key in SECRET_KEYS else value
    for key in BOOL_CONFIG_KEYS:
        if key in saved:
            bool_values[key] = parse_bool(saved.get(key), default=False)
        else:
            bool_values[key] = parse_bool(getattr(env, key, False), default=False)
    return _html(
        request, "settings.html", {"values": values, "masked": masked, "bool_values": bool_values}
    )


@router.post("/settings")
async def save_settings(request: Request) -> RedirectResponse:
    form = await request.form()
    current = repo.get_settings_map(include_secrets=True)
    values: dict[str, str] = {}
    for key in CONFIG_KEYS:
        raw = str(form.get(key, "")).strip()
        if key in SECRET_KEYS and not raw:
            if key in current:
                continue
        values[key] = raw
    for key in BOOL_CONFIG_KEYS:
        values[key] = "true" if form.get(key) else "false"
    repo.save_settings(values)
    return RedirectResponse("/settings", status_code=303)


@router.get("/tasks", response_class=HTMLResponse)
def tasks_page(request: Request) -> HTMLResponse:
    return _html(request, "tasks.html", {"tasks": repo.list_tasks()})


@router.post("/tasks")
async def save_task(request: Request) -> RedirectResponse:
    form = await request.form()
    task = CollectionTaskIn(
        name=str(form.get("name") or "默认热梗收集"),
        query=str(form.get("query") or "最近一周网络热梗 盘点"),
        schedule_cron=str(form.get("schedule_cron") or "0 */12 * * *"),
        max_candidates=int(form.get("max_candidates") or 20),
        freshness=str(form.get("freshness") or "week"),
        enabled=bool(form.get("enabled")),
    )
    task_id_raw = form.get("task_id")
    task_id = int(task_id_raw) if task_id_raw else None
    repo.save_task(task, task_id)
    if hasattr(request.app.state, "scheduler_service"):
        request.app.state.scheduler_service.reload_jobs()
    return RedirectResponse("/tasks", status_code=303)


@router.post("/tasks/{task_id}/run")
async def run_task_now(request: Request, task_id: int) -> RedirectResponse:
    if hasattr(request.app.state, "scheduler_service"):
        await request.app.state.scheduler_service.run_now(task_id)
    return RedirectResponse("/runs", status_code=303)


@router.get("/runs", response_class=HTMLResponse)
def runs_page(request: Request) -> HTMLResponse:
    return _html(request, "runs.html", {"runs": repo.list_runs(50)})


@router.get("/pending", response_class=HTMLResponse)
def pending_page(request: Request) -> HTMLResponse:
    return _html(
        request,
        "pending.html",
        {
            "pending": _candidate_views("pending", 100),
            "approved": _candidate_views("approved", 100),
            "failed": _candidate_views("failed", 100),
            "written": _candidate_views("written", 50),
        },
    )


@router.post("/pending/approve")
async def approve_candidates(request: Request) -> RedirectResponse:
    form = await request.form()
    ids = [int(value) for value in form.getlist("candidate_id")]
    for candidate_id in ids:
        repo.update_candidate_status(candidate_id, CandidateStatus.APPROVED)
    return RedirectResponse("/pending", status_code=303)


@router.post("/pending/reject")
async def reject_candidates(request: Request) -> RedirectResponse:
    form = await request.form()
    ids = [int(value) for value in form.getlist("candidate_id")]
    for candidate_id in ids:
        repo.update_candidate_status(candidate_id, CandidateStatus.REJECTED)
    return RedirectResponse("/pending", status_code=303)


@router.post("/write")
async def write_candidates(request: Request) -> HTMLResponse:
    form = await request.form()
    ids = [int(value) for value in form.getlist("candidate_id")]
    try:
        result = await write_approved(ids)
    except Exception as exc:  # noqa: BLE001 - show operator-facing write failure
        result = WriteResult(failed=len(ids), messages=[f"write failed: {exc}"])
    return _html(request, "write_result.html", {"result": result})


