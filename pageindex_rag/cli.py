"""Command line entry point.

    uv run -m pageindex_rag.cli index <file-or-folder> [...] [--out data/pageindex]
    uv run -m pageindex_rag.cli show <doc_id> [--depth N]
"""

from __future__ import annotations

import argparse
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


def cmd_index(args: argparse.Namespace) -> None:
    from .parsing import IsolatedParser, file_id

    out = Path(args.out)
    files = _collect(args.paths)
    parser = IsolatedParser()
    seen: set[str] = set()
    for f in files:
        doc_id = file_id(f)
        if doc_id in seen:
            print(f"skip (duplicate)  {f.name}")
            continue
        seen.add(doc_id)
        if (out / doc_id / "tree.json").exists() and not args.force:
            print(f"skip (indexed)    {f.name}")
            continue
        t = time.time()
        try:
            tree = parser.parse(f, out)
        except Exception as e:  # one bad file shouldn't stop a batch
            print(f"FAIL              {f.name}: {type(e).__name__}: {e}")
            continue
        nodes = list(tree.walk())
        kinds = {k: sum(n.kind == k for n in nodes) for k in ("section", "figure", "table")}
        print(f"ok {time.time() - t:5.1f}s  {tree.doc_id}  {kinds}  {f.name}")


def cmd_show(args: argparse.Namespace) -> None:
    tree = DocTree.model_validate_json((Path(args.out) / args.doc_id / "tree.json").read_text())
    print(f"{tree.title}\n{tree.filename} · {tree.n_pages} pages · {tree.doc_id}\n")
    print(tree.outline(max_depth=args.depth))


def main() -> None:
    logging.basicConfig(level=logging.WARNING)
    ap = argparse.ArgumentParser(prog="pageindex_rag")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("index")
    p.add_argument("paths", nargs="+")
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_index)
    p = sub.add_parser("show")
    p.add_argument("doc_id")
    p.add_argument("--depth", type=int, default=99)
    p.set_defaults(fn=cmd_show)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
