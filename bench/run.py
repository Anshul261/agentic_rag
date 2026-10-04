"""Run retrieval methods over the FinanceBench subset and save per-question results.

  uv run run.py --methods bm25 dense hybrid llm_tree
  uv run run.py --methods kev_rerank kev_tree --kev-url http://127.0.0.1:8009 --label kev4b-q8
  uv run run.py --methods kev_rerank kev_tree --label smoke --questions 3     # quick check

A question whose search raises (e.g. the Kev server is still down after retries) goes to "failed", never to "rows",
so it is not scored as a miss; the run exits non-zero if any question failed.
"""
import argparse, hashlib, json, sys, time

from common import HERE, load_subset
from methods import REGISTRY

ap = argparse.ArgumentParser()
ap.add_argument("--methods", nargs="+", required=True)
ap.add_argument("--docs", type=int, default=10)
ap.add_argument("--questions", type=int, default=None, help="first N questions only (smoke test)")
ap.add_argument("--kev-url", default="http://127.0.0.1:8009")
ap.add_argument("--tokenizer", default=None, help="tokenizer.json of the served model (needed for non-llama.cpp servers, e.g. K2-Type)")
ap.add_argument("--label", default="", help="suffix for kev methods, e.g. kev4b-q8, so several Kev variants can sit side by side")
ap.add_argument("--choice-mode", choices=["full", "snippet"], default="full", help="K2 requires snippet: its server cuts Choice options to 128 tokens")
ap.add_argument("--summaries", help="Shared query-independent summaries JSON from summaries.py")
ap.add_argument("--overwrite", action="store_true", help="Explicitly replace an existing result")
a = ap.parse_args()

subset = load_subset(a.docs)[:a.questions]
by_doc = {}
for q in subset: by_doc.setdefault(q["doc"], []).append(q)

n_failed = 0
for name in a.methods:
    tag = f"{name}@{a.label}" if a.label else name
    result_path = HERE / f"results/{tag}.json"
    if result_path.exists() and not a.overwrite: raise SystemExit(f"{result_path} exists; use a new --label or --overwrite")
    m = REGISTRY[name](kev_url=a.kev_url, tokenizer=a.tokenizer, choice_mode=a.choice_mode, summaries=a.summaries)
    rows, failed, index_sec = [], [], {}
    for doc, qs in by_doc.items():
        t = time.perf_counter()
        try:
            m.index(doc); index_sec[doc] = time.perf_counter() - t
            if name.startswith("kev") and not rows and not failed: m.search(qs[0]["question"])
        except Exception as e:
            failed.extend({"id": q["id"], "doc": doc, "gold": q["gold"], "error": repr(e)} for q in qs)
            print(f"{tag} index/warm-up FAILED {doc}: {e!r}", file=sys.stderr)
            continue
        for q in qs:
            t = time.perf_counter()
            try: r = m.search(q["question"])
            except Exception as e:
                failed.append({"id": q["id"], "doc": doc, "gold": q["gold"], "error": repr(e)})
                print(f"\n{tag} FAILED {q['id']}: {e!r}", file=sys.stderr); continue
            wall = time.perf_counter() - t
            c = r["cost"]  # cached API calls: swap the wall time of the cache read for the latency recorded when the call was made
            lat = wall - c["api_wall"] + c["api_sec"]
            rows.append({"id": q["id"], "doc": doc, "gold": q["gold"], "ranked": r["ranked"][:10], "conf": r["conf"], "kept": r.get("kept"), "sections": r.get("sections"), "latency": lat, **c})
            print(f"\r{tag} {len(rows)}/{len(subset)} ({len(failed)} failed)", end="", flush=True)
    metadata = {"args": vars(a), "question_ids": [q["id"] for q in subset],
                "code_sha256": hashlib.sha256((HERE / "methods.py").read_bytes() + (HERE / "common.py").read_bytes()).hexdigest(),
                "model": getattr(getattr(m, "kev", None), "model", getattr(m, "model", None)),
                "summary_sha256": hashlib.sha256(open(a.summaries, "rb").read()).hexdigest() if a.summaries else None}
    json.dump({"method": tag, "metadata": metadata, "index_sec": index_sec, "rows": rows, "failed": failed}, open(result_path, "w"))
    print(); n_failed += len(failed)
sys.exit(1 if n_failed else 0)
