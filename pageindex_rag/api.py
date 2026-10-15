"""FastAPI router: PageIndex Q&A with a live search-trace stream.

Mounted by agent-api.py behind its JWT dependency. Server-sent events:
  Trace   one structured trace event (see trace.py), as the agent works
  Answer  {answer, citations}
  Stats   {seconds, cost_usd, model_calls, tool_calls, run_id}
  Error   {error}
Each live run is saved under data/pageindex/runs/ so it can be replayed
(e.g. for demos) without calling the LLM again.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from pathlib import Path
from typing import AsyncIterator

from fastapi import APIRouter, Form, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse

from .runner import run_question
from .store import Store
from .tools import ToolContext
from .trace import TraceBuilder

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "pageindex"
RUNS_DIR = DATA_DIR / "runs"
SSE_HEADERS = {"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"}

router = APIRouter(prefix="/pageindex", tags=["pageindex"])


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.get("/collections")
def list_collections() -> JSONResponse:
    rows = Store().conn.execute(
        "select collection, count(*) from documents where collection not like 'bench%' "
        "group by collection order by collection").fetchall()
    return JSONResponse([dict(name=c, n_docs=n) for c, n in rows])


@router.get("/runs")
def list_runs() -> JSONResponse:
    runs = []
    for f in sorted(RUNS_DIR.glob("*.json"), reverse=True)[:50]:
        d = json.loads(f.read_text())
        runs.append(dict(run_id=f.stem, question=d["question"], collection=d["collection"]))
    return JSONResponse(runs)


@router.post("/query")
async def query(message: str = Form(...), collection: str = Form("litreview")) -> StreamingResponse:
    store = Store()
    if not store.list_documents(collection):
        raise HTTPException(404, f"collection {collection!r} is empty or does not exist")

    async def stream() -> AsyncIterator[str]:
        builder = TraceBuilder(ToolContext(store=store, collection=collection, data_dir=DATA_DIR))
        queue: asyncio.Queue[tuple[str, dict] | None] = asyncio.Queue()
        recorded: list[dict] = []
        t0 = time.time()

        def emit(event: str, data: dict) -> None:
            recorded.append(dict(t=round(time.time() - t0, 2), event=event, data=data))
            queue.put_nowait((event, data))

        def on_tool(name: str, arguments: str) -> None:
            if ev := builder.from_tool_call(name, arguments):
                emit("Trace", ev)

        async def work() -> None:
            try:
                emit("Trace", builder.start())
                r = await run_question(message, collection, DATA_DIR, store=store, on_tool=on_tool)
                if r.answer:
                    emit("Answer", dict(answer=r.answer.answer,
                                        citations=[c.model_dump() for c in r.answer.citations]))
                if r.error:
                    emit("Error", dict(error=r.error))
                run_id = f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
                emit("Stats", dict(seconds=round(r.seconds, 1), cost_usd=round(r.cost_usd + r.tool_llm_cost_usd, 4),
                                   model_calls=r.requests, tool_calls=len(r.tool_calls), run_id=run_id))
                RUNS_DIR.mkdir(parents=True, exist_ok=True)
                (RUNS_DIR / f"{run_id}.json").write_text(json.dumps(
                    dict(question=message, collection=collection, events=recorded), ensure_ascii=False))
            except Exception as e:  # surface failures to the client instead of a dropped stream
                emit("Error", dict(error=f"{type(e).__name__}: {e}"))
            finally:
                queue.put_nowait(None)

        task = asyncio.create_task(work())
        try:
            while (item := await queue.get()) is not None:
                yield _sse(*item)
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(stream(), media_type="text/event-stream", headers=SSE_HEADERS)


@router.post("/replay")
async def replay(run_id: str = Form(...), speed: float = Form(1.0)) -> StreamingResponse:
    """Re-stream a saved run with its original timing (divided by speed). No LLM calls."""
    path = RUNS_DIR / f"{Path(run_id).name}.json"  # Path().name blocks path traversal
    if not path.exists():
        raise HTTPException(404, "run not found")
    saved = json.loads(path.read_text())

    async def stream() -> AsyncIterator[str]:
        last = 0.0
        for e in saved["events"]:
            await asyncio.sleep(min(max(e["t"] - last, 0) / max(speed, 0.1), 4.0))
            last = e["t"]
            yield _sse(e["event"], e["data"])

    return StreamingResponse(stream(), media_type="text/event-stream", headers=SSE_HEADERS)
