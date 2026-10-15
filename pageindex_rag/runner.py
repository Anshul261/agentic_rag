"""Run one question through the agent and report answer + cost/latency metrics.

Shared by the `ask` CLI and the benchmark so both measure the same way.
Cost is OpenRouter's billed cost per response (usage accounting), not an estimate.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from agents import Runner
from agents.exceptions import AgentsException

from .agent import Answer, build_agent, run_config
from .llm import LLM
from .store import Store
from .tools import ToolContext


@dataclass
class RunReport:
    question: str
    answer: Answer | None
    error: str | None = None
    tool_calls: list[tuple[str, str]] = field(default_factory=list)  # (name, arguments)
    seconds: float = 0.0
    requests: int = 0
    input_tokens: int = 0
    cached_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    cost_usd: float = 0.0  # agent model, billed
    tool_llm_cost_usd: float = 0.0  # figure-inspection calls inside tools


async def run_question(question: str, collection: str, data_dir: Path, store: Store | None = None,
                       max_turns: int = 15, on_tool: Callable[[str, str], None] | None = None) -> RunReport:
    llm = LLM()
    ctx = ToolContext(store=store or Store(), collection=collection, data_dir=data_dir, llm=llm)
    report = RunReport(question=question, answer=None)
    t = time.time()
    result = Runner.run_streamed(build_agent(collection, ctx.store), question, context=ctx,
                                 max_turns=max_turns, run_config=run_config())
    try:
        async for ev in result.stream_events():
            if ev.type == "run_item_stream_event" and ev.name == "tool_called":
                raw = ev.item.raw_item
                name = getattr(raw, "name", None) or raw.get("name", "?")
                args = getattr(raw, "arguments", None) or raw.get("arguments", "") or ""
                report.tool_calls.append((name, args))
                if on_tool:
                    on_tool(name, args)
        report.answer = result.final_output
    except AgentsException as e:  # max turns, model behaviour errors, guardrails
        report.error = f"{type(e).__name__}: {e}"

    report.seconds = time.time() - t
    u = result.context_wrapper.usage
    report.requests = u.requests
    report.input_tokens = u.input_tokens
    report.output_tokens = u.output_tokens
    report.cached_tokens = getattr(u.input_tokens_details, "cached_tokens", 0) or 0
    report.reasoning_tokens = getattr(u.output_tokens_details, "reasoning_tokens", 0) or 0
    report.cost_usd = sum(float((r.raw_usage or {}).get("cost") or 0) for r in result.raw_responses)
    report.tool_llm_cost_usd = llm.cost_usd
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
