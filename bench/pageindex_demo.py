"""Prepare a three-question demo; inference occurs only with --run.

Both backends use the same pinned upstream traversal and cached local trees.
"""
import argparse
import hashlib
import json
import os
import time
from pathlib import Path

from jev_pageindex_bench import dataset, save
from jev_reference import ROOT, MODEL, SOURCE_SHA256, LocalPages, RecordedClient, reference

OUT = ROOT / "results/pageindex_demo"


def select_demo(qs, trees, count=3):
    selected, seen = [], set()
    for q in qs:
        doc = q["doc_name"]
        if doc in trees and doc not in seen:
            selected.append({"id": q["financebench_id"], "document": doc, "question": q["question"]})
            seen.add(doc)
        if len(selected) == count:
            break
    if len(selected) != count:
        raise ValueError("Demo requires three cached documents")
    return selected


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", choices=["jev", "gliner"], default="gliner")
    parser.add_argument("--context-budget", type=int, default=4096, help="GLiNER native categorical input-position budget")
    parser.add_argument("--label", default="", help="Safe output suffix for comparing configurations")
    parser.add_argument("--tree-dir",type=Path,help="Use a separate cached index directory, e.g. bench/data/pageindex_classic")
    parser.add_argument("--run", action="store_true", help="Run the three demo questions; otherwise prepare only")
    parser.add_argument("--answer", action="store_true", help="After retrieval, use shared Qwen answerer and GLM judge")
    args = parser.parse_args()
    if args.context_budget < 512 or args.context_budget > 4096:
        raise SystemExit("Validated demo GPU context budget is 512 to 4096 positions")
    if args.label and not all(c.isalnum() or c in "_-" for c in args.label):
        raise SystemExit("Label must use letters, digits, underscores, or hyphens")
    qs, pages, by_doc, trees, _, _ = dataset(args.tree_dir)
    manifest = select_demo(qs, trees)
    metadata = {"status": "prepared", "questions": manifest,
                "scope": "known_document_demo", "reference_source_sha256": SOURCE_SHA256,
                "backend": args.backend, "gliner_model": "fastino/GLiNER2.5-Decide",
                "gliner_device": "cuda", "native_context_budget": args.context_budget,
                "input_sha256": hashlib.sha256(json.dumps({"questions": manifest,
                    "trees": {q["document"]: trees[q["document"]] for q in manifest}}, sort_keys=True).encode()).hexdigest(),
                "note": "Three-document demo, not a full benchmark. Local PDF text and genuine local PageIndex trees."}
    metadata["adapter_source_sha256"] = hashlib.sha256((ROOT / "gliner_jev_adapter.py").read_bytes()).hexdigest()
    metadata["tree_directory"] = str((args.tree_dir or ROOT/'data/pageindex').resolve())
    if args.backend == "jev":
        metadata.update(jev_model=MODEL, typesafe_key_available=bool(os.environ.get("TYPESAFE_API_KEY")))
    save(OUT / "manifest.json", metadata)
    if not args.run:
        print(json.dumps(metadata, indent=2)); return
    if args.backend == "jev":
        if not os.environ.get("TYPESAFE_API_KEY"):
            raise SystemExit("Demo prepared. Running Jev needs TYPESAFE_API_KEY; no .env is read.")
        from typesafe_sdk import TypeSafeClient, RetryPolicy
        client = RecordedClient(TypeSafeClient(model=MODEL,
            retry=RetryPolicy(max_retries=5, backoff_initial=1., backoff_max=20.)))
    else:
        from gliner_jev_adapter import GLiNERClient
        client = GLiNERClient(max_context=args.context_budget)
        metadata.update(gliner_load_s=client.engine.load_sec, gliner_parameters=client.engine.params,
                        precision="bf16", gpu_batch=client.engine.batch_size)
    ref = reference(client)
    local = LocalPages(trees, by_doc)
    lookup = {(p["doc"], p["page"] + 1): i for i, p in enumerate(pages)}
    answers = None
    if args.answer:
        import bucket_gpu_bench as answers
        answers.PAGES = pages
        api = answers.Api()
    result = {"metadata": metadata, "backend": args.backend, "rows": []}
    output = OUT / f"{args.backend}{'_answers' if args.answer else ''}{'_' + args.label if args.label else ''}.json"
    for item in manifest:
        doc = item["document"]
        if args.backend == "gliner":
            client.set_document(doc, trees[doc], [by_doc[doc][p] for p in sorted(by_doc[doc])])
        first = len(client.events)
        started = time.perf_counter()
        found = ref.locate(local, doc, item["question"])
        ranked = sorted(found["pages"], key=lambda p: -found["page_scores"][p])
        row = {**item, "retrieval_s": time.perf_counter() - started, "ranked_pages": ranked,
               "retrieval": {k: v for k, v in found.items() if k != "text"},
               "events": client.events[first:]}
        # Gold pages are consulted only after retrieval, for diagnostics.
        q = next(q for q in qs if q["financebench_id"] == item["id"])
        gold = {e["evidence_page_num"]+1 for e in q["evidence"] if e["doc_name"] == doc}
        row["hit_at_3"] = bool(gold & set(ranked[:3]))
        row["section_hit"] = any(s["start"] <= p <= s["end"] for p in gold for s in found["sections"])
        if answers:
            row["evaluation"] = answers.read_and_judge(api, q, [lookup[(doc, p)] for p in ranked[:3]])
            usage=row["evaluation"]["answer"]["usage"]
            row["query_cost"]={"retrieval_api_requests":0 if args.backend=="gliner" else len(row["events"]),
                               "answer_llm_requests":1,"offline_judge_requests":2,
                               "answer_input_tokens":usage.get("prompt_tokens"),
                               "answer_output_tokens":usage.get("completion_tokens"),
                               "answer_estimated_usd":usage.get("estimated_cost"),
                               "note":"Indexing is ingestion work; judge calls are evaluation only. Local GPU compute cost is not estimated."}
        result["rows"].append(row)
        save(output, result)
        print(f"{item['id']}: {doc}, pages {ranked[:3]}, {row['retrieval_s']:.2f}s", flush=True)
    result["metadata"]["status"] = "demo_complete"
    result["summary"] = {"n":len(result["rows"]),"page_hits_at_3":sum(r["hit_at_3"] for r in result["rows"]),
                         "section_hits":sum(r["section_hit"] for r in result["rows"])}
    if answers:
        result["summary"]["correct_answers"] = sum(r["evaluation"]["correctness_judge"]["value"]["correct"] for r in result["rows"])
    save(output, result)


if __name__ == "__main__":
    main()
