"""Data model for a PageIndex-style document tree.

A document becomes a tree of nodes. Section nodes hold body text; figure and
table nodes hang off the section they appear in. Every node carries page
numbers so answers can cite [doc, page].
"""

from __future__ import annotations

from typing import Iterator, Literal

from pydantic import BaseModel, Field

NodeKind = Literal["section", "figure", "table"]


class Node(BaseModel):
    node_id: str
    kind: NodeKind = "section"
    title: str
    level: int = 1
    page_start: int
    page_end: int
    text: str = ""  # section body, table markdown, or figure caption
    summary: str | None = None  # filled by the indexer (LLM), step 2
    image_path: str | None = None  # figures only, relative to the doc dir
    children: list[Node] = Field(default_factory=list)

    @property
    def n_tokens(self) -> int:
        return len(self.text) // 4  # rough; good enough for read budgets

    def walk(self) -> Iterator[Node]:
        yield self
        for child in self.children:
            yield from child.walk()


class DocTree(BaseModel):
    doc_id: str  # sha256 of file bytes (first 16 hex) — dedupes identical files
    filename: str
    title: str
    n_pages: int
    parser_version: str = ""  # re-index when this changes
    title_verified: bool = False  # title confirmed by the LLM from front matter
    summary: str | None = None
    nodes: list[Node] = Field(default_factory=list)

    def walk(self) -> Iterator[Node]:
        for node in self.nodes:
            yield from node.walk()

    def get(self, node_id: str) -> Node | None:
        return next((n for n in self.walk() if n.node_id == node_id), None)

    def outline(self, max_depth: int = 99, with_summaries: bool = True) -> str:
        """Compact ToC view: the thing the agent reasons over."""
        lines: list[str] = []

        def visit(node: Node, depth: int) -> None:
            if depth > max_depth:
                return
            pages = f"p{node.page_start}" + (f"-{node.page_end}" if node.page_end != node.page_start else "")
            tag = "" if node.kind == "section" else f"[{node.kind}] "
            line = f"{'  ' * depth}{node.node_id} {tag}{node.title} ({pages}, ~{node.n_tokens} tok)"
            if with_summaries and node.summary:
                line += f" — {node.summary}"
            lines.append(line)
            for child in node.children:
                visit(child, depth + 1)

        for node in self.nodes:
            visit(node, 0)
        return "\n".join(lines)
