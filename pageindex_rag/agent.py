"""OpenAI Agents SDK adapter: wraps the plain tools in tools.py.

Runs on OpenRouter through Chat Completions (not the Responses API), with
strict feature validation so unsupported features fail loudly instead of
being silently dropped. SDK tracing to OpenAI is disabled.

Cost design: the collection catalog is part of the system prompt. It is
identical across every turn and every question, so it stays in the provider's
prompt cache (95% cheaper than fresh input) and saves a tool round-trip. We do
not trim old tool outputs mid-run: rewriting earlier context would invalidate
the cached prefix and cost more than it saves.
"""

from __future__ import annotations

from openai import AsyncOpenAI
from pydantic import BaseModel

from agents import (
    Agent,
    ModelSettings,
    OpenAIProvider,
    RunConfig,
    RunContextWrapper,
    function_tool,
    set_tracing_disabled,
)

from . import tools
from .config import settings
from .store import Store
from .tools import ToolContext

set_tracing_disabled(True)

CATALOG_INLINE_MAX_DOCS = 150  # above this, the agent pages the catalog via a tool

INSTRUCTIONS = """You answer questions about a document collection by navigating it like a
researcher: a catalog of documents, then each document's table-of-contents tree, then the
specific sections. You never see full text unless you read it.

Pick the cheapest strategy that fully answers the question:
- Listing / "which documents are about X" / collection overview: answer from the CATALOG below.
  Judge every catalog entry; include borderline documents only if their summary supports it.
  Open trees only when a summary is too vague to decide.
- One specific document: get_tree for it, then read_nodes for the nodes that should hold the answer.
- A topic across many documents (comparisons, "which papers use X and what results"):
  search_nodes first to jump straight to relevant sections, use the catalog to spot documents
  search may have missed, then read the chosen nodes of ALL documents in ONE read_nodes call.
  Only open a tree when you need a document's structure to find the right node.
- Charts, diagrams, architectures, plotted values: look_at_figure on the figure node.

Batch work: request several tool calls in the same turn, and read many nodes per read_nodes
call instead of one at a time. Do not reread nodes you already have.

Answer only from what you read (catalog summaries count for listing questions). Cite every
claim inline as [n], where n indexes your citations list; for a catalog-level fact cite the
document with node_id "catalog". If the collection does not contain the answer, say so
plainly. For comparisons, cover each relevant document explicitly."""


class Citation(BaseModel):
    doc_id: str
    doc_title: str
    node_id: str
    pages: str


class Answer(BaseModel):
    answer: str  # markdown with inline [n] markers
    citations: list[Citation]


@function_tool
def list_documents(ctx: RunContextWrapper[ToolContext]) -> str:
    """List every document in the collection with its doc_id, title, page count and summary."""
    return tools.list_documents(ctx.context)


@function_tool
def search_nodes(ctx: RunContextWrapper[ToolContext], query: str) -> str:
    """Keyword search over section/figure/table titles, summaries and text across all documents.
    Returns the best matching nodes with doc_id, node_id, pages and summary."""
    return tools.search_nodes(ctx.context, query, limit=20)


@function_tool
def get_tree(ctx: RunContextWrapper[ToolContext], doc_id: str) -> str:
    """Show one document's section tree: node ids, titles, page ranges, sizes and summaries
    (figures and tables are tagged). Use it to decide which nodes to read."""
    return tools.get_tree(ctx.context, doc_id)


@function_tool
async def read_nodes(ctx: RunContextWrapper[ToolContext], refs: list[str], focus: str) -> str:
    """Read the content of nodes, possibly from several documents at once.
    refs: "doc_id:node_id" strings, e.g. ["20d48ed184a74ce7:0031", "95d850e1d80e7bfb:0012"].
    focus: what you are looking for in these nodes (e.g. "resampling method and reported F1/AUC").
    Returns up to ~12k tokens per call; request fewer nodes if output is truncated."""
    return await tools.read_refs(ctx.context, refs, focus)


@function_tool
async def look_at_figure(ctx: RunContextWrapper[ToolContext], doc_id: str, node_id: str, question: str) -> str:
    """Ask a vision model a question about one figure node (diagram, chart, plot) of a document."""
    return await tools.look_at_figure(ctx.context, doc_id, node_id, question)


def build_agent(collection: str, store: Store) -> Agent[ToolContext]:
    docs = store.list_documents(collection)
    agent_tools = [search_nodes, get_tree, read_nodes, look_at_figure]
    if len(docs) <= CATALOG_INLINE_MAX_DOCS:
        catalog = "\n".join(f"- doc_id={d} | {t} ({p} pages): {s or ''}" for d, t, p, s in docs)
        instructions = f"{INSTRUCTIONS}\n\nCATALOG ({len(docs)} documents):\n{catalog}"
    else:
        instructions = INSTRUCTIONS.replace("from the CATALOG below", "from list_documents")
        agent_tools.insert(0, list_documents)
    return Agent[ToolContext](
        name="pageindex-researcher",
        instructions=instructions,
        model=settings.reasoning_model,
        tools=agent_tools,
        output_type=Answer,
        model_settings=ModelSettings(
            include_usage=True,
            parallel_tool_calls=True,
            preserve_raw_usage=True,  # keep OpenRouter's billed cost per response
            extra_body={"usage": {"include": True}},
        ),
    )


def run_config() -> RunConfig:
    client = AsyncOpenAI(base_url=settings.openrouter_base_url, api_key=settings.openrouter_key, max_retries=4)
    provider = OpenAIProvider(
        openai_client=client,
        use_responses=False,              # OpenRouter: Chat Completions path
        strict_feature_validation=True,   # fail loudly on Responses-only features
        buffer_streamed_tool_calls=True,  # robust to chunked tool-call deltas
    )
    return RunConfig(model_provider=provider, tracing_disabled=True)
