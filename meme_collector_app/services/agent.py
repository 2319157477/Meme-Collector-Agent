"""Agent-backed meme extraction service."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Protocol

from meme_collector_app.schemas import MemeCandidate
from meme_collector_app.services.mcp_servers import McpConfig, McpServerBundle

try:
    from agents import Agent, RunConfig, Runner
    from agents.models.openai_provider import OpenAIProvider
except Exception:  # pragma: no cover - import environment dependent
    Agent = None  # type: ignore[assignment]
    RunConfig = None  # type: ignore[assignment]
    Runner = None  # type: ignore[assignment]
    OpenAIProvider = None  # type: ignore[assignment]

try:
    from agents.exceptions import UserError
except Exception:  # pragma: no cover - older SDK or import environment dependent
    UserError = RuntimeError  # type: ignore[assignment]

PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "meme_extractor.md"


class MemeAgent(Protocol):
    async def collect(
        self,
        *,
        query: str,
        max_candidates: int,
        freshness: str,
        existing_names: list[str],
    ) -> list[MemeCandidate]: ...


class OpenAIMemeAgent:
    """Use OpenAI Agents SDK plus MCP tools to collect and structure meme candidates."""

    def __init__(
        self,
        *,
        model: str,
        openai_api_key: str | None,
        openai_base_url: str | None,
        anysearch_api_key: str | None,
        anysearch_mcp_url: str,
        anysearch_proxy: str | None,
    ) -> None:
        self.model = model
        self.openai_api_key = openai_api_key
        self.openai_base_url = openai_base_url
        self.mcp_config = McpConfig(
            anysearch_api_key=anysearch_api_key,
            anysearch_mcp_url=anysearch_mcp_url,
            anysearch_proxy=anysearch_proxy,
        )

    async def collect(
        self,
        *,
        query: str,
        max_candidates: int,
        freshness: str,
        existing_names: list[str],
    ) -> list[MemeCandidate]:
        if Agent is None or Runner is None:
            raise RuntimeError("OpenAI Agents SDK is unavailable")

        instructions = PROMPT_PATH.read_text(encoding="utf-8")
        user_input = {
            "query": query,
            "max_candidates": max_candidates,
            "freshness": freshness,
            "existing_names": existing_names,
            "search_provider": "AnySearch MCP only",
            "fetch_provider": "AnySearch MCP extract only",
        }
        bundle_context = McpServerBundle(self.mcp_config)
        try:
            bundle = await bundle_context.__aenter__()
            agent = Agent(
                name="meme-collector",
                model=self.model,
                instructions=instructions,
                mcp_servers=bundle.servers,
                mcp_config={"include_server_in_tool_names": True},
            )
            original_env = {
                "OPENAI_API_KEY": os.environ.get("OPENAI_API_KEY"),
                "OPENAI_BASE_URL": os.environ.get("OPENAI_BASE_URL"),
            }
            if self.openai_api_key:
                os.environ["OPENAI_API_KEY"] = self.openai_api_key
            if self.openai_base_url:
                os.environ["OPENAI_BASE_URL"] = self.openai_base_url
            try:
                result = await Runner.run(
                    agent,
                    json.dumps(user_input, ensure_ascii=False),
                    run_config=self._run_config(),
                )
            finally:
                for key, value in original_env.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value
        except (UserError, OSError) as exc:
            raise RuntimeError(
                "AnySearch MCP server is unreachable. Check network/DNS/firewall access to "
                f"{self.mcp_config.anysearch_mcp_url}, or configure ANYSEARCH_PROXY / "
                "ANYSEARCH_MCP_URL in /settings or the environment. "
                f"Original error: {exc}"
            ) from exc
        finally:
            await bundle_context.__aexit__(None, None, None)
        return parse_candidates(str(result.final_output))

    def _run_config(self):
        if not (self.openai_api_key or self.openai_base_url):
            return None
        if RunConfig is None or OpenAIProvider is None:
            return None
        provider = OpenAIProvider(api_key=self.openai_api_key, base_url=self.openai_base_url)
        return RunConfig(model_provider=provider)


def parse_candidates(raw: str) -> list[MemeCandidate]:
    """Parse an agent JSON response into validated candidates."""

    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].strip()
    data = json.loads(text)
    if isinstance(data, dict):
        data = data.get("candidates", [])
    if not isinstance(data, list):
        raise ValueError("agent output must be a JSON list or {candidates: [...]}")
    return [MemeCandidate.model_validate(item) for item in data]
