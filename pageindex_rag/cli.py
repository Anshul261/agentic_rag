"""Command line entry point.

    uv run -m pageindex_rag.cli index <file-or-folder> [...] [--collection NAME] [--no-llm] [--force]
    uv run -m pageindex_rag.cli show <doc_id> [--depth N]
    uv run -m pageindex_rag.cli docs [--collection NAME]
    uv run -m pageindex_rag.cli ask "question" [--collection NAME] [--max-turns N]

`index` runs the shared pipeline (pipeline.py): parse -> fix titles -> dedupe
-> enrich -> store. Every stage is idempotent.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
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


def _print_progress(p) -> None:
    tags = {"parsed": "parse", "cached": None, "failed": "FAIL ", "duplicate": "skip ", "titled": "title",
            "stored": "store", "skipped": None, "done": "\nLLM:"}
    tag = tags.get(p.kind, p.kind)
    if tag:
        print(f"{tag}  {p.doc_id or ''}  {p.message}  {p.filename}".rstrip())


def cmd_index(args: argparse.Namespace) -> None:
    from .pipeline import enrich_and_store, parse_all

    out = Path(args.out)
    trees = parse_all(_collect(args.paths), out, _print_progress, force=args.force)
    asyncio.run(enrich_and_store(trees, out, args.collection, _print_progress,
                                 use_llm=not args.no_llm, force=args.force))


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

    from .telemetry import setup_tracing

    setup_tracing()
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
