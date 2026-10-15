"""PageIndex HTTP API (FastAPI router). Mounted by server.py.

Browse
  GET    /pageindex/collections
  GET    /pageindex/collections/{c}/documents
  GET    /pageindex/collections/{c}/documents/{doc_id}               tree (no text)
  GET    /pageindex/collections/{c}/documents/{doc_id}/nodes/{node}  node text, path, figure url
  DELETE /pageindex/collections/{c}/documents/{doc_id}
  GET    /pageindex/figures/{doc_id}/{file}                          figure image
Ask
  POST   /pageindex/query     form: message, collection, thread_id?   -> server-sent events
  GET    /pageindex/runs      POST /pageindex/replay  form: run_id, speed
Ingest
  POST   /pageindex/collections/{c}/documents   multipart files -> {job_id}
  GET    /pageindex/jobs/{job_id}

Query events: Trace (see trace.py) · Answer {answer, citations} · Stats · Error {error}.
Each live run is saved under data/pageindex/runs/ so it can be replayed without LLM calls.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from pathlib import Path
from typing import AsyncIterator

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from .parsing import SUPPORTED_SUFFIXES
from .pipeline import Progress, enrich_and_store, parse_all
from .runner import run_question
from .store import Store
from .tools import ToolContext
from .trace import TraceBuilder

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data" / "pageindex"
RUNS_DIR = DATA_DIR / "runs"
UPLOADS_DIR = ROOT / "data" / "uploads"
SSE_HEADERS = {"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"}
MAX_UPLOAD_BYTES = 100 * 1024 * 1024
NODE_TEXT_LIMIT = 40_000

_COLLECTION_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_DOC_ID_RE = re.compile(r"^[0-9a-f]{16}$")
_NODE_ID_RE = re.compile(r"^\d{4}$")
_FIGURE_RE = re.compile(r"^fig_\d{3}_p\d+\.png$")

router = APIRouter(prefix="/pageindex", tags=["pageindex"])
JOBS: dict[str, dict] = {}  # in-memory upload jobs; fine for a single-process server
_TASKS: set[asyncio.Task] = set()  # strong refs so background jobs are not garbage-collected


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _collection(name: str) -> str:
    if not _COLLECTION_RE.match(name):
        raise HTTPException(400, "collection: lowercase letters, digits, '-' or '_' (max 64)")
    return name


def _doc_id(doc_id: str) -> str:
    if not _DOC_ID_RE.match(doc_id):
        raise HTTPException(400, "invalid doc_id")
    return doc_id


def _pages(a: int, b: int) -> str:
    return f"{a}" if a == b else f"{a}–{b}"


# ------------------------------------------------------------------ browse

@router.get("/collections")
def list_collections() -> JSONResponse:
    rows = Store().conn.execute(
        "select collection, count(*) from documents where collection not like 'bench%' "
        "group by collection order by collection").fetchall()
    return JSONResponse([dict(name=c, n_docs=n) for c, n in rows])


@router.get("/collections/{collection}/documents")
def list_documents(collection: str) -> JSONResponse:
    rows = Store().conn.execute(
        """select d.doc_id, d.title, d.filename, d.n_pages, d.summary,
                  count(*) filter (where n.kind = 'figure'), count(*) filter (where n.kind = 'table')
             from documents d left join nodes n using (collection, doc_id)
            where d.collection = %s group by d.doc_id, d.title, d.filename, d.n_pages, d.summary
            order by d.title""", (_collection(collection),)).fetchall()
    return JSONResponse([dict(doc_id=d, title=t, filename=f, n_pages=p, summary=s, n_figures=nf, n_tables=nt)
                         for d, t, f, p, s, nf, nt in rows])


@router.get("/collections/{collection}/documents/{doc_id}")
def get_document(collection: str, doc_id: str) -> JSONResponse:
    tree = Store().load(_collection(collection), _doc_id(doc_id))
    if tree is None:
        raise HTTPException(404, "document not found")

    def node(n) -> dict:
        return dict(node_id=n.node_id, kind=n.kind, title=n.title, pages=_pages(n.page_start, n.page_end),
                    summary=n.summary, children=[node(c) for c in n.children])

    return JSONResponse(dict(doc_id=tree.doc_id, title=tree.title, filename=tree.filename, n_pages=tree.n_pages,
                             summary=tree.summary, nodes=[node(n) for n in tree.nodes]))


@router.get("/collections/{collection}/documents/{doc_id}/nodes/{node_id}")
def get_node(collection: str, doc_id: str, node_id: str) -> JSONResponse:
    if not _NODE_ID_RE.match(node_id):
        raise HTTPException(400, "invalid node_id")
    tree = Store().load(_collection(collection), _doc_id(doc_id))
    path = tree.path(node_id) if tree else []
    if not path:
        raise HTTPException(404, "node not found")
    n = path[-1]
    image_url = f"/pageindex/figures/{doc_id}/{Path(n.image_path).name}" if n.image_path else None
    return JSONResponse(dict(
        doc_id=doc_id, doc_title=tree.title, node_id=n.node_id, kind=n.kind, title=n.title,
        pages=_pages(n.page_start, n.page_end), summary=n.summary, text=n.text[:NODE_TEXT_LIMIT],
        truncated=len(n.text) > NODE_TEXT_LIMIT, image_url=image_url,
        path=[dict(node_id=p.node_id, title=p.title) for p in path[:-1]],
        children=[dict(node_id=c.node_id, kind=c.kind, title=c.title) for c in n.children]))


@router.get("/figures/{doc_id}/{filename}")
def get_figure(doc_id: str, filename: str) -> FileResponse:
    if not _FIGURE_RE.match(filename):
        raise HTTPException(400, "invalid figure name")
    path = DATA_DIR / _doc_id(doc_id) / "figures" / filename
    if not path.is_file():
        raise HTTPException(404, "figure not found")
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "max-age=86400"})


@router.delete("/collections/{collection}/documents/{doc_id}")
def delete_document(collection: str, doc_id: str) -> JSONResponse:
    store = Store()
    if not store.has(_collection(collection), _doc_id(doc_id)):
        raise HTTPException(404, "document not found")
    store.delete(collection, doc_id)  # parsed tree/figures stay cached on disk for re-upload
    return JSONResponse(dict(deleted=doc_id))


# ------------------------------------------------------------------ ask

@router.get("/runs")
def list_runs() -> JSONResponse:
    runs = []
    for f in sorted(RUNS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:50]:
        d = json.loads(f.read_text())
        runs.append(dict(run_id=f.stem, question=d["question"], collection=d["collection"]))
    return JSONResponse(runs)


@router.post("/query")
async def query(request: Request, message: str = Form(...), collection: str = Form(...),
                thread_id: str | None = Form(None)) -> StreamingResponse:
    store = Store()
    if not store.list_documents(_collection(collection)):
        raise HTTPException(404, f"collection {collection!r} is empty or does not exist")
    message = message.strip()[:4000]
    if not message:
        raise HTTPException(400, "empty message")
    checkpointer = getattr(request.app.state, "checkpointer", None)

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
                r = await run_question(message, collection, DATA_DIR, store=store, on_tool=on_tool,
                                       thread_id=thread_id, checkpointer=checkpointer)
                if r.answer:
                    emit("Answer", dict(answer=r.answer.answer, blocked=r.blocked_by_provider,
                                        citations=[c.model_dump() for c in r.answer.citations]))
                if r.error:
                    emit("Error", dict(error=r.error))
                run_id = f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
                emit("Stats", dict(seconds=round(r.seconds, 1), cost_usd=round(r.cost_usd + r.tool_llm_cost_usd, 4),
                                   model_calls=r.requests, tool_calls=len(r.tool_calls), run_id=run_id))
                if r.answer and not r.error:
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


# ------------------------------------------------------------------ ingest

@router.post("/collections/{collection}/documents")
async def upload(collection: str, files: list[UploadFile] = File(...)) -> JSONResponse:
    _collection(collection)
    job_id = uuid.uuid4().hex[:12]
    job_dir = UPLOADS_DIR / job_id
    job_dir.mkdir(parents=True)
    saved: list[Path] = []
    rejected: list[dict] = []
    for f in files:
        name = Path(f.filename or "").name  # no directory components from the client
        if not name or Path(name).suffix.lower() not in SUPPORTED_SUFFIXES:
            rejected.append(dict(filename=name, status="rejected", message="unsupported file type"))
            continue
        data = await f.read(MAX_UPLOAD_BYTES + 1)
        if len(data) > MAX_UPLOAD_BYTES:
            rejected.append(dict(filename=name, status="rejected", message="file larger than 100 MB"))
            continue
        (job_dir / name).write_bytes(data)
        saved.append(job_dir / name)
    if not saved:
        raise HTTPException(400, dict(message="no supported files", files=rejected))

    job = JOBS[job_id] = dict(job_id=job_id, collection=collection, state="running", started=time.time(),
                              files={p.name: dict(filename=p.name, status="queued", message="") for p in saved},
                              rejected=rejected, summary="")

    def report(p: Progress) -> None:
        if p.kind == "done":
            job["summary"] = p.message
        elif p.filename in job["files"]:
            job["files"][p.filename].update(status=p.kind, message=p.message, doc_id=p.doc_id)

    async def run() -> None:
        try:
            for name in job["files"]:
                job["files"][name]["status"] = "parsing"
            trees = await asyncio.to_thread(parse_all, saved, DATA_DIR, report)
            for t in trees:
                if job["files"].get(t.filename, {}).get("status") in ("parsed", "cached"):
                    job["files"][t.filename]["status"] = "summarizing"
            await enrich_and_store(trees, DATA_DIR, collection, report)
            job["state"] = "done"
        except Exception as e:
            job["state"] = "failed"
            job["summary"] = f"{type(e).__name__}: {e}"

    task = asyncio.create_task(run())
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)
    return JSONResponse(dict(job_id=job_id, files=len(saved), rejected=rejected), status_code=202)


@router.get("/jobs/{job_id}")
def get_job(job_id: str) -> JSONResponse:
    job = JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    return JSONResponse(dict(job, files=list(job["files"].values()), elapsed=round(time.time() - job["started"])))
