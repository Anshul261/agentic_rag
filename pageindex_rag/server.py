"""PageIndex API server.

    uv run uvicorn pageindex_rag.server:app --port 7777

CORS allows the Next.js dev UI (PAGEINDEX_UI_ORIGINS, comma-separated).
Chat memory uses a LangGraph Postgres checkpointer in the PageIndex database.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import router
from .auth import get_principal
from .config import settings
from .telemetry import setup_tracing


@asynccontextmanager
async def lifespan(app: FastAPI):
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from psycopg_pool import AsyncConnectionPool

    tracing = setup_tracing()
    async with AsyncConnectionPool(settings.db_url, max_size=10, open=True,
                                   kwargs={"autocommit": True, "prepare_threshold": 0}) as pool:
        checkpointer = AsyncPostgresSaver(pool)
        await checkpointer.setup()  # creates checkpoint tables on first run
        app.state.checkpointer = checkpointer
        print(f"[pageindex] ready · model {settings.reasoning_model} · prompt {settings.prompt_version} "
              f"· read mode {settings.read_mode} · tracing {'on' if tracing else 'off'}", flush=True)
        yield


app = FastAPI(title="PageIndex RAG", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("PAGEINDEX_UI_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(","),
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)
app.include_router(router, dependencies=[Depends(get_principal)])


@app.get("/health")
def health() -> dict:
    return dict(status="ok", model=settings.reasoning_model, prompt=settings.prompt_version)
