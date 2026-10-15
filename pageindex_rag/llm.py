"""Thin OpenRouter client (OpenAI-compatible Chat Completions) with cost tracking."""

from __future__ import annotations

import asyncio
import base64
from pathlib import Path
from typing import TypeVar

from openai import AsyncOpenAI
from pydantic import BaseModel

from .config import settings

T = TypeVar("T", bound=BaseModel)


class LLM:
    def __init__(self, concurrency: int = settings.llm_concurrency):
        if not settings.openrouter_key:
            raise RuntimeError("OPENROUTER_KEY is not set")
        self.client = AsyncOpenAI(base_url=settings.openrouter_base_url, api_key=settings.openrouter_key,
                                  max_retries=4)
        self._sem = asyncio.Semaphore(concurrency)
        self.cost_usd = 0.0
        self.calls = 0

    def _track(self, usage) -> None:
        self.calls += 1
        self.cost_usd += float(getattr(usage, "cost", 0) or 0)  # OpenRouter usage accounting

    async def structured(self, model: str, system: str, user: str | list, schema: type[T],
                         max_tokens: int = 8192) -> T:
        """One call constrained to a Pydantic schema (JSON-schema structured output)."""
        async with self._sem:
            resp = await self.client.chat.completions.parse(
                model=model,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                response_format=schema,
                max_tokens=max_tokens,
                extra_body={"usage": {"include": True}},
            )
        self._track(resp.usage)
        parsed = resp.choices[0].message.parsed
        if parsed is None:
            raise ValueError(f"{model} returned no parseable output: {resp.choices[0].finish_reason}")
        return parsed

    async def text(self, model: str, system: str, user: str | list, max_tokens: int = 400) -> str:
        async with self._sem:
            resp = await self.client.chat.completions.create(
                model=model,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                max_tokens=max_tokens,
                extra_body={"usage": {"include": True}},
            )
        self._track(resp.usage)
        return (resp.choices[0].message.content or "").strip()


def image_part(path: Path) -> dict:
    data = base64.b64encode(path.read_bytes()).decode()
    return {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{data}"}}
