"""Fixed questions for measuring cost/latency before and after optimizations."""
import asyncio, json, sys
from pathlib import Path
from pageindex_rag.runner import run_question

QUESTIONS = [
    "Which GNN architectures are used for financial fraud detection, and which financial area is most studied?",
    "Which papers handle class imbalance with SMOTE or resampling, and what results do they report?",
    "List all the documents related to adversarial machine learning research.",
]

async def main(label: str):
    rows = []
    for q in QUESTIONS:
        r = await run_question(q, "litreview", Path("data/pageindex"))
        rows.append(dict(q=q[:50], s=round(r.seconds), req=r.requests, tools=len(r.tool_calls), inp=r.input_tokens,
                         cached=r.cached_tokens, out=r.output_tokens, cost=round(r.cost_usd + r.tool_llm_cost_usd, 4),
                         cites=len(r.answer.citations) if r.answer else 0, err=r.error))
        print(json.dumps(rows[-1]))
    Path(f"bench/results").mkdir(exist_ok=True)
    Path(f"bench/results/cost_{label}.json").write_text(json.dumps(rows, indent=1))
    print("TOTAL cost", round(sum(r["cost"] for r in rows), 4), "time", sum(r["s"] for r in rows), "s")

asyncio.run(main(sys.argv[1]))
