"""Turn agent tool calls into structured trace events for the UI's search visualization.

Events are derived from tool-call arguments plus the stored trees (titles, page
ranges, paths), so the UI never has to parse free-text tool output.

Event kinds:
  catalog   {n_docs}
  search    {query, hits: [{doc_id, doc_title, node_id, title, pages}]}
  open_doc  {doc_id, doc_title, n_pages, branches: [{node_id, title, pages}]}
  read      {nodes: [{doc_id, doc_title, node_id, title, kind, pages, path: [{node_id, title, pages}]}]}
  figure    {doc_id, doc_title, node_id, title, pages, path}
"""

from __future__ import annotations

import json
from typing import Any

from .models import DocTree, Node
from .tools import ToolContext, search_rows


def _pages(n: Node) -> str:
    return f"{n.page_start}" if n.page_start == n.page_end else f"{n.page_start}–{n.page_end}"


def _brief(n: Node) -> dict:
    return dict(node_id=n.node_id, title=n.title[:120], pages=_pages(n), kind=n.kind)


class TraceBuilder:
    def __init__(self, ctx: ToolContext):
        self.ctx = ctx
        self._trees: dict[str, DocTree | None] = {}

    def _tree(self, doc_id: str) -> DocTree | None:
        if doc_id not in self._trees:
            self._trees[doc_id] = self.ctx.store.load(self.ctx.collection, doc_id)
        return self._trees[doc_id]

    def start(self) -> dict:
        return dict(kind="catalog", n_docs=len(self.ctx.store.list_documents(self.ctx.collection)))

    def _node_event(self, doc_id: str, node_id: str) -> dict | None:
        tree = self._tree(doc_id)
        if tree is None:
            return None
        path = tree.path(node_id)
        if not path:
            return None
        node = path[-1]
        return dict(doc_id=doc_id, doc_title=tree.title, **_brief(node), path=[_brief(p) for p in path[:-1]])

    def from_tool_call(self, name: str, arguments: str) -> dict | None:
        try:
            args: dict[str, Any] = json.loads(arguments or "{}")
        except json.JSONDecodeError:
            return None

        if name == "search_nodes":
            rows = search_rows(self.ctx, str(args.get("query", "")), limit=5)
            hits = [dict(doc_id=d, doc_title=dt, node_id=nid, title=t[:120],
                         pages=f"{ps}" if ps == pe else f"{ps}–{pe}")
                    for dt, d, nid, _kind, t, ps, pe, _s in rows]
            return dict(kind="search", query=str(args.get("query", ""))[:200], hits=hits)

        if name == "get_tree":
            tree = self._tree(str(args.get("doc_id", "")))
            if tree is None:
                return None
            return dict(kind="open_doc", doc_id=tree.doc_id, doc_title=tree.title, n_pages=tree.n_pages,
                        branches=[_brief(n) for n in tree.nodes if n.kind == "section"][:12])

        if name == "read_nodes":
            nodes = []
            for ref in args.get("refs", []) or []:
                doc_id, _, node_id = str(ref).partition(":")
                if ev := self._node_event(doc_id.strip(), node_id.strip()):
                    nodes.append(ev)
            return dict(kind="read", nodes=nodes) if nodes else None

        if name == "look_at_figure":
            ev = self._node_event(str(args.get("doc_id", "")), str(args.get("node_id", "")))
            return {**ev, "kind": "figure"} if ev else None  # event kind replaces node kind

        return None
