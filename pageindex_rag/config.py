"""Settings, read from the environment (.env is loaded, never printed)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default)


@dataclass(frozen=True)
class Settings:
    openrouter_key: str = field(default_factory=lambda: _env("OPENROUTER_KEY"))
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    # Cheap model: node summaries + figure descriptions at index time
    cheap_model: str = field(default_factory=lambda: _env("PAGEINDEX_CHEAP_MODEL", "openai/gpt-6-luna"))
    # Strong model: tree navigation + answering at query time
    reasoning_model: str = field(default_factory=lambda: _env("PAGEINDEX_REASONING_MODEL", "openai/gpt-6.1-sol"))
    # Dedicated container `pageindex_pg` (pgvector/pgvector:pg17), separate from the app's DBs
    db_url: str = field(default_factory=lambda: _env(
        "PAGEINDEX_DB_URL", "postgresql://pageindex:pageindex@127.0.0.1:5534/pageindex"))
    llm_concurrency: int = 8
    summary_batch_tokens: int = 60_000  # rough token budget per summarize call


settings = Settings()
