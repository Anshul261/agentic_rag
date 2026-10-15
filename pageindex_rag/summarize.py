"""Index-time enrichment with the cheap model.

- Sections + tables: summarized in batches (one call covers a whole short paper),
  so a 20-page paper costs one text call instead of ~40.
- Figures: one vision call each — image + caption + surrounding section text.
- Document: a short summary used to pick documents across a corpus.

Summaries are written for the *navigating agent*: it only sees titles and
summaries when deciding which nodes to open, so they must name concrete content.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from pydantic import BaseModel

from .config import settings
from .llm import LLM, image_part
from .models import DocTree, Node

log = logging.getLogger(__name__)

SECTION_SYSTEM = """You write retrieval summaries for nodes of a document tree.
A search agent will read ONLY node titles and your summaries to decide which nodes to open,
so each summary must say concretely what the node contains: methods, models, datasets,
metrics, numbers, findings, definitions. 1-2 sentences, max 45 words.
Never write filler like "This section discusses". For nodes with little or no body text,
summarize what their child nodes cover. For tables, say what is compared and on what.
Also write a 3-4 sentence summary of the whole document: problem, approach, data, key results."""

FIGURE_SYSTEM = """You describe figures from documents for a retrieval index.
In 2-3 sentences (max 70 words) state: the figure type (architecture diagram, flowchart,
bar chart, line plot, ROC curve, table image, screenshot...), what it shows, and any key
values or takeaways readable from it. Be factual; do not guess unreadable values."""


TITLE_SYSTEM = """Identify the document's real title from its first page text. Papers often print the
journal or publisher name ("Expert Systems With Applications", "ORIGINAL ARTICLE", "RESEARCH") above the
title; that is NOT the title. Return the title exactly as printed, without author names."""


class DocTitle(BaseModel):
    title: str


async def fix_title(llm: LLM, tree: DocTree) -> bool:
    """Replace the parser's title guess with the real one. Returns True if it changed."""
    first = [n for n in tree.walk() if n.page_start == 1][:8]
    text = "\n".join(f"{n.title}\n{n.text[:600]}" for n in first)
    user = f"File name: {tree.filename}\nParser's title guess: {tree.title}\n\nFirst page:\n{text[:4000]}"
    result = await llm.structured(settings.cheap_model, TITLE_SYSTEM, user, DocTitle)
    tree.title_verified = True
    new = result.title.strip()
    if new and new != tree.title:
        tree.title = new
        return True
    return False


class NodeSummary(BaseModel):
    node_id: str
    summary: str


class BatchSummaries(BaseModel):
    summaries: list[NodeSummary]
    doc_summary: str


def _node_block(node: Node, max_chars: int) -> str:
    pages = f"p{node.page_start}-{node.page_end}"
    body = node.text[:max_chars] + (" …[truncated]" if len(node.text) > max_chars else "")
    if not body.strip():
        kids = "; ".join(c.title for c in node.children[:15])
        body = f"(no body text; children: {kids})" if kids else "(empty)"
    return f"### [{node.node_id}] ({node.kind}, {pages}) {node.title}\n{body}"


def _batches(nodes: list[Node], budget_tokens: int) -> list[list[Node]]:
    batches, cur, size = [], [], 0
    for n in nodes:
        t = min(n.n_tokens, 2000) + 30
        if cur and size + t > budget_tokens:
            batches.append(cur)
            cur, size = [], 0
        cur.append(n)
        size += t
    return batches + ([cur] if cur else [])


async def summarize_sections(llm: LLM, tree: DocTree) -> None:
    nodes = [n for n in tree.walk() if n.kind in ("section", "table") and n.summary is None]
    if not nodes:
        return
    results: list[BatchSummaries] = []
    for batch in _batches(nodes, settings.summary_batch_tokens):
        blocks = "\n\n".join(_node_block(n, 6000 if n.kind == "section" else 3000) for n in batch)
        user = f"Document: {tree.title}\nFile: {tree.filename}\n\nNodes:\n\n{blocks}"
        results.append(await llm.structured(settings.cheap_model, SECTION_SYSTEM, user, BatchSummaries))

    by_id = {s.node_id: s.summary.strip() for r in results for s in r.summaries}
    missing = 0
    for n in nodes:
        n.summary = by_id.get(n.node_id)
        missing += n.summary is None
    if missing:
        log.warning("%s: %d nodes got no summary", tree.filename, missing)
    tree.summary = results[0].doc_summary.strip() if len(results) == 1 else await llm.text(
        settings.cheap_model, SECTION_SYSTEM,
        "Write only the 3-4 sentence document summary from these partial summaries:\n\n"
        + "\n".join(r.doc_summary for r in results))


async def describe_figure(llm: LLM, tree: DocTree, doc_dir: Path, fig: Node, parent: Node | None) -> None:
    context = f"Document: {tree.title}\nCaption: {fig.text or '(none)'}\n"
    if parent is not None:
        context += f"Appears in section: {parent.title}\nSection excerpt: {parent.text[:1500]}"
    fig.summary = await llm.text(
        settings.cheap_model, FIGURE_SYSTEM,
        [{"type": "text", "text": context}, image_part(doc_dir / fig.image_path)], max_tokens=300)


def _parents(tree: DocTree) -> dict[str, Node]:
    out: dict[str, Node] = {}
    for n in tree.walk():
        for c in n.children:
            out[c.node_id] = n
    return out


async def enrich(llm: LLM, tree: DocTree, doc_dir: Path) -> None:
    parents = _parents(tree)
    figs = [n for n in tree.walk() if n.kind == "figure" and n.summary is None and n.image_path]
    await asyncio.gather(
        summarize_sections(llm, tree),
        *(describe_figure(llm, tree, doc_dir, f, parents.get(f.node_id)) for f in figs),
    )
