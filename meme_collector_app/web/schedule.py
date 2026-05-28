"""Schedule form helpers that preserve APScheduler crontab compatibility."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol

from apscheduler.triggers.cron import CronTrigger


class FormLike(Protocol):
    def get(self, key: str, default: object | None = None) -> object | None: ...


@dataclass(frozen=True)
class ScheduleView:
    kind: str
    label: str
    cron: str
    interval_hours: int = 12
    time: str = "09:00"
    weekly_day: str = "mon"
    custom: bool = False


WEEKDAY_LABELS: Mapping[str, str] = {
    "mon": "周一",
    "tue": "周二",
    "wed": "周三",
    "thu": "周四",
    "fri": "周五",
    "sat": "周六",
    "sun": "周日",
}
def _str(form: FormLike, key: str, default: str = "") -> str:
    return str(form.get(key, default) or default).strip()


def _time_parts(value: str) -> tuple[int, int]:
    try:
        hour_raw, minute_raw = value.split(":", 1)
        hour = int(hour_raw)
        minute = int(minute_raw)
    except (ValueError, TypeError):
        raise ValueError("时间格式必须是 HH:MM") from None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError("时间必须在 00:00 到 23:59 之间")
    return hour, minute


def validate_cron(cron: str) -> str:
    normalized = " ".join(cron.strip().split())
    if not normalized:
        raise ValueError("定时规则不能为空")
    try:
        CronTrigger.from_crontab(normalized)
    except ValueError as exc:
        raise ValueError(f"无效定时规则：{normalized}") from exc
    return normalized


def build_cron_from_form(form: FormLike) -> str:
    kind = _str(form, "schedule_kind", "legacy")
    if kind == "every_hours":
        try:
            hours = int(_str(form, "interval_hours", "12"))
        except ValueError:
            raise ValueError("间隔小时必须是数字") from None
        if hours not in {1, 2, 3, 4, 6, 8, 12, 24}:
            raise ValueError("请选择支持的间隔小时")
        return validate_cron(f"0 */{hours} * * *")
    if kind == "daily":
        hour, minute = _time_parts(_str(form, "daily_time", "09:00"))
        return validate_cron(f"{minute} {hour} * * *")
    if kind == "weekly":
        day = _str(form, "weekly_day", "mon").lower()
        if day not in WEEKDAY_LABELS:
            raise ValueError("请选择有效的星期")
        hour, minute = _time_parts(_str(form, "weekly_time", "09:00"))
        return validate_cron(f"{minute} {hour} * * {day}")
    if kind == "custom":
        custom_cron = _str(form, "custom_cron") or _str(form, "schedule_cron", "0 */12 * * *")
        return validate_cron(custom_cron)
    return validate_cron(_str(form, "schedule_cron", "0 */12 * * *"))


def cron_to_schedule_view(cron: str) -> ScheduleView:
    normalized = " ".join((cron or "").strip().split()) or "0 */12 * * *"
    parts = normalized.split()
    try:
        validate_cron(normalized)
    except ValueError:
        return ScheduleView("custom", f"无法识别：{normalized}", normalized, custom=True)
    if len(parts) != 5:
        return ScheduleView("custom", normalized, normalized, custom=True)
    minute, hour, day, month, weekday = parts
    if minute == "0" and hour.startswith("*/") and day == month == weekday == "*":
        try:
            interval = int(hour[2:])
        except ValueError:
            interval = 12
        return ScheduleView("every_hours", f"每 {interval} 小时", normalized, interval_hours=interval)
    if day == month == weekday == "*" and hour.isdigit() and minute.isdigit():
        label_time = f"{int(hour):02d}:{int(minute):02d}"
        return ScheduleView("daily", f"每天 {label_time}", normalized, time=label_time)
    if day == month == "*" and weekday in WEEKDAY_LABELS and hour.isdigit() and minute.isdigit():
        label_time = f"{int(hour):02d}:{int(minute):02d}"
        return ScheduleView(
            "weekly",
            f"每{WEEKDAY_LABELS[weekday]} {label_time}",
            normalized,
            time=label_time,
            weekly_day=weekday,
        )
    return ScheduleView("custom", f"自定义：{normalized}", normalized, custom=True)


def schedule_options() -> dict[str, object]:
    return {
        "interval_hours": [1, 2, 3, 4, 6, 8, 12, 24],
        "weekdays": WEEKDAY_LABELS,
    }
