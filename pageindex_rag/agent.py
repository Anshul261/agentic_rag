"""OpenAI Agents SDK adapter: wraps the plain tools in tools.py.

Runs on OpenRouter through Chat Completions (not the Responses API), with
strict feature validation so unsupported features fail loudly instead of
being silently dropped. SDK tracing to OpenAI is disabled.
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
from .tools import ToolContext

set_tracing_disabled(True)

INSTRUCTIONS = """You answer questions about a collection of documents by navigating their
section trees, like a researcher using tables of contents. You never see the full text up front.

How to work:
1. Find candidate documents and sections. Use list_documents to see every document's summary,
   and search_nodes for specific terms (methods, datasets, metrics, names).
2. Open get_tree for the most promising documents and reason over section titles and summaries
   to choose the nodes that should contain the answer.
3. read_nodes for just those nodes. For questions about diagrams, charts or architectures,
   use look_at_figure on the relevant figure node.
4. If what you read is not enough, go back to the trees and read more. Prefer several targeted
   reads over reading everything.
5. Answer only from what you read. Cite every claim inline as [n], where n indexes your
   citations list. If the collection does not contain the answer, say so plainly.
For comparisons across papers, cover each relevant paper explicitly."""


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
    Returns matching nodes with doc_id, node_id, pages and summary. Good for specific terms."""
    return tools.search_nodes(ctx.context, query)


@function_tool
def get_tree(ctx: RunContextWrapper[ToolContext], doc_id: str) -> str:
    """Show a document's section tree: node ids, titles, page ranges, sizes and summaries
    (figures and tables are tagged). Use it to decide which nodes to read."""
    return tools.get_tree(ctx.context, doc_id)


@function_tool
def read_nodes(ctx: RunContextWrapper[ToolContext], doc_id: str, node_ids: list[str]) -> str:
    """Read the full text of specific nodes of one document (with page numbers).
    Text of up to ~12k tokens per call; request fewer nodes if truncated."""
    return tools.read_nodes(ctx.context, doc_id, node_ids)


@function_tool
async def look_at_figure(ctx: RunContextWrapper[ToolContext], doc_id: str, node_id: str, question: str) -> str:
    """Ask a vision model a question about one figure node (diagram, chart, plot) of a document."""
    return await tools.look_at_figure(ctx.context, doc_id, node_id, question)


def build_agent() -> Agent[ToolContext]:
    return Agent[ToolContext](
        name="pageindex-researcher",
        instructions=INSTRUCTIONS,
        model=settings.reasoning_model,
        tools=[list_documents, search_nodes, get_tree, read_nodes, look_at_figure],
        output_type=Answer,
        model_settings=ModelSettings(include_usage=True, parallel_tool_calls=True),
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
