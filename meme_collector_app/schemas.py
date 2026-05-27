"""Pydantic schemas and markdown rendering for meme candidates."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field, HttpUrl, field_validator


class CandidateStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    WRITTEN = "written"
    REJECTED = "rejected"
    FAILED = "failed"


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class MemeCandidate(BaseModel):
    """Structured meme record before rendering to the Dify markdown format."""

    name: str = Field(min_length=1, max_length=120, description="简短、易识别的梗名称")
    meme_type: str = Field(description="音频梗/视频梗/流行语/梗图/表情包")
    heat_level: str = Field(description="🔥🔥🔥/🔥🔥/🔥")
    popularity_period: str = Field(description="例如 2026上半年、最近一周")
    derivative_potential: str = Field(description="高/中/低")
    platforms: list[str] = Field(min_length=1, description="主要传播平台")
    meaning: str = Field(min_length=10, description="2-4 句话解释含义、背景和流行原因")
    catchphrases: list[str] = Field(default_factory=list, description="经典台词/用法")
    origin: str = Field(min_length=1, description="出处来源")
    emotion_tags: list[str] = Field(default_factory=list)
    scenarios: list[str] = Field(default_factory=list)
    usage_examples: list[str] = Field(min_length=1)
    script_integration_guide: str = Field(min_length=10)
    source_urls: list[HttpUrl | str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0, le=1)

    @field_validator("heat_level")
    @classmethod
    def validate_heat_level(cls, value: str) -> str:
        allowed = {"🔥🔥🔥", "🔥🔥", "🔥"}
        if value not in allowed:
            raise ValueError("heat_level must be one of 🔥🔥🔥/🔥🔥/🔥")
        return value

    @field_validator("derivative_potential")
    @classmethod
    def validate_derivative_potential(cls, value: str) -> str:
        allowed = {"高", "中", "低"}
        if value not in allowed:
            raise ValueError("derivative_potential must be 高/中/低")
        return value


class CandidateRecord(BaseModel):
    id: int
    name: str
    markdown: str
    status: CandidateStatus
    source_urls: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    created_at: datetime | None = None
    updated_at: datetime | None = None
    dify_document_id: str | None = None
    error: str | None = None


class CollectionTaskIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    query: str = Field(default="最近一周网络热梗 盘点")
    schedule_cron: str = Field(default="0 */12 * * *", description="minute hour day month day_of_week")
    max_candidates: int = Field(default=20, ge=1, le=50)
    freshness: str = Field(default="week")
    enabled: bool = True


class WriteResult(BaseModel):
    success: int = 0
    skipped: int = 0
    failed: int = 0
    messages: list[str] = Field(default_factory=list)


def render_meme_markdown(candidate: MemeCandidate) -> str:
    """Render a structured candidate into the Dify knowledge-base markdown format."""

    quotes = " ".join(f'"{quote}"' for quote in candidate.catchphrases) or "（暂无明确金句）"
    examples = "\n".join(f"- {example}" for example in candidate.usage_examples)
    platforms = "、".join(candidate.platforms)
    emotions = "、".join(candidate.emotion_tags) or "搞笑、调侃"
    scenarios = "、".join(candidate.scenarios) or "日常、社交"
    sources = "\n".join(f"- {url}" for url in candidate.source_urls)
    source_block = f"\n\n参考链接：\n{sources}" if sources else ""

    return f"""# {candidate.name}

## 基本信息
- 梗类型：{candidate.meme_type}
- 热度等级：{candidate.heat_level}
- 流行时间：{candidate.popularity_period}
- 二创潜力：{candidate.derivative_potential}
- 平台来源：{platforms}

## 含义解释
{candidate.meaning}

## 金句台词
{quotes}

## 出处来源
{candidate.origin}{source_block}

## 情感标签
{emotions}

## 适用场景
{scenarios}

## 使用场景示例
{examples}

## 剧本融入指南
{candidate.script_integration_guide}
""".strip()
