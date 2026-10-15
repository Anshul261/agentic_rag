"""Retrieval tools as plain functions — no agent framework imported here.

Any agent runtime (OpenAI Agents SDK, AGNO, an MCP server) wraps these.
Outputs are deliberately compact: the agent sees titles + summaries until it
chooses to read specific nodes, which is where PageIndex saves tokens.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .config import settings
from .llm import LLM, image_part
from .models import DocTree
from .store import Store

READ_BUDGET_TOKENS = 12_000  # max text returned by one read_nodes call


@dataclass
class ToolContext:
    store: Store
    collection: str
    data_dir: Path
    llm: LLM | None = None  # only needed for look_at_figure


def _tree(ctx: ToolContext, doc_id: str) -> DocTree:
    tree = ctx.store.load(ctx.collection, doc_id)
    if tree is None:
        raise ValueError(f"unknown doc_id {doc_id!r}; call list_documents first")
    return tree


def list_documents(ctx: ToolContext) -> str:
    rows = ctx.store.list_documents(ctx.collection)
    return "\n\n".join(f"doc_id={d} | {t} ({p} pages)\n{s or ''}" for d, t, p, s in rows)


def search_nodes(ctx: ToolContext, query: str, limit: int = 15) -> str:
    words = [w for w in re.findall(r"[A-Za-z0-9]+", query) if len(w) > 2]
    if not words:
        return "No searchable terms in query."
    rows = ctx.store.conn.execute(
        """select d.title, n.doc_id, n.node_id, n.kind, n.title, n.page_start, n.page_end, n.summary
             from nodes n join documents d using (collection, doc_id)
            where n.collection=%s and n.tsv @@ to_tsquery('english', %s)
            order by ts_rank_cd(n.tsv, to_tsquery('english', %s)) desc limit %s""",
        (ctx.collection, " | ".join(words), " | ".join(words), limit)).fetchall()
    if not rows:
        return "No matches."
    return "\n".join(f"[{doc_title[:60]}] doc_id={d} node={nid} ({kind}, p{ps}-{pe}) {title} — {summ or ''}"
                     for doc_title, d, nid, kind, title, ps, pe, summ in rows)


def get_tree(ctx: ToolContext, doc_id: str, max_depth: int = 99) -> str:
    tree = _tree(ctx, doc_id)
    return f"{tree.title} ({tree.n_pages} pages)\n{tree.summary or ''}\n\n{tree.outline(max_depth=max_depth)}"


def read_nodes(ctx: ToolContext, doc_id: str, node_ids: list[str]) -> str:
    tree = _tree(ctx, doc_id)
    parts, used = [], 0
    for nid in node_ids:
        node = tree.get(nid)
        if node is None:
            parts.append(f"## node {nid}: not found")
            continue
        header = f"## [{tree.title[:60]}] node {nid} — {node.title} (p{node.page_start}-{node.page_end})"
        if node.kind == "figure":
            body = (f"Figure caption: {node.text}\nDescription: {node.summary}\n"
                    "(Use look_at_figure to ask about details in the image.)")
        else:
            remaining = READ_BUDGET_TOKENS - used
            if remaining <= 200:
                parts.append(f"## node {nid}: skipped, read budget used — request it in a separate call")
                continue
            body = node.text[: remaining * 4]
            if len(node.text) > len(body):
                body += "\n…[truncated]"
            used += len(body) // 4
        if node.children:
            body += "\nChildren: " + "; ".join(f"{c.node_id} {c.title}" for c in node.children)
        parts.append(f"{header}\n{body}")
    return "\n\n".join(parts)


FIGURE_QA_SYSTEM = ("Answer the question about this figure from a document. Read values carefully; "
                    "if something is not legible or not shown, say so.")


async def look_at_figure(ctx: ToolContext, doc_id: str, node_id: str, question: str) -> str:
    tree = _tree(ctx, doc_id)
    node = tree.get(node_id)
    if node is None or node.kind != "figure" or not node.image_path:
        return f"node {node_id} is not a figure"
    if ctx.llm is None:
        return "figure inspection unavailable (no LLM configured)"
    return await ctx.llm.text(
        settings.cheap_model, FIGURE_QA_SYSTEM,
        [{"type": "text", "text": f"Caption: {node.text}\nQuestion: {question}"},
         image_part(ctx.data_dir / doc_id / node.image_path)],
        max_tokens=500)
