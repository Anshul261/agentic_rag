"""Build shared, query-independent section summaries from every page in each section.

uv run --project bench --no-env-file bench/summaries.py --output bench/data/summaries.json
Requires HF_TOKEN in the process environment. No gold answers or questions are used.
"""
import argparse
import hashlib
import json
from pathlib import Path

from common import load_doc, load_subset
from methods import llm, new_cost


def fingerprint(texts, nodes):
    structure = [{k: v for k, v in n.items() if k != "summary"} for n in nodes]
    return hashlib.sha256(json.dumps([texts, structure], sort_keys=True).encode()).hexdigest()


def read_summaries(path, doc, texts, nodes):
    entry = json.loads(Path(path).read_text())["documents"][doc]
    if entry["fingerprint"] != fingerprint(texts, nodes):
        raise ValueError(f"Stale summaries for {doc}; regenerate against the current index")
    if set(entry["summaries"]) != {str(n["id"]) for n in nodes}:
        raise ValueError(f"Incomplete summaries for {doc}")
    return [{**n, "summary": entry["summaries"][str(n["id"])]} for n in nodes]


def summarize(model, title, body, cost):
    result = llm(model, "Summarize this financial-filing section for document retrieval. "
                 "Use at most 60 words. Name the topics, financial statements, metrics, and years actually covered. "
                 "Do not invent figures. Return only JSON: {\"summary\":\"text\"}.\n\n"
                 f"Title: {title}\nContent:\n{body}", cost, 350)
    summary = result.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise ValueError("Summary model returned no summary")
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--docs", type=int, default=10)
    ap.add_argument("--model", default="zai-org/GLM-5.3-Flash")
    ap.add_argument("--output", required=True)
    args = ap.parse_args()
    path = Path(args.output)
    output = json.loads(path.read_text()) if path.exists() else {"model": args.model, "documents": {}}
    if output["model"] != args.model: raise ValueError("Use a separate output for a different summary model")
    for doc in sorted({q["doc"] for q in load_subset(args.docs)}):
        texts, nodes = load_doc(doc)
        fp = fingerprint(texts, nodes)
        entry = output["documents"].get(doc)
        if entry and entry["fingerprint"] == fp: continue
        cost = new_cost(); summaries = {}; page_summaries = {}
        # Read all text, in bounded chunks. Reuse page descriptions across overlapping sections.
        for p, text in enumerate(texts):
            parts = [summarize(args.model, f"{doc}, page {p}", text[i:i + 12000], cost)
                     for i in range(0, len(text), 12000)]
            page_summaries[p] = " ".join(parts) or "Blank page."
        for node in nodes:
            blocks = [f"Page {p}: {page_summaries[p]}" for p in range(node["start"], node["end"] + 1)]
            # Recursive reductions keep the entire section represented without prefix truncation.
            while sum(len(b) + 1 for b in blocks) > 12000:
                groups, group, size = [], [], 0
                for block in blocks:
                    if group and size + len(block) + 1 > 12000: groups.append(group); group, size = [], 0
                    group.append(block); size += len(block) + 1
                if group: groups.append(group)
                blocks = [summarize(args.model, node["title"], "\n".join(group), cost) for group in groups]
            summaries[str(node["id"])] = summarize(args.model, node["title"], "\n".join(blocks), cost)
        output["documents"][doc] = {"fingerprint": fp, "summaries": summaries, "cost": cost}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(output, indent=2))
        print(f"{doc}: {len(summaries)} summaries, {cost['api_tokens']} API tokens", flush=True)


if __name__ == "__main__": main()
