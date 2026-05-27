"""APScheduler integration for local periodic collection tasks."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from meme_collector_app.db import repositories as repo
from meme_collector_app.services.collector import run_collection


@dataclass
class SchedulerService:
    scheduler: AsyncIOScheduler

    def start(self) -> None:
        if not self.scheduler.running:
            self.scheduler.start()
        self.reload_jobs()

    def shutdown(self) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)

    def reload_jobs(self) -> None:
        self.scheduler.remove_all_jobs()
        for task in repo.list_tasks():
            if not task["enabled"]:
                continue
            try:
                trigger = CronTrigger.from_crontab(task["schedule_cron"])
            except ValueError:
                continue
            self.scheduler.add_job(
                run_collection,
                trigger=trigger,
                args=[task["id"]],
                id=f"collection-task-{task['id']}",
                replace_existing=True,
                max_instances=1,
                coalesce=True,
            )

    async def run_now(self, task_id: int) -> int:
        return await run_collection(task_id)


def create_scheduler_service() -> SchedulerService:
    return SchedulerService(AsyncIOScheduler(timezone="Asia/Shanghai"))
