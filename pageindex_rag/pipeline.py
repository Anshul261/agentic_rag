"""Indexing pipeline shared by the CLI and the upload API.

parse (Docling in an isolated subprocess, cached as tree.json)
  -> fix titles (cheap LLM reads the front matter)
  -> skip duplicates by title
  -> enrich (section/table summaries, figure descriptions)
  -> store in Postgres.
Every stage is idempotent; progress is reported through a callback.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .models import DocTree


@dataclass
class Progress:
    kind: str  # parsed | cached | failed | duplicate | titled | stored | skipped | done
    filename: str
    message: str = ""
    doc_id: str | None = None


Reporter = Callable[[Progress], None]


def counts(tree: DocTree) -> str:
    nodes = list(tree.walk())
    return " ".join(f"{k}={sum(n.kind == k for n in nodes)}" for k in ("section", "figure", "table"))


def parse_all(files: list[Path], out: Path, report: Reporter, force: bool = False) -> list[DocTree]:
    """Blocking: run in a thread from async code."""
    from .parsing import IsolatedParser, file_id

    parser = IsolatedParser()
    trees: dict[str, DocTree] = {}
    try:
        for f in files:
            doc_id = file_id(f)
            if doc_id in trees:
                report(Progress("duplicate", f.name, "same file content as another upload", doc_id))
                continue
            cached = out / doc_id / "tree.json"
            if cached.exists() and not force:
                trees[doc_id] = DocTree.model_validate_json(cached.read_text())
                report(Progress("cached", f.name, "already parsed", doc_id))
                continue
            t = time.time()
            try:
                trees[doc_id] = parser.parse(f, out)
            except Exception as e:  # one bad file shouldn't stop a batch
                report(Progress("failed", f.name, f"parse: {type(e).__name__}: {e}", doc_id))
                continue
            report(Progress("parsed", f.name, f"{time.time() - t:.1f}s {counts(trees[doc_id])}", doc_id))
    finally:
        parser.close()
    return list(trees.values())


async def enrich_and_store(trees: list[DocTree], out: Path, collection: str, report: Reporter,
                           use_llm: bool = True, force: bool = False) -> float:
    """Returns the LLM cost in USD."""
    from .store import Store, title_key

    store = Store()
    llm = None
    if use_llm:
        from .llm import LLM

        llm = LLM()

    # Titles first: dedupe below depends on them, and the parser often picks the journal name.
    retitled: set[str] = set()
    if llm:
        from .summarize import fix_title

        todo = [t for t in trees if not t.title_verified]
        for tree, changed in zip(todo, await asyncio.gather(*(fix_title(llm, t) for t in todo))):
            (out / tree.doc_id / "tree.json").write_text(tree.model_dump_json(indent=2))
            if changed:
                retitled.add(tree.doc_id)
                report(Progress("titled", tree.filename, tree.title, tree.doc_id))

    # Same paper saved as two different files: keep the first by title.
    kept: dict[str, DocTree] = {}
    for tree in trees:
        key = title_key(tree.title)
        dup = kept.get(key)
        existing = store.find_duplicate(collection, tree)
        if dup or existing:
            report(Progress("duplicate", tree.filename,
                            f"same title as {dup.filename if dup else existing}", tree.doc_id))
            continue
        kept[key] = tree

    async def one(tree: DocTree) -> None:
        enriched = tree.summary is not None
        if store.has(collection, tree.doc_id) and enriched and not force and tree.doc_id not in retitled:
            report(Progress("skipped", tree.filename, "already in collection", tree.doc_id))
            return
        t = time.time()
        try:
            if llm and not enriched:
                from .summarize import enrich

                await enrich(llm, tree, out / tree.doc_id)
                (out / tree.doc_id / "tree.json").write_text(tree.model_dump_json(indent=2))
            store.upsert(collection, tree)
        except Exception as e:
            report(Progress("failed", tree.filename, f"enrich: {type(e).__name__}: {e}", tree.doc_id))
            return
        report(Progress("stored", tree.filename, f"{time.time() - t:.1f}s · {tree.title}", tree.doc_id))

    await asyncio.gather(*(one(t) for t in kept.values()))
    cost = llm.cost_usd if llm else 0.0
    report(Progress("done", "", f"{len(kept)} documents in '{collection}' · LLM ${cost:.4f}"))
    return cost
