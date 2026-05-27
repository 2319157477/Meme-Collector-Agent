"""Collection orchestration and approved-write workflows."""

from __future__ import annotations

from dataclasses import dataclass

from meme_collector_app.core.config import get_settings, parse_bool
from meme_collector_app.db import repositories as repo
from meme_collector_app.schemas import CandidateStatus, RunStatus, WriteResult
from meme_collector_app.services.agent import MemeAgent, OpenAIMemeAgent
from meme_collector_app.services.dedupe import normalize_name
from meme_collector_app.services.dify import DifyClient, DifyConfig


@dataclass(frozen=True)
class RuntimeConfig:
    openai_model: str
    openai_api_key: str | None
    openai_base_url: str | None
    openai_proxy: str | None
    anysearch_api_key: str | None
    anysearch_mcp_url: str
    anysearch_proxy: str | None
    dify_base_url: str
    dify_dataset_id: str | None
    dify_api_key: str | None
    dify_proxy: str | None
    dify_skip_check_for_dry_run: bool


def load_runtime_config() -> RuntimeConfig:
    """Merge environment defaults with settings saved from the WebUI."""

    env = get_settings()
    saved = repo.get_settings_map(include_secrets=True)

    def pick(key: str, default: str | None = None) -> str | None:
        value = saved.get(key)
        if value:
            return value
        return getattr(env, key, default)

    def pick_bool(key: str, default: bool = False) -> bool:
        if key in saved:
            return parse_bool(saved.get(key), default=default)
        return parse_bool(getattr(env, key, default), default=default)

    return RuntimeConfig(
        openai_model=pick("openai_model", env.openai_model) or env.openai_model,
        openai_api_key=pick("openai_api_key"),
        openai_base_url=pick("openai_base_url"),
        openai_proxy=pick("openai_proxy"),
        anysearch_api_key=pick("anysearch_api_key"),
        anysearch_mcp_url=pick("anysearch_mcp_url", env.anysearch_mcp_url)
        or env.anysearch_mcp_url,
        anysearch_proxy=pick("anysearch_proxy"),
        dify_base_url=pick("dify_base_url", env.dify_base_url) or env.dify_base_url,
        dify_dataset_id=pick("dify_dataset_id"),
        dify_api_key=pick("dify_api_key"),
        dify_proxy=pick("dify_proxy"),
        dify_skip_check_for_dry_run=pick_bool(
            "dify_skip_check_for_dry_run", env.dify_skip_check_for_dry_run
        ),
    )


def make_dify_client(config: RuntimeConfig | None = None) -> DifyClient:
    config = config or load_runtime_config()
    if not config.dify_dataset_id or not config.dify_api_key:
        raise RuntimeError("Dify dataset id and API key are required")
    return DifyClient(
        DifyConfig(
            dataset_id=config.dify_dataset_id,
            api_key=config.dify_api_key,
            base_url=config.dify_base_url,
            proxy=config.dify_proxy,
        )
    )


def make_agent(config: RuntimeConfig | None = None) -> OpenAIMemeAgent:
    config = config or load_runtime_config()
    return OpenAIMemeAgent(
        model=config.openai_model,
        openai_api_key=config.openai_api_key,
        openai_base_url=config.openai_base_url,
        openai_proxy=config.openai_proxy,
        anysearch_api_key=config.anysearch_api_key,
        anysearch_mcp_url=config.anysearch_mcp_url,
        anysearch_proxy=config.anysearch_proxy,
    )


async def run_collection(task_id: int, *, agent: MemeAgent | None = None) -> int:
    """Run one collection task and insert reliable candidates as pending."""

    task = repo.get_task(task_id)
    if task is None:
        raise ValueError(f"task {task_id} not found")

    run_id, should_run = repo.create_run_or_skip(task_id)
    if not should_run:
        return run_id

    try:
        config = load_runtime_config()
        if config.dify_skip_check_for_dry_run:
            existing_dify_names: list[str] = []
        else:
            dify_client = make_dify_client(config)
            existing_dify_names = await dify_client.list_documents()
        existing_local = repo.candidate_names_by_status()
        collector_agent = agent or make_agent(config)
        candidates = await collector_agent.collect(
            query=task["query"],
            max_candidates=int(task["max_candidates"]),
            freshness=task["freshness"],
            existing_names=existing_dify_names,
        )

        inserted = 0
        skipped = 0
        existing_normalized = {normalize_name(name) for name in existing_dify_names} | existing_local
        for candidate in candidates:
            if normalize_name(candidate.name) in existing_normalized:
                skipped += 1
                continue
            new_id = repo.insert_candidate(run_id, candidate)
            if new_id is None:
                skipped += 1
            else:
                inserted += 1
                existing_normalized.add(normalize_name(candidate.name))
        repo.finish_run(
            run_id,
            RunStatus.COMPLETED.value,
            found_count=len(candidates),
            inserted_count=inserted,
            skipped_count=skipped,
            log=f"Inserted {inserted}, skipped {skipped}",
        )
    except Exception as exc:  # noqa: BLE001 - visible run failure
        repo.finish_run(run_id, RunStatus.FAILED.value, error=str(exc))
    return run_id


async def write_approved(candidate_ids: list[int], *, client: DifyClient | None = None) -> WriteResult:
    """Write selected approved candidates to Dify after human approval."""

    rows = repo.get_candidates(candidate_ids)
    writable = [row for row in rows if row["status"] == "approved"]
    if not writable:
        return WriteResult(messages=["no approved candidates selected"])

    dify = client or make_dify_client()
    result = WriteResult()
    existing = set(await dify.list_documents())
    existing_normalized = {normalize_name(item) for item in existing}
    for row in writable:
        name = row["name"]
        normalized = normalize_name(name)
        if normalized in existing_normalized:
            repo.update_candidate_status(row["id"], CandidateStatus.WRITTEN, error="Skipped duplicate")
            result.skipped += 1
            result.messages.append(f"skip duplicate: {name}")
            continue
        try:
            document_id = await dify.upload_document(name, row["markdown"])
        except Exception as exc:  # noqa: BLE001
            repo.update_candidate_status(row["id"], CandidateStatus.FAILED, error=str(exc))
            result.failed += 1
            result.messages.append(f"failed {name}: {exc}")
        else:
            repo.update_candidate_status(row["id"], CandidateStatus.WRITTEN, dify_document_id=document_id)
            existing_normalized.add(normalized)
            result.success += 1
            result.messages.append(f"uploaded {name}: {document_id}")
    return result
