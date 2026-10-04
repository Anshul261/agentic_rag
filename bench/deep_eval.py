"""Evaluate a common question cohort and retain per-question answers and judgments.

uv run --project bench --no-env-file bench/deep_eval.py bm25 hybrid llm_tree 'kev_rerank@k2-0.9b'
Original deep_eval.md is preserved. Output defaults to deep_eval_v2.md plus per-question JSON.
"""
import argparse
import concurrent.futures as cf
import json
import statistics as st
from pathlib import Path

from common import HERE, bootstrap_ci, load_doc, load_subset
from methods import llm, new_cost

MODEL = "zai-org/GLM-5.3-Flash"


def answer(q, pages, texts, model=MODEL, page_chars=6000):
    ctx = "\n\n".join(f"[page {p}]\n{texts[p][:page_chars]}" for p in pages) or "(no document pages provided)"
    result = llm(model, f"Answer the question using only these pages from a financial filing. If they do not contain the answer, say so.\n\n{ctx}\n\n"
                 f'Question: {q}\nReply only JSON: {{"answer":"short answer with units"}}', new_cost(), 600)
    if not isinstance(result.get("answer"), str): raise ValueError("Answerer returned no string answer")
    return result["answer"]


def judge(q, ref, got, model=MODEL):
    result = llm(model, f"Question: {q}\nReference answer: {ref}\nCandidate answer: {got}\n\nIs the candidate answer correct, i.e. consistent with the reference "
                 'on the key figure/fact (ignore formatting, rounding within 1%, extra explanation)? A candidate that says the information is missing is incorrect. Reply only JSON: {"correct":true|false}', new_cost(), 300)
    if type(result.get("correct")) is not bool: raise ValueError("Judge returned no boolean correct value")
    return result["correct"]


def section_metrics(rows):
    sections = [r for r in rows if r.get("sections") is not None]
    if not sections: return None, None
    return (st.mean(any(a <= p <= b for a, b in r["sections"] for p in r["gold"]) for r in sections),
            st.mean(len({p for a, b in r["sections"] for p in range(a, b + 1)}) for r in sections))


def validate_cohort(results, gold):
    for name, result in results.items():
        ids = [r["id"] for r in result["rows"]]
        if result.get("failed") or len(set(ids)) != len(ids) or set(ids) != set(gold):
            raise ValueError(f"{name}: failed, duplicate, or missing questions; use complete runs on the same cohort")
        for row in result["rows"]:
            if row["doc"] != gold[row["id"]]["doc"] or row["gold"] != gold[row["id"]]["gold"]:
                raise ValueError(f"{name}: document or evidence mismatch for {row['id']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("methods", nargs="+")
    ap.add_argument("--docs", type=int, default=10)
    ap.add_argument("--questions", type=int)
    ap.add_argument("--answer-model", default=MODEL)
    ap.add_argument("--judge-model", default=MODEL)
    ap.add_argument("--page-chars", type=int, default=6000)
    ap.add_argument("--output", default=str(HERE / "results/deep_eval_v2.md"))
    args = ap.parse_args()
    gold = {q["id"]: q for q in load_subset(args.docs, args.questions)}
    results = {name: json.loads((HERE / f"results/{name}.json").read_text()) for name in args.methods}
    validate_cohort(results, gold)
    picks = {"oracle": {qid: g["gold"] for qid, g in gold.items()}, "no_context": {qid: [] for qid in gold}}
    picks.update({name: {r["id"]: r["ranked"][:3] for r in result["rows"]} for name, result in results.items()})
    records = {}; lines = ["| method | n | answer correct, 95% CI | section recall | unique pages in sections | hit@3 |", "|---|---|---|---|---|---|"]
    for name, selected in picks.items():
        def one(item):
            qid, pages = item; g = gold[qid]; texts, _ = load_doc(g["doc"])
            got = answer(g["question"], pages, texts, args.answer_model, args.page_chars)
            return {"id": qid, "pages": pages, "answer": got, "correct": judge(g["question"], g["answer"], got, args.judge_model)}
        with cf.ThreadPoolExecutor(8) as ex: records[name] = list(ex.map(one, selected.items()))
        acc = st.mean(r["correct"] for r in records[name]); lo, hi = bootstrap_ci([r["correct"] for r in records[name]])
        rows = results.get(name, {}).get("rows", [])
        rec, size = section_metrics(rows)
        sr = f"{100 * rec:.1f}" if rec is not None else "-"
        sz = f"{size:.1f}" if size is not None else "-"
        h3 = f"{100 * st.mean(bool(set(r['gold']) & set(r['ranked'][:3])) for r in rows):.1f}" if rows else "-"
        lines.append(f"| {name} | {len(gold)} | {100 * acc:.1f} [{100 * lo:.1f}, {100 * hi:.1f}] | {sr} | {sz} | {h3} |")
        print(lines[-1], flush=True)
    path = Path(args.output); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + f"\n\nAnswerer: {args.answer_model}; judge: {args.judge_model}; maximum {args.page_chars} characters per page.\n")
    path.with_suffix(".json").write_text(json.dumps({"config": vars(args), "records": records}, indent=2))


if __name__ == "__main__": main()
