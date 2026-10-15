"""Command line entry point.

    uv run -m pageindex_rag.cli index <file-or-folder> [...] [--collection NAME] [--no-llm] [--force]
    uv run -m pageindex_rag.cli show <doc_id> [--depth N]
    uv run -m pageindex_rag.cli docs [--collection NAME]
    uv run -m pageindex_rag.cli ask "question" [--collection NAME] [--max-turns N]

`index` runs the whole pipeline per file: parse (Docling, cached as tree.json)
-> skip duplicates by title -> enrich (cheap LLM summaries + figure
descriptions) -> store in Postgres. Every stage is idempotent.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import time
from pathlib import Path

from .models import DocTree

DEFAULT_OUT = Path("data/pageindex")


def _collect(paths: list[str]) -> list[Path]:
    from .parsing import SUPPORTED_SUFFIXES

    files: list[Path] = []
    for p in map(Path, paths):
        if p.is_dir():
            files += sorted(f for f in p.rglob("*") if f.suffix.lower() in SUPPORTED_SUFFIXES)
        elif p.suffix.lower() in SUPPORTED_SUFFIXES:
            files.append(p)
    return files


def _counts(tree: DocTree) -> str:
    nodes = list(tree.walk())
    return " ".join(f"{k}={sum(n.kind == k for n in nodes)}" for k in ("section", "figure", "table"))


def _parse_all(files: list[Path], out: Path, force: bool) -> list[DocTree]:
    from .parsing import IsolatedParser, file_id

    parser = IsolatedParser()
    trees: dict[str, DocTree] = {}
    try:
        for f in files:
            doc_id = file_id(f)
            if doc_id in trees:
                print(f"skip  duplicate file  {f.name}")
                continue
            cached = out / doc_id / "tree.json"
            if cached.exists() and not force:
                trees[doc_id] = DocTree.model_validate_json(cached.read_text())
                continue
            t = time.time()
            try:
                trees[doc_id] = parser.parse(f, out)
            except Exception as e:  # one bad file shouldn't stop a batch
                print(f"FAIL  parse  {f.name}: {type(e).__name__}: {e}")
                continue
            print(f"parse {time.time() - t:5.1f}s  {doc_id}  {_counts(trees[doc_id])}  {f.name}")
    finally:
        parser.close()
    return list(trees.values())


async def _enrich_and_store(trees: list[DocTree], out: Path, collection: str, use_llm: bool, force: bool) -> None:
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
                print(f"title {tree.doc_id}  {tree.title[:90]}")

    # Same paper saved as two different files: keep the first by title.
    kept: dict[str, DocTree] = {}
    for tree in trees:
        key = title_key(tree.title)
        dup = kept.get(key)
        existing = store.find_duplicate(collection, tree)
        if dup or existing:
            print(f"skip  duplicate title  {tree.filename}  (same as {dup.filename if dup else existing})")
            continue
        kept[key] = tree

    async def one(tree: DocTree) -> None:
        enriched = tree.summary is not None
        if store.has(collection, tree.doc_id) and enriched and not force and tree.doc_id not in retitled:
            return
        t = time.time()
        try:
            if llm and not enriched:
                from .summarize import enrich

                await enrich(llm, tree, out / tree.doc_id)
                (out / tree.doc_id / "tree.json").write_text(tree.model_dump_json(indent=2))
            store.upsert(collection, tree)
        except Exception as e:
            print(f"FAIL  enrich {tree.filename}: {type(e).__name__}: {e}")
            return
        print(f"store {time.time() - t:5.1f}s  {tree.doc_id}  {tree.filename[:70]}")

    await asyncio.gather(*(one(t) for t in kept.values()))
    if llm:
        print(f"\nLLM: {llm.calls} calls, ${llm.cost_usd:.4f} ({len(kept)} docs in '{collection}')")


def cmd_index(args: argparse.Namespace) -> None:
    out = Path(args.out)
    trees = _parse_all(_collect(args.paths), out, args.force)
    asyncio.run(_enrich_and_store(trees, out, args.collection, not args.no_llm, args.force))


def cmd_show(args: argparse.Namespace) -> None:
    tree = DocTree.model_validate_json((Path(args.out) / args.doc_id / "tree.json").read_text())
    print(f"{tree.title}\n{tree.filename} · {tree.n_pages} pages · {tree.doc_id}\n")
    if tree.summary:
        print(f"{tree.summary}\n")
    print(tree.outline(max_depth=args.depth))


def cmd_docs(args: argparse.Namespace) -> None:
    from .store import Store

    for doc_id, title, n_pages, summary in Store().list_documents(args.collection):
        print(f"{doc_id}  {n_pages:3}p  {title[:90]}")


async def _ask(args: argparse.Namespace) -> None:
    from .runner import format_report, run_question

    report = await run_question(args.question, args.collection, Path(args.out), max_turns=args.max_turns,
                                on_tool=lambda name, a: print(f"  → {name}({a[:150]})"))
    print(format_report(report))


def cmd_ask(args: argparse.Namespace) -> None:
    asyncio.run(_ask(args))


def main() -> None:
    logging.basicConfig(level=logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    ap = argparse.ArgumentParser(prog="pageindex_rag")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("index")
    p.add_argument("paths", nargs="+")
    p.add_argument("--collection", default="default")
    p.add_argument("--no-llm", action="store_true", help="parse + store only, skip summaries")
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_index)
    p = sub.add_parser("show")
    p.add_argument("doc_id")
    p.add_argument("--depth", type=int, default=99)
    p.set_defaults(fn=cmd_show)
    p = sub.add_parser("docs")
    p.add_argument("--collection", default="default")
    p.set_defaults(fn=cmd_docs)
    p = sub.add_parser("ask")
    p.add_argument("question")
    p.add_argument("--collection", default="default")
    p.add_argument("--max-turns", type=int, default=15)
    p.set_defaults(fn=cmd_ask)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
