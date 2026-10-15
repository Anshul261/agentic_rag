"""Run one question through the agent and report answer + cost/latency metrics.

Shared by the CLI, the API server and the benchmark so all measure the same way.
Cost is OpenRouter's billed cost per response (usage accounting), not an estimate.
"""

from __future__ import annotations

import json
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from langchain_core.messages import AIMessage
from langgraph.errors import GraphRecursionError
from openai import APIError
from opentelemetry import trace

from .agent import ANSWER_TOOL, Answer, build_agent
from .llm import LLM
from .store import Store
from .tools import ToolContext

tracer = trace.get_tracer("pageindex_rag")


@dataclass
class RunReport:
    question: str
    answer: Answer | None
    error: str | None = None
    tool_calls: list[tuple[str, str]] = field(default_factory=list)  # (name, json arguments)
    seconds: float = 0.0
    requests: int = 0
    input_tokens: int = 0
    cached_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    cost_usd: float = 0.0  # agent model, billed
    tool_llm_cost_usd: float = 0.0  # figure inspection / extraction calls inside tools
    blocked_by_provider: bool = False  # model provider's own safety filter refused the request


PROVIDER_REFUSAL = ("I can't help with that request. I can answer questions about the documents in "
                    "this collection, including how the research describes attacks and defenses.")


def _is_provider_block(e: BaseException) -> bool:
    """The provider's safety filter refused the request.

    Shows up either as an explicit API error ("flagged", "content filter") or, through
    OpenRouter, as a completion with no choices, which the OpenAI client fails to parse.
    """
    text = str(e).lower()
    if isinstance(e, APIError):
        return "flagged" in text or "content filter" in text or "content_filter" in text
    if isinstance(e, ValueError):  # OpenRouter error object surfaced by langchain_openai
        return "'error_type': 'refusal'" in text or ("flagged" in text and "'code': 403" in text)
    if isinstance(e, TypeError) and "nonetype" in text:
        frames = "".join(traceback.format_tb(e.__traceback__))
        return "choices" in frames and ("openai/lib/_parsing" in frames or "langchain_openai" in frames)
    return False


def _account(report: RunReport, msg: AIMessage) -> None:
    report.requests += 1
    u = msg.usage_metadata or {}
    report.input_tokens += u.get("input_tokens", 0)
    report.output_tokens += u.get("output_tokens", 0)
    report.cached_tokens += (u.get("input_token_details") or {}).get("cache_read", 0) or 0
    report.reasoning_tokens += (u.get("output_token_details") or {}).get("reasoning", 0) or 0
    report.cost_usd += float(((msg.response_metadata or {}).get("token_usage") or {}).get("cost") or 0)


async def run_question(question: str, collection: str, data_dir: Path, store: Store | None = None,
                       max_turns: int = 15, on_tool: Callable[[str, str], None] | None = None,
                       thread_id: str | None = None, checkpointer=None) -> RunReport:
    """thread_id + checkpointer give multi-turn memory; without them each call is stateless."""
    llm = LLM()
    store = store or Store()
    ctx = ToolContext(store=store, collection=collection, data_dir=data_dir, llm=llm)
    agent = build_agent(collection, store, checkpointer=checkpointer if thread_id else None)
    config: dict = {"recursion_limit": 2 * max_turns + 1}
    if thread_id and checkpointer is not None:
        config["configurable"] = {"thread_id": thread_id}

    report = RunReport(question=question, answer=None)
    last_text: str | None = None
    t = time.time()
    with tracer.start_as_current_span("pageindex.question") as span:
        span.set_attribute("pageindex.collection", collection)
        if thread_id:
            span.set_attribute("pageindex.thread_id", thread_id)
        try:
            async for update in agent.astream({"messages": [{"role": "user", "content": question}]},
                                              context=ctx, config=config, stream_mode="updates"):
                for delta in update.values():
                    if not isinstance(delta, dict):
                        continue
                    for msg in delta.get("messages", []):
                        if isinstance(msg, AIMessage):
                            _account(report, msg)
                            for call in msg.tool_calls:
                                if call["name"] == ANSWER_TOOL:
                                    continue  # the final structured answer, not a retrieval step
                                args = json.dumps(call["args"], ensure_ascii=False)
                                report.tool_calls.append((call["name"], args))
                                if on_tool:
                                    on_tool(call["name"], args)
                    if delta.get("structured_response") is not None:
                        report.answer = delta["structured_response"]
                    last_text = next((m.content for m in reversed(delta.get("messages", []))
                                      if isinstance(m, AIMessage) and isinstance(m.content, str) and m.content.strip()),
                                     last_text)
            if report.answer is None and last_text:
                # Model answered in plain text instead of calling Answer: keep it rather than fail.
                report.answer = Answer(answer=last_text, citations=[])
            if report.answer is None and not report.error:
                report.error = "agent finished without an answer"
        except GraphRecursionError:
            report.error = f"stopped after {max_turns} turns without an answer"
        except Exception as e:
            if _is_provider_block(e):
                # Provider-side safety filter: answer with a refusal instead of failing the request.
                report.blocked_by_provider = True
                report.answer = Answer(answer=PROVIDER_REFUSAL, citations=[])
            elif isinstance(e, APIError):
                report.error = f"{type(e).__name__}: {e}"
            else:
                raise

        report.seconds = time.time() - t
        report.tool_llm_cost_usd = llm.cost_usd
        span.set_attribute("pageindex.cost_usd", report.cost_usd + report.tool_llm_cost_usd)
        span.set_attribute("pageindex.tool_calls", len(report.tool_calls))
        if report.error:
            span.set_status(trace.Status(trace.StatusCode.ERROR, report.error[:200]))
    return report


def format_report(r: RunReport) -> str:
    lines = []
    if r.answer:
        lines.append(f"\n{r.answer.answer}\n")
        for i, c in enumerate(r.answer.citations, 1):
            lines.append(f"  [{i}] {c.doc_title[:80]} — node {c.node_id}, p{c.pages}  ({c.doc_id})")
    if r.error:
        lines.append(f"\nERROR: {r.error}")
    lines.append(
        f"\n{r.seconds:.0f}s · {r.requests} model calls · {len(r.tool_calls)} tool calls · "
        f"{r.input_tokens:,} in ({r.cached_tokens:,} cached) / {r.output_tokens:,} out "
        f"({r.reasoning_tokens:,} reasoning) · ${r.cost_usd + r.tool_llm_cost_usd:.4f}")
    return "\n".join(lines)
