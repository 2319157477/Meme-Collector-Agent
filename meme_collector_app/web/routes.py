"""FastAPI routes and server-rendered WebUI."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from meme_collector_app.core.config import get_settings, mask_secret, parse_bool
from meme_collector_app.db import repositories as repo
from meme_collector_app.schemas import CandidateStatus, CollectionTaskIn, WriteResult
from meme_collector_app.services.collector import write_approved
from meme_collector_app.web.auth import (
    authenticate,
    clear_auth_cookie,
    csrf_token_for_request,
    current_username,
    require_admin,
    set_auth_cookie,
    set_csrf_cookie,
    verify_csrf,
)
from meme_collector_app.web.schedule import (
    build_cron_from_form,
    cron_to_schedule_view,
    schedule_options,
)

TEMPLATE_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
router = APIRouter()
public_router = APIRouter()
protected_router = APIRouter(dependencies=[Depends(require_admin)])

CONFIG_KEYS = [
    "openai_model",
    "openai_api_key",
    "openai_base_url",
    "openai_proxy",
    "anysearch_api_key",
    "anysearch_mcp_url",
    "anysearch_proxy",
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
    username = current_username(request)
    context.setdefault("current_username", username)
    if username:
        csrf_token = csrf_token_for_request(request)
        context.setdefault("csrf_token", csrf_token)
    response = templates.TemplateResponse(request, template, context)
    if username:
        set_csrf_cookie(response, str(context["csrf_token"]))
    return response


def _safe_next_url(next_url: str | None) -> str:
    if not next_url or not next_url.startswith("/") or next_url.startswith("//"):
        return "/"
    return next_url


def _candidate_views(status_value: str, limit: int = 100) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    for row in repo.list_candidates(status_value, limit):
        item = dict(row)
        try:
            item["source_urls"] = json.loads(row["source_urls_json"] or "[]")
        except json.JSONDecodeError:
            item["source_urls"] = []
        items.append(item)
    return items


def _candidate_counts() -> dict[str, int]:
    return {
        status_value: len(repo.list_candidates(status_value, 1000))
        for status_value in ("pending", "approved", "failed", "written", "rejected")
    }


def _task_views() -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    for row in repo.list_tasks():
        task = dict(row)
        task["schedule"] = cron_to_schedule_view(task["schedule_cron"])
        tasks.append(task)
    return tasks


def _reload_scheduler(request: Request) -> None:
    if hasattr(request.app.state, "scheduler_service"):
        request.app.state.scheduler_service.reload_jobs()


async def _form_with_csrf(request: Request):
    form = await request.form()
    verify_csrf(request, str(form.get("csrf_token") or ""))
    return form


def _tasks_context(error: str | None = None, message: str | None = None) -> dict[str, object]:
    return {
        "tasks": _task_views(),
        "schedule_options": schedule_options(),
        "error": error,
        "message": message,
    }


@public_router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@public_router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, next: str = "/") -> HTMLResponse:  # noqa: A002 - query name
    next_url = _safe_next_url(next)
    if current_username(request):
        return RedirectResponse(next_url, status_code=303)
    return _html(request, "login.html", {"next": next_url, "error": None})


@public_router.post("/login")
async def login(request: Request):
    form = await request.form()
    username = str(form.get("username") or "")
    password = str(form.get("password") or "")
    next_url = _safe_next_url(str(form.get("next") or "/"))
    if not authenticate(username, password):
        return _html(
            request,
            "login.html",
            {"next": next_url, "error": "用户名或密码不正确。"},
        )
    response = RedirectResponse(next_url, status_code=303)
    set_auth_cookie(response, username)
    return response


@protected_router.post("/logout")
async def logout(request: Request) -> RedirectResponse:
    await _form_with_csrf(request)
    response = RedirectResponse("/login", status_code=303)
    clear_auth_cookie(response)
    return response


@protected_router.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    tasks = repo.list_tasks()
    runs = repo.list_runs(5)
    counts = _candidate_counts()
    enabled_tasks = sum(1 for task in tasks if task["enabled"])
    return _html(
        request,
        "index.html",
        {
            "tasks": tasks,
            "enabled_tasks": enabled_tasks,
            "runs": runs,
            "candidate_counts": counts,
            "pending": repo.list_candidates("pending", 10),
        },
    )


@protected_router.get("/settings", response_class=HTMLResponse)
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


@protected_router.post("/settings")
async def save_settings(request: Request) -> RedirectResponse:
    form = await _form_with_csrf(request)
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


@protected_router.get("/tasks", response_class=HTMLResponse)
def tasks_page(request: Request) -> HTMLResponse:
    return _html(request, "tasks.html", _tasks_context())


@protected_router.post("/tasks")
async def save_task(request: Request):
    form = await _form_with_csrf(request)
    try:
        schedule_cron = build_cron_from_form(form)
        task = CollectionTaskIn(
            name=str(form.get("name") or "默认热梗收集"),
            query=str(form.get("query") or "最近一周网络热梗 盘点"),
            schedule_cron=schedule_cron,
            max_candidates=int(form.get("max_candidates") or 20),
            freshness=str(form.get("freshness") or "week"),
            enabled=bool(form.get("enabled")),
        )
        task_id_raw = form.get("task_id")
        task_id = int(task_id_raw) if task_id_raw else None
    except (TypeError, ValueError) as exc:
        return _html(request, "tasks.html", _tasks_context(error=str(exc)))
    repo.save_task(task, task_id)
    _reload_scheduler(request)
    return RedirectResponse("/tasks", status_code=303)


@protected_router.post("/tasks/{task_id}/delete")
async def delete_task(request: Request, task_id: int) -> RedirectResponse:
    form = await _form_with_csrf(request)
    if str(form.get("confirm_delete") or "") != str(task_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Delete confirmation failed"
        )
    repo.delete_task(task_id)
    _reload_scheduler(request)
    return RedirectResponse("/tasks", status_code=303)


@protected_router.post("/tasks/{task_id}/run")
async def run_task_now(request: Request, task_id: int) -> RedirectResponse:
    await _form_with_csrf(request)
    if hasattr(request.app.state, "scheduler_service"):
        await request.app.state.scheduler_service.run_now(task_id)
    return RedirectResponse("/runs", status_code=303)


@protected_router.get("/runs", response_class=HTMLResponse)
def runs_page(request: Request) -> HTMLResponse:
    return _html(request, "runs.html", {"runs": repo.list_runs(50)})


@protected_router.get("/pending", response_class=HTMLResponse)
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


@protected_router.post("/pending/approve")
async def approve_candidates(request: Request) -> RedirectResponse:
    form = await _form_with_csrf(request)
    ids = [int(value) for value in form.getlist("candidate_id")]
    for candidate_id in ids:
        repo.update_candidate_status(candidate_id, CandidateStatus.APPROVED)
    return RedirectResponse("/pending", status_code=303)


@protected_router.post("/pending/reject")
async def reject_candidates(request: Request) -> RedirectResponse:
    form = await _form_with_csrf(request)
    ids = [int(value) for value in form.getlist("candidate_id")]
    for candidate_id in ids:
        repo.update_candidate_status(candidate_id, CandidateStatus.REJECTED)
    return RedirectResponse("/pending", status_code=303)


@protected_router.post("/write")
async def write_candidates(request: Request) -> HTMLResponse:
    form = await _form_with_csrf(request)
    ids = [int(value) for value in form.getlist("candidate_id")]
    try:
        result = await write_approved(ids)
    except Exception as exc:  # noqa: BLE001 - show operator-facing write failure
        result = WriteResult(failed=len(ids), messages=[f"write failed: {exc}"])
    return _html(request, "write_result.html", {"result": result})


router.include_router(public_router)
router.include_router(protected_router)
