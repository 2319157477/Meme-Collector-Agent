"""Repository functions for SQLite-backed app state."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from meme_collector_app.db.session import connect
from meme_collector_app.schemas import CandidateStatus, CollectionTaskIn, MemeCandidate, render_meme_markdown
from meme_collector_app.services.dedupe import normalize_name

SECRET_KEYS = {"openai_api_key", "anysearch_api_key", "tavily_api_key", "dify_api_key"}


def get_settings_map(include_secrets: bool = True) -> dict[str, str]:
    with connect() as conn:
        rows = conn.execute("SELECT key, value, secret FROM app_settings").fetchall()
    result: dict[str, str] = {}
    for row in rows:
        if row["secret"] and not include_secrets:
            result[row["key"]] = ""
        else:
            result[row["key"]] = row["value"]
    return result


def save_settings(values: dict[str, str]) -> None:
    with connect() as conn:
        for key, value in values.items():
            if value is None or key.endswith("_masked"):
                continue
            secret = 1 if key in SECRET_KEYS else 0
            conn.execute(
                """
                INSERT INTO app_settings(key, value, secret, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value, secret=excluded.secret,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (key, str(value), secret),
            )


def list_tasks() -> list[sqlite3.Row]:
    with connect() as conn:
        return list(conn.execute("SELECT * FROM collection_tasks ORDER BY id DESC"))


def get_task(task_id: int) -> sqlite3.Row | None:
    with connect() as conn:
        return conn.execute("SELECT * FROM collection_tasks WHERE id = ?", (task_id,)).fetchone()


def save_task(task: CollectionTaskIn, task_id: int | None = None) -> int:
    with connect() as conn:
        if task_id:
            conn.execute(
                """
                UPDATE collection_tasks
                SET name=?, query=?, schedule_cron=?, max_candidates=?, freshness=?, enabled=?,
                    updated_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (
                    task.name,
                    task.query,
                    task.schedule_cron,
                    task.max_candidates,
                    task.freshness,
                    int(task.enabled),
                    task_id,
                ),
            )
            return task_id
        cursor = conn.execute(
            """
            INSERT INTO collection_tasks(name, query, schedule_cron, max_candidates, freshness, enabled)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                task.name,
                task.query,
                task.schedule_cron,
                task.max_candidates,
                task.freshness,
                int(task.enabled),
            ),
        )
        return int(cursor.lastrowid)


def delete_task(task_id: int) -> bool:
    with connect() as conn:
        cursor = conn.execute("DELETE FROM collection_tasks WHERE id = ?", (task_id,))
        return cursor.rowcount > 0


def create_run(task_id: int | None, status: str = "running") -> int:
    with connect() as conn:
        cursor = conn.execute(
            "INSERT INTO collection_runs(task_id, status) VALUES (?, ?)", (task_id, status)
        )
        return int(cursor.lastrowid)


def has_active_run(task_id: int) -> bool:
    with connect() as conn:
        row = conn.execute(
            """
            SELECT id FROM collection_runs
            WHERE task_id = ? AND status IN ('queued', 'running')
            LIMIT 1
            """,
            (task_id,),
        ).fetchone()
    return row is not None


def create_run_or_skip(task_id: int) -> tuple[int, bool]:
    """Atomically create a running run or a skipped run when one is already active."""

    def active_exists(conn: sqlite3.Connection) -> bool:
        return (
            conn.execute(
                """
                SELECT id FROM collection_runs
                WHERE task_id = ? AND status IN ('queued', 'running')
                LIMIT 1
                """,
                (task_id,),
            ).fetchone()
            is not None
        )

    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        if active_exists(conn):
            cursor = conn.execute(
                """
                INSERT INTO collection_runs(task_id, status, finished_at, log)
                VALUES (?, 'skipped', CURRENT_TIMESTAMP,
                        'Skipped because another run is already active for this task')
                """,
                (task_id,),
            )
            return int(cursor.lastrowid), False

        cursor = conn.execute(
            "INSERT INTO collection_runs(task_id, status) VALUES (?, 'running')", (task_id,)
        )
        return int(cursor.lastrowid), True


def finish_run(
    run_id: int,
    status: str,
    *,
    found_count: int = 0,
    inserted_count: int = 0,
    skipped_count: int = 0,
    error: str | None = None,
    log: str | None = None,
) -> None:
    with connect() as conn:
        conn.execute(
            """
            UPDATE collection_runs
            SET status=?, finished_at=CURRENT_TIMESTAMP, found_count=?, inserted_count=?,
                skipped_count=?, error=?, log=?
            WHERE id=?
            """,
            (status, found_count, inserted_count, skipped_count, error, log, run_id),
        )


def list_runs(limit: int = 20) -> list[sqlite3.Row]:
    with connect() as conn:
        return list(
            conn.execute(
                """
                SELECT r.*, t.name AS task_name
                FROM collection_runs r
                LEFT JOIN collection_tasks t ON t.id = r.task_id
                ORDER BY r.id DESC LIMIT ?
                """,
                (limit,),
            )
        )


def insert_candidate(run_id: int | None, candidate: MemeCandidate) -> int | None:
    normalized = normalize_name(candidate.name)
    markdown = render_meme_markdown(candidate)
    payload = candidate.model_dump(mode="json")
    source_urls = [str(url) for url in candidate.source_urls]
    with connect() as conn:
        existing = conn.execute(
            "SELECT id FROM meme_candidates WHERE normalized_name = ? AND status != 'rejected'",
            (normalized,),
        ).fetchone()
        if existing:
            return None
        cursor = conn.execute(
            """
            INSERT INTO meme_candidates(
                run_id, name, normalized_name, markdown, structured_json, source_urls_json,
                confidence, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')
            """,
            (
                run_id,
                candidate.name,
                normalized,
                markdown,
                json.dumps(payload, ensure_ascii=False),
                json.dumps(source_urls, ensure_ascii=False),
                candidate.confidence,
            ),
        )
        return int(cursor.lastrowid)


def list_candidates(status: str | None = None, limit: int = 100) -> list[sqlite3.Row]:
    sql = "SELECT * FROM meme_candidates"
    args: tuple[Any, ...] = ()
    if status:
        sql += " WHERE status = ?"
        args = (status,)
    sql += " ORDER BY id DESC LIMIT ?"
    args = (*args, limit)
    with connect() as conn:
        return list(conn.execute(sql, args))


def get_candidates(candidate_ids: list[int]) -> list[sqlite3.Row]:
    if not candidate_ids:
        return []
    placeholders = ",".join("?" for _ in candidate_ids)
    with connect() as conn:
        return list(
            conn.execute(f"SELECT * FROM meme_candidates WHERE id IN ({placeholders})", candidate_ids)
        )


def update_candidate_status(
    candidate_id: int,
    status: CandidateStatus | str,
    *,
    dify_document_id: str | None = None,
    error: str | None = None,
) -> None:
    with connect() as conn:
        conn.execute(
            """
            UPDATE meme_candidates
            SET status=?, dify_document_id=COALESCE(?, dify_document_id), error=?,
                updated_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (str(status), dify_document_id, error, candidate_id),
        )


def candidate_names_by_status(statuses: tuple[str, ...] = ("pending", "approved", "written")) -> set[str]:
    placeholders = ",".join("?" for _ in statuses)
    with connect() as conn:
        rows = conn.execute(
            f"SELECT normalized_name FROM meme_candidates WHERE status IN ({placeholders})", statuses
        ).fetchall()
    return {row["normalized_name"] for row in rows}
